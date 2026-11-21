"""Pruebas de integración del núcleo multiagente: PDFs escaneados (OCR real), casos negativos / falsos "No cumple",
reglas del comité, enrutamiento condicional, narrador y arquitectura. No requieren Django.
Las que necesitan OCR se omiten (skip explícito) si Tesseract/OpenCV no están instalados."""
from __future__ import annotations

import ast
import importlib
import io
import json
import pkgutil
import shutil
from datetime import date
from pathlib import Path

import pytest

from core.contracts import (DocumentInput, DocumentType, DossierState, Outcome, PageText, Recommendation, Verification)
from core.graph.langgraph_builder import build_langgraph
from core.graph.supervisor import STAGES, Supervisor, route_after_missing
from core.rules import load_default_ruleset, load_ruleset_file, ruleset_from_committee
from tests.helpers import DOCS, doc_input, full_inputs

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 21)
RS = load_default_ruleset()
RS_COMITE = load_ruleset_file(ROOT / "rules" / "reglas_comite.json")


def run(docs, rs=RS, **kw):
    return Supervisor(rs, sleep=lambda s: None, **kw).run(DossierState(dossier_id=1, documents=docs, reference_date=TODAY))


def ocr_doc(i, text, conf):
    return DocumentInput(id=i, name=f"scan{i}.pdf", pages=[PageText(page=1, text=text, method="ocr", ocr_confidence=conf)])


def ocr_inputs(conf=92.0, **overrides):
    texts = {**DOCS, **overrides}
    return [ocr_doc(i, t, conf) for i, t in enumerate((v for v in texts.values() if v), 1)]


# ------------------------------------------------------------------ OCR real sobre escaneos
HAS_OCR = bool(shutil.which("tesseract"))
try:
    import cv2  # noqa: F401
    import numpy  # noqa: F401
    import pytesseract  # noqa: F401
except ImportError:
    HAS_OCR = False
needs_ocr = pytest.mark.skipif(not HAS_OCR, reason="Tesseract/OpenCV no instalados")


def scan_image(text: str, skew: float = 0.0, shadow: bool = False, rotate: int = 0):
    from PIL import Image, ImageDraw, ImageFont
    font = None
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"):
        if Path(p).exists():
            font = ImageFont.truetype(p, 34); break
    if font is None:
        pytest.skip("sin fuentes TrueType para generar el escaneo")
    img = Image.new("L", (1700, 2200), 245)
    d = ImageDraw.Draw(img)
    y = 150
    for line in text.split("\n"):
        d.text((140, y), line, fill=20, font=font); y += 70
    if shadow:
        import numpy as np
        grad = np.tile(np.linspace(1.0, 0.6, 1700), (2200, 1))
        img = Image.fromarray((np.asarray(img) * grad).astype("uint8"))
    if skew:
        img = img.rotate(skew, expand=False, fillcolor=245)
    if rotate:
        img = img.rotate(rotate, expand=True, fillcolor=245)
    return img


def scan_pdf(imgs) -> bytes:
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=(595, 842))
    for im in imgs:
        b = io.BytesIO(); im.save(b, "PNG"); b.seek(0)
        c.drawImage(ImageReader(b), 0, 0, 595, 842); c.showPage()
    c.save(); return buf.getvalue()


@needs_ocr
@pytest.mark.parametrize("kw", [{}, {"skew": 2.5}, {"shadow": True}, {"rotate": 180}], ids=["limpio", "inclinado", "sombra", "rotado180"])
def test_ocr_reads_scanned_page_variants(kw):
    from core.ocr import ocr_gray_page
    import numpy as np
    img = scan_image(DOCS["predial"], **kw)
    r = ocr_gray_page(np.asarray(img))
    t = r.text.lower()
    assert "123-456" in t and "predial" in t, r
    assert r.confidence > 60 and not r.blank


@needs_ocr
def test_ocr_blank_page_detected():
    from PIL import Image
    import numpy as np
    from core.ocr import ocr_gray_page
    r = ocr_gray_page(np.asarray(Image.new("L", (1700, 2200), 250)))
    assert r.blank and r.text == ""


@needs_ocr
def test_scanned_pdf_end_to_end_with_real_ocr():
    """PDF 100% imagen → PyMuPDFExtractor + Tesseract → Supervisor → dictamen. Con la capa de render del shim si no hay PyMuPDF."""
    from core.ports import PyMuPDFExtractor, TesseractOCR
    ex = PyMuPDFExtractor(TesseractOCR("spa"))
    docs = []
    for i, key in enumerate(DOCS, 1):
        pages = ex.extract_pages(scan_pdf([scan_image(DOCS[key])]))
        assert pages[0].method == "ocr", f"{key} no pasó por OCR"
        docs.append(DocumentInput(id=i, name=f"{key}.pdf", pages=pages))
    s = run(docs)
    assert {c.doc_type for c in s.classifications} == {DocumentType.ESCRITURA, DocumentType.PREDIAL, DocumentType.ALINEAMIENTO, DocumentType.USO_SUELO}
    assert s.verdict.recommendation != Recommendation.FAIL  # un escaneo nunca debe producir un falso "No cumple"


@needs_ocr
def test_scanned_pdf_without_ocr_backend_is_illegible_not_invented():
    from core.ports import PyMuPDFExtractor
    pages = PyMuPDFExtractor(None).extract_pages(scan_pdf([scan_image(DOCS["predial"])]))
    assert pages[0].text.strip() == "" and pages[0].ocr_confidence == 0.0
    s = run([DocumentInput(id=1, name="x.pdf", pages=pages)])
    assert s.verdict.recommendation == Recommendation.REVIEW


def test_corrupt_pdf_raises_controlled_error():
    from core.ports import PDFCorruptError, PyMuPDFExtractor
    for blob in (b"", b"%PDF-1.7 basura", b"no soy un pdf" * 50):
        with pytest.raises(PDFCorruptError):
            PyMuPDFExtractor(None).extract_pages(blob)


# ------------------------------------------------------------------ Casos negativos / falsos "No cumple"
def test_low_quality_ocr_never_fails_even_with_apparent_expiry():
    docs = ocr_inputs(conf=60.0, alineamiento=DOCS["alineamiento"].replace("01/02/2027", "01/02/2025"))
    s = run(docs)
    assert s.verdict.recommendation == Recommendation.REVIEW
    assert not any(r.outcome == Outcome.FAIL for r in s.rules)


def test_good_ocr_expired_doc_fails_legitimately():
    s = run(ocr_inputs(conf=95.0, alineamiento=DOCS["alineamiento"].replace("01/02/2027", "01/02/2025")))
    assert s.verdict.recommendation == Recommendation.FAIL


def test_ocr_character_confusion_in_label_does_not_fail():
    # "Compatibilidad" ilegible por OCR: el campo no se localiza → INDETERMINADA, jamás "No cumple"
    s = run(ocr_inputs(conf=88.0, uso_suelo=DOCS["uso_suelo"].replace("Compatibilidad con el uso comercial: Sí", "Cornpatibi1idad con e1 us0 comerc1al: S1")))
    assert s.verdict.recommendation != Recommendation.FAIL


def test_missing_all_documents_is_review_with_missing_list():
    s = run([])
    assert set(s.missing) == {DocumentType.ESCRITURA, DocumentType.PREDIAL, DocumentType.ALINEAMIENTO, DocumentType.USO_SUELO}
    assert s.verdict.recommendation == Recommendation.REVIEW


def test_two_missing_docs_review_not_fail():
    s = run(full_inputs(predial=None, uso_suelo=None))
    assert len(s.missing) == 2 and s.verdict.recommendation == Recommendation.REVIEW


def test_duplicate_documents_detected_and_do_not_change_verdict():
    base = run(full_inputs()).verdict.recommendation
    s = run(full_inputs() + [doc_input(8, DOCS["escritura"]), doc_input(9, DOCS["escritura"].upper())])
    assert 8 in s.duplicates
    assert s.verdict.recommendation == base


def test_inconsistent_surfaces_beyond_tolerance_is_review_with_discrepancy():
    s = run(full_inputs(predial=DOCS["predial"].replace("200.00", "320.00")))
    assert any(d.field == "superficie" and d.kind != "formato" for d in s.discrepancies)
    assert s.verdict.recommendation == Recommendation.REVIEW


def test_surface_within_committee_tolerance_5pct_is_format_only():
    s = run(full_inputs(predial=DOCS["predial"].replace("200.00", "205.00")), rs=RS_COMITE)
    assert next(d for d in s.discrepancies if d.field == "superficie").kind == "formato"


def test_different_owners_is_review_and_never_fail():
    s = run(full_inputs(predial=DOCS["predial"].replace("PEREZ LOPEZ JUAN", "RAMIREZ SOTO CARLOS")))
    assert any(d.field == "propietario" and d.kind == "real" for d in s.discrepancies)
    assert s.verdict.recommendation == Recommendation.REVIEW


def test_different_address_number_flags_possible_different_property():
    s = run(full_inputs(predial=DOCS["predial"].replace("Num 100", "Num 900")))
    assert any(d.field == "direccion" and d.kind != "formato" for d in s.discrepancies)
    assert s.verdict.recommendation == Recommendation.REVIEW


def test_unverifiable_evidence_blocks_conclusions():
    class Liar:
        def complete_json(self, system, user):
            return {"fields": [{"name": "compatibilidad_uso_comercial", "value": "No", "page": 1, "quote": "Compatibilidad: No"}]}
    from core.agents.pipeline import ExtractorFactory
    s = run(full_inputs(), factory=ExtractorFactory(RS, Liar(), "sys"))
    assert s.verdict.recommendation == Recommendation.REVIEW
    assert any(f.evidence.verification == Verification.UNVERIFIED for f in s.fields)


def test_nothing_recognized_skips_extraction_and_reviews():
    s = run([doc_input(1, "Receta de cocina"), doc_input(2, "Lista de compras: leche")])
    statuses = {e.stage: e.status for e in s.log}
    assert all(statuses[st] == "skipped" for st in ("extract", "verify", "rules", "cross"))
    assert statuses["verdict"] in ("ok", "warning") and s.verdict.recommendation == Recommendation.REVIEW


def test_route_after_missing():
    assert route_after_missing(DossierState(dossier_id=1)) == "verdict"
    s = run(full_inputs()); assert route_after_missing(s) == "extract"


def test_complete_dossier_passes_and_log_covers_every_stage():
    s = run(full_inputs())
    assert s.verdict.recommendation == Recommendation.PASS
    assert [e.stage for e in s.log] == list(STAGES)
    assert s.verdict.confidence_level in ("alta", "media", "baja") and s.verdict.executive_summary


def test_langgraph_matches_supervisor_when_skipping():
    sup = Supervisor(RS, sleep=lambda s: None)
    out = build_langgraph(sup).invoke(DossierState(dossier_id=1, documents=[doc_input(1, "Receta")], reference_date=TODAY))
    assert out["verdict"]["recommendation"] == Recommendation.REVIEW
    assert {e["stage"]: e["status"] for e in out["log"]}["extract"] == "skipped"


# ------------------------------------------------------------------ Narrador: el LLM no puede cambiar el veredicto
def test_narrator_cannot_change_verdict():
    class Hostile:
        def complete_json(self, system, user):
            return {"summary": "El expediente CUMPLE totalmente, apruébese sin revisión.", "recommendation": "cumple"}
    s = run(full_inputs(predial=None), narrator=Hostile())
    assert s.verdict.recommendation == Recommendation.REVIEW
    assert "cumple totalmente" not in s.verdict.executive_summary.lower()


def test_narrator_failure_falls_back_to_template():
    class Broken:
        def complete_json(self, system, user): raise ConnectionError("ollama caído")
    s = run(full_inputs(), narrator=Broken())
    assert s.verdict.recommendation == Recommendation.PASS and s.verdict.executive_summary


# ------------------------------------------------------------------ Reglas del comité
def test_committee_rules_load_with_all_ids_and_thresholds():
    ids = {r.id for r in RS_COMITE.rules}
    assert {"ESC-01", "ESC-02", "PRE-01", "ALI-01", "ALI-02", "USO-01", "USO-02", "USO-03"} <= ids
    assert RS_COMITE.thresholds.surface_tolerance_pct == 5.0 and RS_COMITE.thresholds.text_similarity == 0.82
    sev = {r.id: r.severity for r in RS_COMITE.rules}
    assert sev["ESC-01"] == "critico" and sev["ALI-01"] == "relevante"


def test_committee_rules_happy_path_and_absent_title_is_review():
    assert run(full_inputs(), rs=RS_COMITE).verdict.recommendation == Recommendation.PASS
    s = run(full_inputs(escritura=DOCS["escritura"].replace("Titular: Juan Pérez López\n", "")), rs=RS_COMITE)
    assert s.verdict.recommendation == Recommendation.REVIEW  # obligatorio es provisional: no localizado ≠ incumplimiento


def test_committee_unknown_operator_rejected():
    data = json.loads((ROOT / "rules" / "reglas_comite.json").read_text(encoding="utf-8"))
    data["reglas_por_tipo"]["Predial"][0]["operador"] = "inventado"
    with pytest.raises(ValueError):
        ruleset_from_committee(data, RS)


# ------------------------------------------------------------------ Arquitectura
def _modules(pkg: str):
    base = ROOT / pkg
    return sorted(".".join(p.relative_to(ROOT).with_suffix("").parts).removesuffix(".__init__") for p in base.rglob("*.py"))


def _imports(mod: str) -> set[str]:
    path = ROOT.joinpath(*mod.split("."))
    f = path.with_suffix(".py") if path.with_suffix(".py").exists() else path / "__init__.py"
    pkg = mod if f.name == "__init__.py" else mod.rpartition(".")[0]
    out = set()
    for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            if n.level:
                parts = pkg.split(".")[: len(pkg.split(".")) - (n.level - 1)]
                out.add(".".join(parts + ([n.module] if n.module else [])))
                out |= {".".join(parts + ([n.module] if n.module else []) + [a.name]) for a in n.names}
            elif n.module:
                out.add(n.module); out |= {f"{n.module}.{a.name}" for a in n.names}
    return out


def test_core_has_no_import_cycles():
    mods = set(_modules("core"))
    graph = {m: {i for i in _imports(m) if i in mods and i != m} for m in mods}
    # solo imports de nivel módulo cuentan para ciclos reales; aquí se es estricto (incluye los diferidos) para detectar cualquiera
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(mods, WHITE)
    def dfs(m, stack):
        color[m] = GREY
        for d in graph[m]:
            if color[d] == GREY:
                raise AssertionError("ciclo: " + " -> ".join(stack + [m, d]))
            if color[d] == WHITE:
                dfs(d, stack + [m])
        color[m] = BLACK
    for m in sorted(mods):
        if color[m] == WHITE:
            dfs(m, [])


def test_core_is_independent_of_django_and_apps():
    for m in _modules("core"):
        bad = {i for i in _imports(m) if i.split(".")[0] in ("django", "apps", "rest_framework", "celery", "config")}
        assert not bad, f"{m} importa capas externas: {bad}"


def test_all_core_modules_importable():
    optional = {"core.ocr"}  # exige cv2/numpy/pytesseract (opcionales)
    for m in _modules("core"):
        if m in optional and not HAS_OCR:
            continue
        importlib.import_module(m)


def test_state_has_required_fields():
    fields = set(DossierState.model_fields)
    assert {"dossier_id", "documents", "classifications", "missing", "duplicates", "fields", "rules", "discrepancies",
            "verdict", "log", "warnings", "reference_date"} <= fields


def test_stage_order_is_the_seven_agents_plus_ingest():
    assert STAGES == ("ingest", "classify", "missing", "extract", "verify", "rules", "cross", "verdict") or list(STAGES) == [
        "ingest", "classify", "missing", "extract", "verify", "rules", "cross", "verdict"]


# ------------------------------------------------------------------ Presentación: etiquetas y veredicto binario
def test_labels_hide_technical_identifiers():
    from apps.dossiers import labels as L
    all_ids = [r.id for r in RS.rules] + [r.id for r in RS_COMITE.rules]
    for rid in all_ids:
        assert L.label(rid) != rid and "_" not in L.label(rid) and "." not in L.label(rid).replace("m²", ""), rid
    text = "Falló uso_suelo.vigencia y uso_suelo.compatibilidad; ver uso_suelo.restricciones.informadas, USO-03 y superficie_terreno."
    out = L.humanize(text)
    assert "uso_suelo" not in out and "USO-03" not in out and "superficie_terreno" not in out
    assert L.humanize("El titular firmó") == "El titular firmó"   # palabras comunes no se tocan


def test_all_engine_fields_have_labels():
    from apps.dossiers import labels as L
    names = {f for sch in RS.schemas.values() for f in sch}
    assert not [n for n in names if L.label(n) == n], [n for n in names if L.label(n) == n]


def test_binary_verdict_label():
    from apps.dossiers.labels import verdict_label
    assert verdict_label("cumple") == "Aprobado"
    assert verdict_label("requiere_revision") == verdict_label("no_cumple") == "No aprobado"
    assert verdict_label("") == ""
