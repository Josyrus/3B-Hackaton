from datetime import date

import pytest

from core import normalization as nz
from core.agents.pipeline import CrossValidationAgent, LLMExtractor, ExtractorFactory
from core.contracts import *
from core.evidence import verify_evidence
from core.graph.langgraph_builder import build_langgraph
from core.graph.supervisor import Supervisor
from core.rules import RuleSetError, load_default_ruleset, parse_ruleset
from tests.helpers import DOCS, doc_input, full_inputs

RS = load_default_ruleset()
TODAY = date(2026, 11, 21)


def run(docs, **kw):
    return Supervisor(RS, sleep=lambda s: None, **kw).run(DossierState(dossier_id=1, documents=docs, reference_date=TODAY))


# ---- normalización
def test_address_abbreviations_and_accents():
    assert nz.normalize_address("Av. Reforma No. 100, Col. Centro") == nz.normalize_address("AVENIDA REFORMA Núm 100 Colonia Centro")

def test_name_order_and_case():
    assert nz.normalize_name("Pérez López, Juan") == nz.normalize_name("JUAN PEREZ LOPEZ")

@pytest.mark.parametrize("raw,expected", [("200 m2", 200.0), ("200.00 m²", 200.0), ("1,250.5 metros cuadrados", 1250.5), ("0.5 ha", 5000.0)])
def test_area_units(raw, expected):
    assert nz.parse_area_m2(raw) == expected

@pytest.mark.parametrize("raw", ["12 de marzo de 2024", "12/03/2024", "2024-03-12"])
def test_dates(raw):
    assert nz.parse_date(raw) == date(2024, 3, 12)

def test_invalid_date_none():
    assert nz.parse_date("31/02/2024") is None


# ---- evidencia
def test_evidence_verified_and_fabricated():
    d = {1: doc_input(1, "Titular: Juan Pérez")}
    ok = verify_evidence(Evidence(document_id=1, page=1, quote="titular:  JUAN PEREZ"), d)
    bad = verify_evidence(Evidence(document_id=1, page=1, quote="Titular: Pedro"), d)
    wrong_page = verify_evidence(Evidence(document_id=1, page=2, quote="Titular: Juan Pérez"), d)
    assert ok.verification == Verification.VERIFIED
    assert bad.verification == Verification.UNVERIFIED and wrong_page.verification == Verification.UNVERIFIED


# ---- pipeline completo
def test_happy_path_cumple_with_format_differences_only():
    s = run(full_inputs())
    assert s.verdict.recommendation == Recommendation.PASS
    assert {d.kind for d in s.discrepancies} == {"formato"}
    assert all(f.evidence.verification == Verification.VERIFIED for f in s.fields if f.found)

def test_missing_document_requires_review():
    s = run(full_inputs(predial=None))
    assert DocumentType.PREDIAL in s.missing
    assert s.verdict.recommendation == Recommendation.REVIEW

def test_owner_discrepancy_is_review_not_fail():
    s = run(full_inputs(predial=DOCS["predial"].replace("PEREZ LOPEZ JUAN", "GARCIA RUIZ MARIA")))
    assert any(d.field == "propietario" and d.kind == "real" for d in s.discrepancies)
    assert s.verdict.recommendation == Recommendation.REVIEW

def test_surface_beyond_tolerance_is_real_discrepancy_and_review():
    s = run(full_inputs(predial=DOCS["predial"].replace("200.00", "350.00")))
    assert any(d.field == "superficie" and d.kind == "real" and d.critical for d in s.discrepancies)
    assert s.verdict.recommendation == Recommendation.REVIEW

def test_surface_pending_tolerance_when_not_configured_is_review():
    rs = RS.model_copy(deep=True); rs.thresholds.surface_tolerance_pct = None
    s = Supervisor(rs).run(DossierState(dossier_id=1, reference_date=TODAY, documents=full_inputs(predial=DOCS["predial"].replace("200.00", "350.00"))))
    assert any(d.field == "superficie" and d.kind == "tolerancia_pendiente" for d in s.discrepancies)
    assert s.verdict.recommendation == Recommendation.REVIEW

def test_surface_tolerance_configurable():
    rs = RS.model_copy(deep=True); rs.thresholds.surface_tolerance_pct = 5
    s = Supervisor(rs).run(DossierState(dossier_id=1, reference_date=TODAY, documents=full_inputs(predial=DOCS["predial"].replace("200.00", "203.00"))))
    assert next(d for d in s.discrepancies if d.field == "superficie").kind == "formato"

def test_incompatible_land_use_is_no_cumple():
    s = run(full_inputs(uso_suelo=DOCS["uso_suelo"].replace("uso comercial: Sí", "uso comercial: No compatible")))
    assert s.verdict.recommendation == Recommendation.FAIL
    assert "uso_suelo.compatibilidad" in s.verdict.unmet

def test_expired_document_is_no_cumple():
    s = run(full_inputs(alineamiento=DOCS["alineamiento"].replace("01/02/2027", "01/02/2025")))
    assert s.verdict.recommendation == Recommendation.FAIL
    assert any(r.category == "vigencia" and r.outcome == Outcome.FAIL for r in s.rules)

def test_unparseable_validity_is_indeterminate_review():
    s = run(full_inputs(alineamiento=DOCS["alineamiento"].replace("01/02/2027", "según dictamen técnico")))
    assert s.verdict.recommendation == Recommendation.REVIEW

def test_unrecognized_document_flagged():
    s = run(full_inputs() + [doc_input(9, "Receta de cocina: harina, huevos")])
    c = next(c for c in s.classifications if c.document_id == 9)
    assert c.doc_type == DocumentType.NO_RECONOCIDO and c.needs_review
    assert s.verdict.recommendation == Recommendation.REVIEW

def test_illegible_document_warns_and_reviews():
    s = run([doc_input(1, "")])
    assert s.warnings and s.verdict.recommendation == Recommendation.REVIEW

def test_content_duplicate_detected():
    s = run(full_inputs() + [doc_input(8, DOCS["predial"])])
    assert 8 in s.duplicates

def test_wrong_classification_manual_is_respected():
    docs = full_inputs()
    st = DossierState(dossier_id=1, documents=docs, reference_date=TODAY,
                      classifications=[Classification(document_id=2, doc_type=DocumentType.USO_SUELO, confidence=1, manual=True)])
    out = Supervisor(RS).run(st)
    assert next(c for c in out.classifications if c.document_id == 2).doc_type == DocumentType.USO_SUELO

def test_provisional_failure_never_yields_no_cumple():
    s = run(full_inputs(escritura=DOCS["escritura"].replace("Titular: Juan Pérez López\n", "")))
    assert s.verdict.recommendation == Recommendation.REVIEW


# ---- evidencia inexistente (LLM que alucina)
class FakeLLM:
    def __init__(self, payload): self.payload = payload
    def complete_json(self, system, user): return self.payload

def test_hallucinated_quote_is_unverified_and_blocks_conclusions():
    payload = {"fields": [{"name": "uso_autorizado", "value": "Comercial", "page": 1, "quote": "Uso autorizado: Industrial pesado"},
                          {"name": "compatibilidad_uso_comercial", "value": "No", "page": 1, "quote": "Compatibilidad: No (inventado)"}]}
    f = ExtractorFactory(RS, FakeLLM(payload), "sys")
    s = run(full_inputs(), factory=f)
    assert any(x.evidence.verification == Verification.UNVERIFIED for x in s.fields)
    assert s.verdict.recommendation == Recommendation.REVIEW  # nunca NO CUMPLE con evidencia no verificada

def test_invalid_llm_output_is_handled():
    s = run(full_inputs(), factory=ExtractorFactory(RS, FakeLLM({"basura": 1}), "sys"))
    assert s.verdict.recommendation == Recommendation.REVIEW and any("inválida" in w for w in s.warnings)


# ---- supervisor
def test_supervisor_retries_then_succeeds():
    calls = {"n": 0}
    sup = Supervisor(RS, sleep=lambda s: None)
    orig = sup.agents["classify"].run
    def flaky(state):
        calls["n"] += 1
        if calls["n"] < 3: raise OSError("transitorio")
        return orig(state)
    sup.agents["classify"].run = flaky
    events = []
    sup.observer = type("O", (), {"on_event": lambda self, e, a, s, p: events.append(e)})()
    sup.run(DossierState(dossier_id=1, documents=full_inputs(), reference_date=TODAY))
    assert events.count("retry") == 2

def test_supervisor_gives_up_after_max_retries():
    sup = Supervisor(RS, max_retries=1, sleep=lambda s: None)
    sup.agents["classify"].run = lambda state: (_ for _ in ()).throw(OSError("x"))
    with pytest.raises(OSError):
        sup.run(DossierState(dossier_id=1, documents=full_inputs()))

def test_rerun_from_rules_stage():
    s = run(full_inputs())
    s.rules = []; s.verdict = None
    s = Supervisor(RS).run(s, "rules")
    assert s.verdict.recommendation == Recommendation.PASS

def test_langgraph_equivalent_to_supervisor():
    sup = Supervisor(RS)
    g = build_langgraph(sup)
    out = g.invoke(DossierState(dossier_id=1, documents=full_inputs(), reference_date=TODAY))
    assert out["verdict"]["recommendation"] == Recommendation.PASS


# ---- configuración
def test_invalid_ruleset_rejected():
    with pytest.raises(RuleSetError):
        parse_ruleset("version: x")
    with pytest.raises(RuleSetError):
        parse_ruleset(open("rules/ruleset.yaml").read().replace("type: required_field", "type: inventada", 1))

def test_new_rule_without_code_changes():
    txt = open("rules/ruleset.yaml").read() + "\n"
    txt = txt.replace("rules:\n", "rules:\n  - {id: predial.direccion.presente, doc_type: predial, type: required_field, field: direccion, provisional: true}\n", 1)
    rs = parse_ruleset(txt)
    s = Supervisor(rs).run(DossierState(dossier_id=1, documents=full_inputs(), reference_date=TODAY))
    assert "predial.direccion.presente" in s.verdict.satisfied

def test_reproducible():
    a, b = run(full_inputs()), run(full_inputs())
    assert a.verdict == b.verdict


def test_extractor_value_on_next_line_and_inline_label():
    text = "Constancia de alineamiento y número oficial\nNÚMERO OFICIAL\n245-B\nDIRECCIÓN OFICIAL Calle Hidalgo 12 Col. Centro\nVIGENCIA\n01/02/2027"
    s = run([doc_input(1, text)])
    f = {x.name: x for x in s.fields if x.found}
    assert f["numero_oficial"].raw == "245-B" and f["direccion_oficial"].raw.startswith("Calle Hidalgo")
    assert f["vigencia"].raw == "01/02/2027"
    assert all(x.evidence.verification == Verification.VERIFIED for x in f.values())
