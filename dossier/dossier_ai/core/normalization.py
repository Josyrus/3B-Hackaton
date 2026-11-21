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
    """Minúsculas, sin acentos, espacios colapsados; une palabras cortadas con guion al final de línea."""
    text = re.sub(r"-[ \t]*\n[ \t]*(?=[a-záéíóúüñ])", "", text)
    return re.sub(r"\s+", " ", strip_accents(text).lower()).strip()


def compact_text(text: str) -> str:
    """Solo letras y dígitos, sin espacios: inmune a saltos de línea, signos y espaciado irregular (OCR/PDF)."""
    return re.sub(r"[^a-z0-9]", "", normalize_text(text))


def text_quality(text: str) -> float:
    """0..1. Detecta capas de texto corruptas (fuentes sin ToUnicode, basura de OCR embebido)."""
    t = text.strip()
    if not t:
        return 0.0
    good = sum(1 for c in t if c.isalnum() or c.isspace() or c in ".,;:-()/%$°#\"'ºª¿?¡!&@")
    ratio = good / len(t)
    words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}", t)
    if not words:
        return round(ratio * 0.5, 3)
    with_vowel = sum(1 for w in words if re.search(r"[aeiouáéíóúü]", w.lower()))
    return round(min(ratio, with_vowel / len(words)), 3)


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


def all_dates(text: str) -> list[date]:
    """Todas las fechas reconocibles en un texto (dd/mm/aaaa, aaaa-mm-dd, '12 de marzo de 2024'), sin duplicados."""
    t = normalize_text(text)
    found: list[tuple[int, date]] = []
    for pat in (r"\b\d{4}-\d{1,2}-\d{1,2}\b", r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{4}\b",
                r"\b\d{1,2}\s+de\s+[a-z]+\s+(?:de|del)\s+\d{4}\b"):
        for m in re.finditer(pat, t):
            if (d := parse_date(m[0])) is not None:
                found.append((m.start(), d))
    out: list[date] = []
    for _, d in sorted(found):
        if d not in out:
            out.append(d)
    return out


def numbers_in(text: str) -> list[float]:
    """Todos los números de un texto; ante la ambigüedad miles/decimales ('1.250' ó '1,250') devuelve ambas lecturas."""
    out: list[float] = []
    for m in re.finditer(r"\d[\d.,]*\d|\d", text or ""):
        tok = m[0]
        try:
            if "," in tok and "." in tok:
                out.append(float(tok.replace(".", "").replace(",", ".") if tok.rfind(",") > tok.rfind(".") else tok.replace(",", "")))
            elif "," in tok or "." in tok:
                sep = "," if "," in tok else "."
                parts = tok.split(sep)
                if len(parts) > 2 or len(parts[-1]) == 3:
                    out.append(float("".join(parts)))
                if len(parts) == 2:
                    out.append(float(parts[0] + "." + parts[1]))
            else:
                out.append(float(tok))
        except ValueError:
            continue
    return out


_WORD_NUM = {"un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "doce": 12,
             "treinta": 30, "sesenta": 60, "noventa": 90}


def parse_period(text: str) -> tuple[int, int, int] | None:
    """(años, meses, días) para plazos como 'un año', '6 meses', '90 días naturales'. None si no hay plazo o son días hábiles
    (no calculables sin calendario oficial)."""
    t = normalize_text(text)
    if "habil" in t:
        return None
    m = re.search(r"(\d+|" + "|".join(_WORD_NUM) + r")\s*(?:\(\s*\d+\s*\))?\s*(anos?|meses|mes|dias?)\b", t)
    if not m:
        return None
    n = int(m[1]) if m[1].isdigit() else _WORD_NUM[m[1]]
    unit = m[2]
    return (n, 0, 0) if unit.startswith("ano") else (0, n, 0) if unit.startswith("mes") else (0, 0, n)


def add_period(d: date, years: int, months: int, days: int) -> date:
    import calendar
    from datetime import timedelta
    total = d.month - 1 + years * 12 + months
    y, mo = d.year + total // 12, total % 12 + 1
    return date(y, mo, min(d.day, calendar.monthrange(y, mo)[1])) + timedelta(days=days)


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
