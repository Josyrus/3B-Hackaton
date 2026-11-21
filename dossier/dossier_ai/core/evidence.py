"""Verificación independiente de citas contra el texto original (tolerante a OCR solo en páginas OCR)."""
from __future__ import annotations

from difflib import SequenceMatcher

from .contracts import DocumentInput, Evidence, PageText, Verification
from .normalization import all_dates, compact_text, normalize_text, numbers_in, parse_area_m2, parse_date

OCR_MIN_COVERAGE = 0.85      # fracción de la cita que debe hallarse (aprox.) en una página OCR
MIN_FUZZY_LEN = 8            # citas muy cortas solo se aceptan de forma exacta
VALUE_TOKEN_MIN = 0.30       # fracción mínima de palabras del valor presentes en la cita


def quote_in_page(quote: str, page_text: str) -> bool:
    """Coincidencia estricta (insensible a mayúsculas, acentos, espacios, saltos de línea, signos y guiones de corte)."""
    q = normalize_text(quote)
    if not q:
        return False
    if q in normalize_text(page_text):
        return True
    cq = compact_text(quote)
    return len(cq) >= 4 and cq in compact_text(page_text)


def quote_coverage(quote: str, page_text: str) -> float:
    """Fracción (0-1) de la cita que aparece de forma contigua y aproximada en la página (para ruido de OCR)."""
    f, p = compact_text(quote)[:700], compact_text(page_text)
    if not f or not p:
        return 0.0
    if f in p:
        return 1.0
    n = len(f)
    window, step = int(n * 1.35) + 8, max(1, n // 3)
    best = 0.0
    for start in range(0, max(1, len(p) - n // 2), step):
        w = p[start:start + window]
        if not w:
            break
        sm = SequenceMatcher(None, f, w, autojunk=False)
        best = max(best, sum(b.size for b in sm.get_matching_blocks() if b.size >= 3) / n)
        if best >= 0.995:
            break
    return min(best, 1.0)


def value_supported(raw: str, quote: str, kind: str = "text") -> bool | None:
    """¿La cita realmente sustenta el valor? True/False; None si no es comprobable (la cita no trae el tipo de dato)."""
    if kind == "area":
        target = parse_area_m2(raw)
        nums = numbers_in(quote)
        if target is None or not nums:
            return None
        return any(abs(c - target) <= max(0.01, abs(target) * 0.005) for n in nums for c in (n, n * 10_000.0))
    if kind == "date":
        target = parse_date(raw)
        found = all_dates(quote)
        if target is None or not found:
            return None
        return target in found
    tokens = [t for t in normalize_text(raw).replace("-", " ").split() if len(t) >= 3 or t.isdigit()]
    if not tokens:
        return None
    q = normalize_text(quote).replace("-", " ").split()
    hits = sum(1 for t in tokens if any(t == o or SequenceMatcher(None, t, o).ratio() >= 0.85 for o in q))
    return hits / len(tokens) >= VALUE_TOKEN_MIN


def _locate(ev: Evidence, page: PageText) -> tuple[bool, bool, str]:
    """(encontrada, exacta, detalle)."""
    if quote_in_page(ev.quote, page.text):
        return True, True, "Coincidencia literal verificada."
    if page.method == "ocr" and len(compact_text(ev.quote)) >= MIN_FUZZY_LEN:
        cov = quote_coverage(ev.quote, page.text)
        if cov >= OCR_MIN_COVERAGE:
            return True, False, f"Coincidencia aproximada tolerante a OCR ({cov:.0%})."
        return False, False, f"La cita no aparece en la página (mejor coincidencia OCR {cov:.0%})."
    return False, False, "La cita no aparece en la página indicada."


def verify_evidence(ev: Evidence, documents: dict[int, DocumentInput], value: str | None = None, kind: str = "text") -> Evidence:
    """Devuelve una copia con el estado de verificación. La cita debe existir en la página indicada y, si se
    entrega `value`, debe sustentarlo. Las correcciones manuales no se re-verifican."""
    if ev.verification == Verification.MANUAL:
        return ev
    doc = documents.get(ev.document_id or -1)
    page = next((p for p in doc.pages if p.page == ev.page), None) if doc else None
    if page is None:
        return ev.model_copy(update={"verification": Verification.UNVERIFIED, "detail": "La página citada no existe en el documento."})
    found, exact, detail = _locate(ev, page)
    if found and value is not None:
        supported = value_supported(value, ev.quote, kind)
        if supported is False:
            found, detail = False, "El valor extraído no está respaldado por la cita."
    return ev.model_copy(update={
        "verification": Verification.VERIFIED if found else Verification.UNVERIFIED,
        "ocr_confidence": page.ocr_confidence if page.method == "ocr" else None,
        "exact_match": exact if found else False, "detail": detail})
