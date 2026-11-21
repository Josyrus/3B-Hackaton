"""Puertos (interfaces) para desacoplar OCR, PDF y LLM. Adaptadores locales incluidos."""
from __future__ import annotations

import io
import json
from typing import Protocol

from .contracts import PageText
from .normalization import text_quality

OCR_UNKNOWN_CONFIDENCE = 80.0   # OCR sin medida de confianza: sirve para leer, pero nunca para sustentar un "No cumple" (<85)


class PDFTextPort(Protocol):
    def extract_pages(self, data: bytes) -> list[PageText]: ...


class OCRPort(Protocol):
    def ocr_image(self, png_bytes: bytes) -> str: ...
    # Opcional: `ocr_page(png_bytes) -> OCRPageResult` (texto + confianza). Si falta, se usa ocr_image.


class LLMPort(Protocol):
    def complete_json(self, system: str, user: str) -> dict: ...


class PDFCorruptError(Exception):
    pass


class PyMuPDFExtractor:
    """Extrae texto por página. Una página se trata como ESCANEADA (se aplica OCR aunque tenga algo de texto
    embebido, p. ej. marcas de agua) si está dominada por una imagen o su capa de texto es corrupta/escasa."""

    def __init__(self, ocr: OCRPort | None = None, min_chars: int = 20, min_quality: float = 0.8,
                 scan_coverage: float = 0.6, ocr_dpi: int = 300, ocr_min_confidence: float = 65.0,
                 max_pages: int = 300) -> None:
        self.ocr, self.min_chars, self.min_quality = ocr, min_chars, min_quality
        self.scan_coverage, self.ocr_dpi, self.ocr_min_confidence, self.max_pages = scan_coverage, ocr_dpi, ocr_min_confidence, max_pages

    @staticmethod
    def _image_coverage(page) -> float:
        """Fracción aproximada de la página cubierta por imágenes (≈1.0 en un escaneo)."""
        try:
            import pymupdf
            area = float(page.rect.width * page.rect.height) or 1.0
            total = 0.0
            for info in page.get_image_info():
                r = pymupdf.Rect(info["bbox"]) & page.rect
                if not r.is_empty:
                    total += r.width * r.height
            return min(total / area, 1.0)
        except Exception:  # sin información de imágenes: se decide solo por el texto
            return 0.0

    def _ocr(self, png: bytes) -> tuple[str, float, bool]:
        """(texto, confianza 0-100, en_blanco)."""
        assert self.ocr is not None
        if hasattr(self.ocr, "ocr_page"):
            r = self.ocr.ocr_page(png)
            return r.text, float(r.confidence), bool(r.blank)
        text = self.ocr.ocr_image(png)
        return text, (OCR_UNKNOWN_CONFIDENCE if text.strip() else 0.0), False

    def _page(self, page, number: int) -> PageText:
        try:
            native = page.get_text().strip()
        except Exception:
            native = ""
        coverage = self._image_coverage(page)
        native_ok = len(native) >= self.min_chars and text_quality(native) >= self.min_quality
        if native_ok and coverage < self.scan_coverage:
            return PageText(page=number, text=native, method="native", ocr_confidence=100.0)
        if self.ocr is None:  # sin OCR disponible: no se inventa texto; una página escaneada queda como ilegible (confianza 0)
            if not native and coverage < 0.05:
                return PageText(page=number, text="", method="native", ocr_confidence=100.0, blank=True)
            return PageText(page=number, text=native, method="native", ocr_confidence=0.0)
        text, conf, blank = self._ocr(page.get_pixmap(dpi=self.ocr_dpi).tobytes("png"))
        if blank:
            return PageText(page=number, text="", method="ocr", ocr_confidence=100.0, blank=True)
        if conf < self.ocr_min_confidence and native_ok:  # respaldo: una capa de texto buena vence a un OCR malo
            return PageText(page=number, text=native, method="native", ocr_confidence=100.0)
        return PageText(page=number, text=text, method="ocr", ocr_confidence=round(conf, 2))

    def extract_pages(self, data: bytes) -> list[PageText]:
        import pymupdf
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
            if doc.needs_pass:
                raise PDFCorruptError("PDF protegido con contraseña")
            pages: list[PageText] = []
            for i, page in enumerate(doc, 1):
                if i > self.max_pages:
                    break
                try:
                    pages.append(self._page(page, i))
                except PDFCorruptError:
                    raise
                except Exception:  # una página dañada no tumba todo el documento: queda ilegible y se avisa
                    pages.append(PageText(page=i, text="", method="ocr", ocr_confidence=0.0))
            if not pages:
                raise PDFCorruptError("PDF sin páginas")
            return pages
        except PDFCorruptError:
            raise
        except Exception as exc:  # pymupdf lanza varios tipos
            raise PDFCorruptError(f"PDF ilegible: {type(exc).__name__}") from exc


class TesseractOCR:
    """OCR local con Tesseract + OpenCV (ver core/ocr.py). Requiere el binario y los paquetes opcionales."""

    def __init__(self, lang: str = "spa") -> None:
        self.lang = lang

    def ocr_page(self, png_bytes: bytes):
        from .ocr import ocr_png  # dependencias opcionales (cv2/pytesseract): solo con OCR_BACKEND=tesseract
        return ocr_png(png_bytes, self.lang)

    def ocr_image(self, png_bytes: bytes) -> str:
        return self.ocr_page(png_bytes).text

    def language_warning(self) -> str | None:
        from .ocr import resolve_language
        return resolve_language(self.lang)[1]


class OllamaLLM:
    """LLM local vía LangChain + Ollama. Temperatura 0 para reproducibilidad. Configuración centralizada: el modelo se
    construye una sola vez; cambiar de proveedor implica implementar `LLMPort` (p. ej. otro chat model de LangChain)."""

    def __init__(self, model: str, base_url: str, num_ctx: int = 16384) -> None:
        self.model, self.base_url, self.num_ctx = model, base_url, num_ctx
        self._llm = None

    def _client(self):
        if self._llm is None:
            from langchain_ollama import ChatOllama
            self._llm = ChatOllama(model=self.model, base_url=self.base_url, temperature=0, format="json", seed=7,
                                   num_ctx=self.num_ctx)  # num_ctx alto: el valor por defecto trunca documentos largos en silencio
        return self._llm

    def complete_json(self, system: str, user: str) -> dict:
        from langchain_core.messages import HumanMessage, SystemMessage
        return json.loads(self._client().invoke([SystemMessage(content=system), HumanMessage(content=user)]).content)
