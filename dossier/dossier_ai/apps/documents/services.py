"""Carga segura de PDF/ZIP, almacenamiento privado y extracción de texto."""
from __future__ import annotations

import hashlib
import io
import stat
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.db import transaction

from core.ports import OCRPort, PDFCorruptError, PyMuPDFExtractor
from .models import Classification, DocStatus, Document, DocumentPage


MAX_COMPRESSION_RATIO = 200  # ratio descomprimido/comprimido a partir del cual un miembro se considera zip bomb


class UploadRejected(ValueError):
    """Archivo rechazado antes de crear el expediente (formato, tamaño, ZIP malicioso)."""


@dataclass
class UploadItem:
    name: str
    data: bytes


@dataclass
class IngestReport:
    created: list[Document] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def get_ocr() -> OCRPort | None:
    if settings.OCR_BACKEND == "tesseract":
        from core.ports import TesseractOCR
        return TesseractOCR(lang=getattr(settings, "OCR_LANG", "spa"))
    return None


def safe_name(name: str) -> str:
    """Solo el nombre base: elimina rutas y caracteres de control (path traversal)."""
    base = PurePosixPath(name.replace("\\", "/")).name
    return "".join(c for c in base if c.isprintable())[:200] or "documento.pdf"


def expand_uploads(files: list[tuple[str, bytes]]) -> list[UploadItem]:
    """Valida y expande PDF/ZIP en una lista de PDF. Lanza UploadRejected ante cualquier anomalía."""
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    items: list[UploadItem] = []
    for name, data in files:
        lower = name.lower()
        if len(data) > limit:
            raise UploadRejected(f"'{safe_name(name)}' excede el límite de {settings.MAX_UPLOAD_MB} MB.")
        if lower.endswith(".zip"):
            items.extend(_expand_zip(name, data))
        elif lower.endswith(".pdf"):
            if not data.startswith(b"%PDF"):
                raise UploadRejected(f"'{safe_name(name)}' no tiene estructura PDF válida.")
            items.append(UploadItem(safe_name(name), data))
        else:
            raise UploadRejected(f"Formato no permitido: '{safe_name(name)}'. Solo PDF o ZIP con PDF.")
    if not items:
        raise UploadRejected("No se recibió ningún PDF.")
    return items


def _expand_zip(name: str, data: bytes) -> list[UploadItem]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UploadRejected(f"ZIP corrupto: '{safe_name(name)}'.") from exc
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > settings.MAX_ZIP_ENTRIES:
        raise UploadRejected("El ZIP contiene demasiados archivos.")
    if sum(i.file_size for i in infos) > settings.MAX_ZIP_UNCOMPRESSED_MB * 1024 * 1024:
        raise UploadRejected("El ZIP excede el tamaño descomprimido permitido (posible zip bomb).")
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    out: list[UploadItem] = []
    for info in infos:
        parts = PurePosixPath(info.filename.replace("\\", "/")).parts
        if info.filename.startswith(("/", "\\")) or ".." in parts or (parts and ":" in parts[0]):
            raise UploadRejected("El ZIP contiene rutas inseguras (path traversal).")
        if parts and parts[0] == "__MACOSX":
            continue
        if stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF):
            raise UploadRejected(f"El ZIP contiene un enlace simbólico: '{safe_name(info.filename)}'.")
        if info.flag_bits & 0x1:
            raise UploadRejected(f"'{safe_name(info.filename)}' dentro del ZIP está cifrado con contraseña.")
        if not info.filename.lower().endswith(".pdf"):
            raise UploadRejected(f"El ZIP contiene un archivo que no es PDF: '{safe_name(info.filename)}'.")
        if info.file_size > limit:
            raise UploadRejected(f"'{safe_name(info.filename)}' dentro del ZIP excede el límite de {settings.MAX_UPLOAD_MB} MB.")
        if info.compress_size and info.file_size > 1024 * 1024 and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
            raise UploadRejected(f"Ratio de compresión sospechoso en '{safe_name(info.filename)}' (posible zip bomb).")
        try:
            content = zf.read(info)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, OSError, ValueError) as exc:
            # CRC inválido, miembro cifrado/truncado o compresión no soportada: se rechaza con mensaje, nunca un error 500
            raise UploadRejected(f"No se pudo leer '{safe_name(info.filename)}' del ZIP ({type(exc).__name__}).") from exc
        if not content.startswith(b"%PDF"):
            raise UploadRejected(f"'{safe_name(info.filename)}' dentro del ZIP no es un PDF válido.")
        out.append(UploadItem(safe_name(info.filename), content))
    return out


def store_private(data: bytes, dossier_id: int) -> str:
    rel = Path(str(dossier_id)) / f"{uuid.uuid4().hex}.pdf"
    target = settings.PRIVATE_STORAGE_ROOT / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return str(rel)


def read_private(doc: Document) -> bytes:
    root = settings.PRIVATE_STORAGE_ROOT.resolve()
    path = (root / doc.storage_path).resolve()
    if root not in path.parents:  # defensa adicional contra traversal
        raise PermissionError("Ruta fuera del almacenamiento privado")
    return path.read_bytes()


@transaction.atomic
def ingest_items(dossier, items: list[UploadItem]) -> IngestReport:
    """Persiste cada PDF: detecta duplicados exactos y archivos corruptos; extrae texto por página."""
    report = IngestReport()
    ocr = get_ocr()
    if ocr is not None and hasattr(ocr, "language_warning") and (warning := ocr.language_warning()):
        report.messages.append(f"OCR: {warning}")
    extractor = PyMuPDFExtractor(ocr=ocr)
    seen = set(Document.objects.filter(dossier=dossier).values_list("sha256", flat=True))
    for item in items:
        digest = hashlib.sha256(item.data).hexdigest()
        doc = Document(dossier=dossier, original_name=item.name, sha256=digest,
                       storage_path=store_private(item.data, dossier.id))
        if digest in seen:
            doc.status, doc.status_detail = DocStatus.DUPLICATE, "Mismo archivo ya cargado en el expediente"
            report.messages.append(f"{item.name}: duplicado exacto (no se analiza).")
            doc.save()
            report.created.append(doc)
            continue
        seen.add(digest)
        try:
            pages = extractor.extract_pages(item.data)
        except PDFCorruptError as exc:
            doc.status, doc.status_detail = DocStatus.CORRUPT, str(exc)
            report.messages.append(f"{item.name}: {exc}.")
            doc.save()
            report.created.append(doc)
            continue
        doc.page_count = len(pages)
        doc.save()
        DocumentPage.objects.bulk_create(DocumentPage(document=doc, number=p.page, text=p.text, method=p.method,
                                                      ocr_confidence=p.ocr_confidence, is_blank=p.blank) for p in pages)
        low = [p.page for p in pages if not p.blank and p.ocr_confidence < extractor.ocr_min_confidence]
        if low:
            report.messages.append(f"{item.name}: lectura de baja calidad (OCR) en las páginas {low}; se recomienda revisar el original.")
        report.created.append(doc)
    return report
