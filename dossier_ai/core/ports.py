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


class OllamaLLM:
    """LLM local vía LangChain + Ollama. Temperatura 0 para reproducibilidad."""

    def __init__(self, model: str, base_url: str) -> None:
        self.model, self.base_url = model, base_url

    def complete_json(self, system: str, user: str) -> dict:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_ollama import ChatOllama
        llm = ChatOllama(model=self.model, base_url=self.base_url, temperature=0, format="json", seed=7)
        return json.loads(llm.invoke([SystemMessage(content=system), HumanMessage(content=user)]).content)
