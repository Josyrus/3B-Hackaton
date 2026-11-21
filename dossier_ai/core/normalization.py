"""Normalización de texto, direcciones, nombres, fechas y superficies."""
from __future__ import annotations

import re
import unicodedata
from datetime import date

ADDRESS_ABBR = {
    "av": "avenida", "avda": "avenida", "col": "colonia", "calz": "calzada", "no": "numero",
    "num": "numero", "mz": "manzana", "lt": "lote", "blvd": "boulevard", "cd": "ciudad",
    "mex": "mexico", "cdmx": "ciudad de mexico", "dr": "doctor", "gral": "general",
    "prol": "prolongacion", "int": "interior", "ext": "exterior", "cp": "codigo postal", "c": "calle",
}
STOPWORDS = {"de", "del", "la", "el", "los", "las", "y"}
MONTHS = {m: i for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
     "septiembre", "octubre", "noviembre", "diciembre"], 1)}
MONTHS["setiembre"] = 9


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def normalize_text(text: str) -> str:
    """Minúsculas, sin acentos, espacios colapsados."""
    return re.sub(r"\s+", " ", strip_accents(text).lower()).strip()


def _tokens(text: str) -> list[str]:
    cleaned = re.sub(r"[^\w\s]", " ", normalize_text(text))
    return [t for t in cleaned.split() if t]


def normalize_address(text: str) -> str:
    out: list[str] = []
    for tok in _tokens(text):
        out.extend(ADDRESS_ABBR.get(tok, tok).split())
    return " ".join(t for t in out if t not in STOPWORDS and t != "numero")


def normalize_name(text: str) -> str:
    return " ".join(sorted(t for t in _tokens(text) if t not in STOPWORDS))


def normalize_identifier(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize_text(text))


def parse_date(text: str) -> date | None:
    """Acepta dd/mm/aaaa, aaaa-mm-dd y '12 de marzo de 2024'. None si no es una fecha."""
    t = normalize_text(text)
    if m := re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t):
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))
    if m := re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", t):
        return _safe_date(int(m[3]), int(m[2]), int(m[1]))
    if m := re.search(r"\b(\d{1,2})\s+de\s+([a-z]+)\s+(?:de|del)\s+(\d{4})\b", t):
        if m[2] in MONTHS:
            return _safe_date(int(m[3]), MONTHS[m[2]], int(m[1]))
    return None


def _safe_date(y: int, mo: int, d: int) -> date | None:
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def normalize_date(text: str) -> str:
    d = parse_date(text)
    return d.isoformat() if d else normalize_text(text)


_AREA = re.compile(r"(\d[\d,\s]*(?:\.\d+)?)\s*(m2|m²|mts2|metros cuadrados|mt2|ha|hectareas?|km2)?", re.I)


def parse_area_m2(text: str) -> float | None:
    t = normalize_text(text).replace("²", "2")
    m = _AREA.search(t)
    if not m:
        return None
    try:
        value = float(re.sub(r"[,\s]", "", m[1]))
    except ValueError:
        return None
    unit = (m[2] or "m2").lower()
    if unit.startswith("ha") or unit.startswith("hectarea"):
        value *= 10_000
    elif unit == "km2":
        value *= 1_000_000
    return round(value, 2)


def normalize_area(text: str) -> str:
    v = parse_area_m2(text)
    return f"{v:.2f} m2" if v is not None else normalize_text(text)
