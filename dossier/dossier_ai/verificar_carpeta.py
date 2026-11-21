#!/usr/bin/env python3
"""Verifica los PDF/ZIP que estén en la MISMA carpeta que este script (o en la carpeta indicada) con el núcleo multiagente.

Uso:
    python verificar_carpeta.py                    # analiza ./*.pdf y ./*.zip junto al script
    python verificar_carpeta.py RUTA --uso comercial --ocr tesseract --llm ollama --json salida.json

No requiere Django ni base de datos. Los PDF escaneados pasan por OCR (Tesseract + OpenCV) si está instalado (--ocr auto).
Código de salida: 0 = cumple, 1 = requiere revisión, 2 = no cumple, 3 = error de ejecución / sin documentos.
Los ZIP se abren con las mismas defensas que la aplicación (zip-slip, symlinks, cifrado, bombas, límites).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.contracts import DocumentInput, DossierState  # noqa: E402
from core.graph.supervisor import Supervisor  # noqa: E402
from core.ports import OllamaLLM, PDFCorruptError, PyMuPDFExtractor, TesseractOCR  # noqa: E402
from core.rules import load_default_ruleset, load_ruleset_file  # noqa: E402

MAX_ZIP_MEMBERS, MAX_MEMBER_BYTES, MAX_TOTAL_BYTES, MAX_RATIO = 200, 50 * 2**20, 300 * 2**20, 200


def safe_zip_members(data: bytes, label: str, notes: list[str]) -> list[tuple[str, bytes]]:
    """Extrae PDFs de un ZIP en memoria rechazando entradas peligrosas; cada rechazo se informa (nunca en silencio)."""
    out: list[tuple[str, bytes]] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        notes.append(f"{label}: ZIP corrupto, omitido")
        return out
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_MEMBERS:
            notes.append(f"{label}: demasiadas entradas ({len(infos)}), ZIP rechazado")
            return out
        total = 0
        for zi in infos:
            n = zi.filename
            if zi.is_dir():
                continue
            parts = Path(n.replace("\\", "/")).parts
            if n.startswith(("/", "\\")) or ".." in parts or (len(n) > 1 and n[1] == ":"):
                notes.append(f"{label}: ruta peligrosa '{n}' rechazada"); continue
            if (zi.external_attr >> 16) & 0o170000 == 0o120000:
                notes.append(f"{label}: enlace simbólico '{n}' rechazado"); continue
            if zi.flag_bits & 0x1:
                notes.append(f"{label}: entrada cifrada '{n}' rechazada"); continue
            if not n.lower().endswith(".pdf"):
                notes.append(f"{label}: '{n}' ignorado (no es PDF)"); continue
            if zi.file_size > MAX_MEMBER_BYTES or (zi.compress_size and zi.file_size / zi.compress_size > MAX_RATIO):
                notes.append(f"{label}: '{n}' excede tamaño/ratio permitido (posible zip bomb)"); continue
            total += zi.file_size
            if total > MAX_TOTAL_BYTES:
                notes.append(f"{label}: tamaño total excedido, se detiene la extracción"); break
            try:
                blob = zf.read(zi)
            except (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError) as exc:
                notes.append(f"{label}: no se pudo leer '{n}' ({type(exc).__name__})"); continue
            if len(blob) > MAX_MEMBER_BYTES:
                notes.append(f"{label}: '{n}' excede el tamaño real permitido"); continue
            out.append((f"{label}/{Path(n).name}", blob))
    return out


def collect(folder: Path, notes: list[str]) -> list[tuple[str, bytes]]:
    items: list[tuple[str, bytes]] = []
    for f in sorted(folder.iterdir()):
        if not f.is_file() or f.is_symlink():
            continue
        low = f.suffix.lower()
        if low == ".pdf":
            items.append((f.name, f.read_bytes()))
        elif low == ".zip":
            items.extend(safe_zip_members(f.read_bytes(), f.name, notes))
    return items


def build_ocr(mode: str, lang: str, notes: list[str]):
    if mode == "none":
        return None
    try:
        ocr = TesseractOCR(lang)
        if not shutil.which("tesseract"):
            raise RuntimeError("binario 'tesseract' no encontrado")
        import core.ocr  # noqa: F401  (valida cv2/numpy/pytesseract)
        warn = ocr.language_warning()
        if warn:
            notes.append(f"OCR: {warn}")
        return ocr
    except Exception as exc:  # noqa: BLE001
        if mode == "tesseract":
            raise SystemExit(f"OCR solicitado pero no disponible: {exc}")
        notes.append(f"OCR no disponible ({exc}); los PDF escaneados quedarán ilegibles y el dictamen exigirá revisión")
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("carpeta", nargs="?", default=str(Path(__file__).resolve().parent))
    ap.add_argument("--ocr", choices=["auto", "tesseract", "none"], default="auto")
    ap.add_argument("--ocr-lang", default=os.environ.get("OCR_LANG", "spa"))
    ap.add_argument("--llm", choices=["none", "ollama"], default="none", help="narrador/extractor LLM opcional (no altera el veredicto determinista)")
    ap.add_argument("--model", default=os.environ.get("LLM_MODEL", "qwen2.5:7b"))
    ap.add_argument("--ollama-url", default=os.environ.get("LLM_BASE_URL", "http://localhost:11434"))
    ap.add_argument("--reglas", default=None, help="YAML o JSON del comité (por defecto rules/ruleset.yaml)")
    ap.add_argument("--fecha", default=None, help="fecha de referencia AAAA-MM-DD (por defecto hoy)")
    ap.add_argument("--json", default=None, help="guarda el reporte completo en este archivo")
    a = ap.parse_args()

    folder = Path(a.carpeta).resolve()
    notes: list[str] = []
    items = collect(folder, notes)
    if not items:
        print(f"No se encontraron PDF/ZIP en {folder}")
        for n in notes: print("  !", n)
        return 3

    ocr = build_ocr(a.ocr, a.ocr_lang, notes)
    extractor = PyMuPDFExtractor(ocr)
    docs: list[DocumentInput] = []
    seen: dict[str, str] = {}
    for name, blob in items:
        h = hashlib.sha256(blob).hexdigest()
        if h in seen:
            notes.append(f"{name}: idéntico byte a byte a {seen[h]} (duplicado, omitido)"); continue
        seen[h] = name
        try:
            pages = extractor.extract_pages(blob)
        except PDFCorruptError as exc:
            notes.append(f"{name}: PDF no procesable ({exc})"); continue
        docs.append(DocumentInput(id=len(docs) + 1, name=name, pages=pages))

    llm = OllamaLLM(a.model, a.ollama_url) if a.llm == "ollama" else None
    rs = load_ruleset_file(a.reglas) if a.reglas else load_default_ruleset()
    ref = date.fromisoformat(a.fecha) if a.fecha else date.today()
    state = Supervisor(rs, narrator=llm).run(DossierState(dossier_id=0, documents=docs, reference_date=ref, warnings=list(notes)))

    v = state.verdict
    print(f"\n=== {len(docs)} documento(s) analizados en {folder} ===")
    for d in docs:
        c = next((c for c in state.classifications if c.document_id == d.id), None)
        q = min((p.ocr_confidence for p in d.pages), default=0)
        print(f"  [{d.id}] {d.name:40s} → {c.doc_type.value if c else '?':14s} conf={c.confidence if c else 0:.2f} "
              f"{'REVISAR ' if c and c.needs_review else ''}método={'/'.join(sorted({p.method for p in d.pages}))} calidad_OCR_min={q:.0f}")
    if state.missing: print("Faltantes:", ", ".join(m.value for m in state.missing))
    if state.duplicates: print("Duplicados por contenido:", state.duplicates)
    for r in state.rules:
        print(f"  regla {r.rule_id:34s} {r.outcome.value:14s} {r.message}")
    for x in state.discrepancies:
        print(f"  discrepancia {x.field}: {x.kind}{' (posible inmueble distinto)' if x.possible_different_property else ''} — "
              + "; ".join(f"{val.get('doc_type')}={val.get('raw')}" for val in x.values))
    for w in state.warnings: print("  ! aviso:", w)
    print(f"\nDICTAMEN: {v.recommendation.value.upper()} (confianza {v.confidence_level}, {v.confidence:.2f}) "
          f"{'— requiere revisión humana' if v.requires_human_review else ''}")
    print(v.executive_summary)
    for j in v.justification: print("  -", j)
    if a.json:
        Path(a.json).write_text(json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        print("Reporte JSON:", a.json)
    return {"cumple": 0, "requiere_revision": 1, "no_cumple": 2}.get(v.recommendation.value, 1)


if __name__ == "__main__":
    sys.exit(main())
