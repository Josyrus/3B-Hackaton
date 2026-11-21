"""Verificación independiente de citas contra el texto original."""
from __future__ import annotations

from .contracts import DocumentInput, Evidence, Verification
from .normalization import normalize_text


def quote_in_page(quote: str, page_text: str) -> bool:
    q = normalize_text(quote)
    return bool(q) and q in normalize_text(page_text)


def verify_evidence(ev: Evidence, documents: dict[int, DocumentInput]) -> Evidence:
    """Devuelve una copia con el estado de verificación. La cita debe existir en la página indicada."""
    if ev.verification == Verification.MANUAL:
        return ev
    doc = documents.get(ev.document_id or -1)
    page = next((p for p in doc.pages if p.page == ev.page), None) if doc else None
    ok = page is not None and quote_in_page(ev.quote, page.text)
    return ev.model_copy(update={"verification": Verification.VERIFIED if ok else Verification.UNVERIFIED})
