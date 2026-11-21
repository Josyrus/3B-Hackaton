"""Pruebas unitarias para la integración de PaddleOCR (core/ports.py y apps/documents/services.py)."""
import io
import sys
import unittest
from unittest.mock import MagicMock, patch

# Pre-importar numpy para evitar recarga de módulo C en Python 3.14
import numpy as np
from PIL import Image

# Si pydantic no está en el entorno local del sistema, proveer mock para probar core.ports
if "pydantic" not in sys.modules:
    try:
        import pydantic  # noqa: F401
    except ImportError:
        mock_pydantic = MagicMock()
        mock_pydantic.BaseModel = object
        sys.modules["pydantic"] = mock_pydantic

from core.ports import OCRPort, PaddleOCRAdapter, PyMuPDFExtractor


class TestPaddleOCRAdapter(unittest.TestCase):
    def test_implements_ocr_port_interface(self):
        adapter = PaddleOCRAdapter(lang="es", use_angle_cls=True)
        self.assertTrue(hasattr(adapter, "ocr_image"))
        self.assertTrue(callable(adapter.ocr_image))

    def test_missing_paddleocr_raises_informative_error(self):
        adapter = PaddleOCRAdapter()

        real_import = __import__

        def mock_import(name, *args, **kwargs):
            if name == "paddleocr":
                raise ImportError("No module named 'paddleocr'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with self.assertRaises(ImportError) as ctx:
                adapter.ocr_image(b"fake_png_data")
            msg = str(ctx.exception)
            self.assertIn("pip install paddlepaddle paddleocr", msg)
            self.assertIn("README_es.md", msg)

    def test_ocr_image_parsing_and_filtering(self):
        adapter = PaddleOCRAdapter(lang="es", use_angle_cls=True, confidence_threshold=0.5)

        # Simular salida oficial de PaddleOCR (ver README_es.md)
        mock_raw_result = [
            [
                [[[10, 10], [100, 10], [100, 30], [10, 30]], ("ESCRITURA PUBLICA", 0.985)],
                [[[10, 40], [200, 40], [200, 60], [10, 60]], ("TITULAR: JUAN PEREZ", 0.950)],
                [[[10, 70], [50, 70], [50, 90], [10, 90]], ("RUIDO ILEGIBLE", 0.250)],
            ]
        ]

        mock_engine = MagicMock()
        mock_engine.ocr.return_value = mock_raw_result
        adapter._ocr = mock_engine

        # Generar una imagen sintética en memoria
        img = Image.new("RGB", (100, 100), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        # ocr_image filtra por confidence_threshold (0.5), ignorando "RUIDO ILEGIBLE"
        text = adapter.ocr_image(png_bytes)
        self.assertEqual(text, "ESCRITURA PUBLICA\nTITULAR: JUAN PEREZ")

        # ocr_image_detailed retorna cajas y métricas
        detailed = adapter.ocr_image_detailed(png_bytes)
        self.assertEqual(len(detailed), 2)
        self.assertEqual(detailed[0]["text"], "ESCRITURA PUBLICA")
        self.assertEqual(detailed[0]["confidence"], 0.985)
        self.assertEqual(detailed[0]["box"], [[10, 10], [100, 10], [100, 30], [10, 30]])

        # Verificar que cls=True fue enviado por use_angle_cls
        mock_engine.ocr.assert_called_with(unittest.mock.ANY, cls=True)

    def test_ocr_empty_or_no_text_detected(self):
        adapter = PaddleOCRAdapter()
        mock_engine = MagicMock()
        mock_engine.ocr.return_value = [None]
        adapter._ocr = mock_engine

        img = Image.new("RGB", (50, 50), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        text = adapter.ocr_image(buf.getvalue())
        self.assertEqual(text, "")
        self.assertEqual(adapter.ocr_image_detailed(buf.getvalue()), [])

    def test_pymupdf_extractor_triggers_ocr_when_text_empty(self):
        mock_ocr = MagicMock(spec=OCRPort)
        mock_ocr.ocr_image.return_value = "TEXTO EXTRAIDO POR PADDLEOCR"

        extractor = PyMuPDFExtractor(ocr=mock_ocr, min_chars=10)

        mock_page = MagicMock()
        mock_page.get_text.return_value = "   "  # Menos de min_chars
        mock_pixmap = MagicMock()
        mock_pixmap.tobytes.return_value = b"fake_png"
        mock_page.get_pixmap.return_value = mock_pixmap

        mock_doc = MagicMock()
        mock_doc.needs_pass = False
        mock_doc.__iter__.return_value = [mock_page]

        # Simular PageText contract
        class DummyPageText:
            def __init__(self, page, text):
                self.page = page
                self.text = text

        mock_pymupdf = MagicMock()
        mock_pymupdf.open.return_value = mock_doc

        with patch.dict(sys.modules, {"pymupdf": mock_pymupdf}), \
             patch("core.ports.PageText", side_effect=DummyPageText):
            pages = extractor.extract_pages(b"%PDF-1.4...")

        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].page, 1)
        self.assertEqual(pages[0].text, "TEXTO EXTRAIDO POR PADDLEOCR")
        mock_ocr.ocr_image.assert_called_once_with(b"fake_png")


class TestPaddleOCRToolCLI(unittest.TestCase):
    def test_process_image_with_custom_engine(self):
        from scripts.paddle_ocr_tool import process_image

        mock_engine = MagicMock()
        mock_engine.ocr.return_value = [
            [
                [[[0, 0], [10, 0], [10, 10], [0, 10]], ("TITULO", 0.99)],
            ]
        ]
        img = Image.new("RGB", (20, 20), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        lines = process_image(buf.getvalue(), engine=mock_engine)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["text"], "TITULO")
        self.assertEqual(lines[0]["confidence"], 0.99)

    def test_draw_and_save_visualization(self):
        import tempfile
        from scripts.paddle_ocr_tool import draw_and_save_visualization

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as in_f, \
             tempfile.NamedTemporaryFile(suffix=".png", delete=False) as out_f:
            img = Image.new("RGB", (100, 100), color="white")
            img.save(in_f.name)
            in_path = in_f.name
            out_path = out_f.name

        try:
            sample_lines = [{
                "box": [[10, 10], [80, 10], [80, 40], [10, 40]],
                "text": "PRUEBA",
                "confidence": 0.95,
            }]
            draw_and_save_visualization(in_path, sample_lines, out_path)
            with Image.open(out_path) as res_img:
                self.assertEqual(res_img.size, (100, 100))
        finally:
            import os
            if os.path.exists(in_path):
                os.remove(in_path)
            if os.path.exists(out_path):
                os.remove(out_path)


if __name__ == "__main__":
    unittest.main()
