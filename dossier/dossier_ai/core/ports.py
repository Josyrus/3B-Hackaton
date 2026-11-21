"""Puertos (interfaces) para desacoplar OCR, PDF y LLM. Adaptadores locales incluidos."""
from __future__ import annotations

import io
import json
from typing import Protocol

from .contracts import PageText


class PDFTextPort(Protocol):
    def extract_pages(self, data: bytes) -> list[PageText]: ...


class OCRPort(Protocol):
    def ocr_image(self, png_bytes: bytes) -> str: ...


class LLMPort(Protocol):
    def complete_json(self, system: str, user: str) -> dict: ...


class PDFCorruptError(Exception):
    pass


class PyMuPDFExtractor:
    """Extrae texto por página; aplica OCR a páginas sin texto si hay OCR disponible."""

    def __init__(self, ocr: OCRPort | None = None, min_chars: int = 20) -> None:
        self.ocr, self.min_chars = ocr, min_chars

    def extract_pages(self, data: bytes) -> list[PageText]:
        import pymupdf
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
            if doc.needs_pass:
                raise PDFCorruptError("PDF protegido con contraseña")
            pages = []
            for i, page in enumerate(doc, 1):
                text = page.get_text()
                if len(text.strip()) < self.min_chars and self.ocr:
                    text = self.ocr.ocr_image(page.get_pixmap(dpi=200).tobytes("png"))
                pages.append(PageText(page=i, text=text))
            if not pages:
                raise PDFCorruptError("PDF sin páginas")
            return pages
        except PDFCorruptError:
            raise
        except Exception as exc:  # pymupdf lanza varios tipos
            raise PDFCorruptError(f"PDF ilegible: {type(exc).__name__}") from exc


class TesseractOCR:
    """OCR local con Tesseract (requiere binario instalado y pytesseract)."""

    def __init__(self, lang: str = "spa") -> None:
        self.lang = lang

    def ocr_image(self, png_bytes: bytes) -> str:
        import pytesseract
        from PIL import Image
        return pytesseract.image_to_string(Image.open(io.BytesIO(png_bytes)), lang=self.lang)


class PaddleOCRAdapter:
    """Adaptador de OCR local usando PaddleOCR (compatible con PaddleOCR 2.x y 3.x+).

    Basado en la implementación y documentación oficial en español:
    https://github.com/PaddlePaddle/PaddleOCR/blob/main/readme/README_es.md

    Características:
      - Soporta idioma español ('es'), inglés ('en'), etc.
      - Incluye clasificación de orientación de texto (`use_angle_cls` / `use_textline_orientation`) para imágenes rotadas.
      - Procesamiento por CPU o aceleración con GPU (`use_gpu=True` / `device='gpu'`).
      - Desactiva MKL-DNN en CPU cuando aplica para evitar incompatibilidades en Linux.
      - Salida en texto plano compatible con OCRPort o detallada con bounding boxes y confianza.
    """

    def __init__(
        self,
        lang: str = "es",
        use_angle_cls: bool = True,
        use_gpu: bool = False,
        confidence_threshold: float = 0.0,
        show_log: bool = False,
        **extra_kwargs,
    ) -> None:
        self.lang = lang
        self.use_angle_cls = use_angle_cls
        self.use_gpu = use_gpu
        self.confidence_threshold = confidence_threshold
        self.show_log = show_log
        self.extra_kwargs = extra_kwargs
        self._ocr = None

    def _get_engine(self):
        if self._ocr is None:
            try:
                import inspect
                from paddleocr import PaddleOCR
            except ImportError as exc:
                raise ImportError(
                    "PaddleOCR no está instalado. Para utilizarlo, instálalo con:\n"
                    "  pip install paddlepaddle paddleocr\n"
                    "Consulta la documentación en https://github.com/PaddlePaddle/PaddleOCR/blob/main/readme/README_es.md"
                ) from exc

            # Detectar compatibilidad de parámetros entre PaddleOCR 2.x y 3.x
            init_params = inspect.signature(PaddleOCR.__init__).parameters
            kwargs = dict(self.extra_kwargs)

            # Idioma
            if "lang" in init_params:
                kwargs["lang"] = self.lang

            # Compatibilidad PaddleOCR 3.x vs 2.x
            if "use_textline_orientation" in init_params:
                kwargs["use_textline_orientation"] = self.use_angle_cls
                kwargs["device"] = "gpu" if self.use_gpu else "cpu"
                if not self.use_gpu:
                    kwargs["enable_mkldnn"] = False
            else:
                kwargs["use_angle_cls"] = self.use_angle_cls
                kwargs["use_gpu"] = self.use_gpu

            if "show_log" in init_params:
                kwargs["show_log"] = self.show_log

            self._ocr = PaddleOCR(**kwargs)
        return self._ocr

    def ocr_image(self, png_bytes: bytes) -> str:
        """Extrae y concatena el texto de una imagen en bytes (PNG/JPG). Cumple la interfaz OCRPort."""
        detailed = self.ocr_image_detailed(png_bytes)
        return "\n".join(item["text"] for item in detailed)

    def ocr_image_detailed(self, image_input: bytes | str) -> list[dict]:
        """Extrae texto detallado con cuadros delimitadores (bounding boxes) y puntuación de confianza.

        Soporta los formatos de retorno tanto de PaddleOCR 2.x (lista anidada)
        como de PaddleOCR 3.x (OCRResult con rec_texts, rec_scores, rec_polys).
        """
        import numpy as np
        from PIL import Image

        engine = self._get_engine()

        if isinstance(image_input, (bytes, bytearray)):
            img = Image.open(io.BytesIO(image_input)).convert("RGB")
            img_target = np.array(img)
        elif isinstance(image_input, str):
            img_target = image_input
        else:
            img_target = np.array(image_input)

        # Usar predict si existe (PaddleOCR 3.x) o ocr (PaddleOCR 2.x)
        if hasattr(engine, "predict") and not getattr(engine, "_is_mock", False):
            raw_res = list(engine.predict(img_target))
        elif hasattr(engine, "ocr"):
            try:
                raw_res = engine.ocr(img_target, cls=self.use_angle_cls)
            except TypeError:
                raw_res = engine.ocr(img_target)
        else:
            raw_res = []

        return self._parse_ocr_result(raw_res)

    def _parse_ocr_result(self, raw_res: list | Any) -> list[dict]:
        """Parsea la salida de PaddleOCR (versiones 2.x y 3.x)."""
        lines: list[dict] = []
        if not raw_res:
            return lines

        first_entry = raw_res[0] if isinstance(raw_res, list) and len(raw_res) > 0 else raw_res

        # Formato PaddleOCR 3.x (objeto OCRResult o dict con claves 'rec_texts')
        if hasattr(first_entry, "get") and first_entry.get("rec_texts") is not None:
            texts = first_entry.get("rec_texts", [])
            scores = first_entry.get("rec_scores", [])
            polys = first_entry.get("rec_polys", [])
            for idx, text in enumerate(texts):
                score = float(scores[idx]) if idx < len(scores) else 1.0
                if score >= self.confidence_threshold:
                    poly = polys[idx] if idx < len(polys) else []
                    if hasattr(poly, "tolist"):
                        poly = poly.tolist()
                    lines.append({
                        "box": poly,
                        "text": str(text).strip(),
                        "confidence": round(score, 4),
                    })
            return lines

        # Formato PaddleOCR 2.x (lista anidada: [[[box, (text, score)], ...]])
        if isinstance(first_entry, list):
            for entry in first_entry:
                if not entry or len(entry) < 2:
                    continue
                box = entry[0]
                if hasattr(box, "tolist"):
                    box = box.tolist()
                text_info = entry[1]
                if isinstance(text_info, (list, tuple)) and len(text_info) >= 2:
                    text, score = str(text_info[0]).strip(), float(text_info[1])
                    if text and score >= self.confidence_threshold:
                        lines.append({
                            "box": box,
                            "text": text,
                            "confidence": round(score, 4),
                        })
        return lines


class OllamaLLM:
    """LLM local vía LangChain + Ollama. Temperatura 0 para reproducibilidad."""

    def __init__(self, model: str, base_url: str) -> None:
        self.model, self.base_url = model, base_url

    def complete_json(self, system: str, user: str) -> dict:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_ollama import ChatOllama
        llm = ChatOllama(model=self.model, base_url=self.base_url, temperature=0, format="json", seed=7)
        return json.loads(llm.invoke([SystemMessage(content=system), HumanMessage(content=user)]).content)
