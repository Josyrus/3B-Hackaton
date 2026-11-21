"""Adaptador Django ↔ núcleo: arma el estado desde la BD, ejecuta el supervisor y persiste resultados."""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.db import transaction

from apps.documents.models import Classification, DocStatus, Document
from apps.dossiers.models import Dossier, DossierStatus
from apps.findings.models import ExtractedField
from apps.reports.models import Verdict
from apps.validations.models import CrossDiscrepancy, RuleResult
from apps.validations.rulesets import active_ruleset
from core.agents.pipeline import ExtractorFactory, normalize_value, field_kind
from core.contracts import (Classification as CCls, DocumentInput, DocumentType, DossierState, Evidence, FieldValue,
                            PageText, Verification)
from core.graph.supervisor import STAGES, Supervisor
from core.ports import OllamaLLM
from .models import AgentRun

PROMPT = Path(__file__).resolve().parent.parent.parent / "prompts" / "extractor_v1.txt"


class DBObserver:
    """Observer: persiste cada evento de agente y el progreso del expediente."""

    def __init__(self, dossier: Dossier, ruleset_version: str) -> None:
        self.dossier, self.version, self.runs = dossier, ruleset_version, {}

    def on_event(self, event: str, agent: str, stage: str, payload: dict) -> None:
        d = self.dossier
        if event == "start":
            self.runs[stage] = AgentRun.objects.create(dossier=d, agent=agent, stage=stage, ruleset_version=self.version)
            Dossier.objects.filter(pk=d.pk).update(current_stage=stage, progress=payload["progress"])
        elif event == "finish":
            AgentRun.objects.filter(pk=self.runs[stage].pk).update(
                status="ok", output=payload["output"], duration_ms=payload["duration_ms"], retries=payload["retries"])
            Dossier.objects.filter(pk=d.pk).update(progress=payload["progress"])
        elif event == "error":
            AgentRun.objects.filter(pk=self.runs[stage].pk).update(status="error", error=payload["error"], retries=payload["retries"])


def build_state(dossier: Dossier, from_stage: str) -> DossierState:
    docs = Document.objects.filter(dossier=dossier, status=DocStatus.OK).prefetch_related("pages")
    state = DossierState(dossier_id=dossier.pk, required_use=dossier.required_use, documents=[
        DocumentInput(id=d.pk, name=d.original_name, pages=[PageText(page=p.number, text=p.text) for p in d.pages.all()]) for d in docs])
    idx = STAGES.index
    if idx(from_stage) > idx("ingest"):
        state.duplicates = list(Classification.objects.filter(document__dossier=dossier, is_content_duplicate=True).values_list("document_id", flat=True))
    cls_qs = Classification.objects.filter(document__dossier=dossier, document__status=DocStatus.OK)
    if idx(from_stage) <= idx("classify"):
        cls_qs = cls_qs.filter(manual=True)  # el clasificador respeta las correcciones manuales
    state.classifications = [CCls(document_id=c.document_id, doc_type=DocumentType(c.doc_type), confidence=c.confidence,
                                  needs_review=c.needs_review, manual=c.manual) for c in cls_qs]
    fields = dossier.fields.filter(is_current=True)
    if idx(from_stage) <= idx("extract"):
        fields = fields.filter(origin="manual")  # los datos corregidos manualmente se conservan
    state.fields = [_to_fv(f) for f in fields]
    return state


def _to_fv(f: ExtractedField) -> FieldValue:
    kind = field_kind(f.name)
    return FieldValue(doc_type=DocumentType(f.doc_type), name=f.name, raw=f.raw_value,
                      normalized=f.normalized_value or normalize_value(kind, f.raw_value), origin=f.origin,
                      evidence=Evidence(document_id=f.document_id, page=f.page, quote=f.quote, verification=Verification(f.verification)))


def make_factory() -> ExtractorFactory | None:
    if settings.EXTRACTOR_BACKEND == "llm":
        return ExtractorFactory(active_ruleset()[0], OllamaLLM(settings.LLM_MODEL, settings.LLM_BASE_URL), PROMPT.read_text(encoding="utf-8"))
    return None


@transaction.atomic
def persist(dossier: Dossier, state: DossierState, from_stage: str, version: str) -> None:
    idx = STAGES.index
    if idx(from_stage) <= idx("classify"):
        for c in state.classifications:
            Classification.objects.update_or_create(document_id=c.document_id, defaults={
                "doc_type": c.doc_type.value, "confidence": c.confidence, "needs_review": c.needs_review,
                "manual": c.manual, "is_content_duplicate": False})
        Classification.objects.filter(document__dossier=dossier, document_id__in=state.duplicates).update(is_content_duplicate=True)
        Classification.objects.filter(document__dossier=dossier).exclude(document_id__in=[c.document_id for c in state.classifications]).delete()
    if idx(from_stage) <= idx("verify"):
        keep = ExtractedField.objects.filter(dossier=dossier, origin="manual", is_current=True)
        ExtractedField.objects.filter(dossier=dossier, origin="agent").update(is_current=False)
        for f in state.fields:
            if f.origin == "manual":
                keep.filter(document_id=f.evidence.document_id, doc_type=f.doc_type.value, name=f.name).update(
                    normalized_value=f.normalized, verification=f.evidence.verification.value)
                continue
            ExtractedField.objects.create(
                dossier=dossier, document_id=f.evidence.document_id, doc_type=f.doc_type.value,
                name=f.name, raw_value=f.raw, normalized_value=f.normalized, page=f.evidence.page, quote=f.evidence.quote,
                verification=f.evidence.verification.value if f.found else "no_aplica")
    RuleResult.objects.filter(dossier=dossier).delete()
    RuleResult.objects.bulk_create(RuleResult(
        dossier=dossier, rule_id=r.rule_id, doc_type=r.doc_type.value if r.doc_type else "", outcome=r.outcome.value,
        category=r.category, provisional=r.provisional, message=r.message,
        evidence=[e.model_dump(mode="json") for e in r.evidence], ruleset_version=version) for r in state.rules)
    CrossDiscrepancy.objects.filter(dossier=dossier).delete()
    CrossDiscrepancy.objects.bulk_create(CrossDiscrepancy(dossier=dossier, field=d.field, kind=d.kind, critical=d.critical, values=d.values) for d in state.discrepancies)
    v = state.verdict
    Verdict.objects.create(dossier=dossier, recommendation=v.recommendation.value, confidence=v.confidence,
                           payload={**v.model_dump(mode="json"), "warnings": state.warnings}, ruleset_version=version)
    Dossier.objects.filter(pk=dossier.pk).update(status=DossierStatus.ANALYZED, progress=100, current_stage="verdict",
                                                 recommendation=v.recommendation.value, confidence=v.confidence)


def run_analysis(dossier_id: int, from_stage: str = "ingest") -> None:
    dossier = Dossier.objects.get(pk=dossier_id)
    ruleset, version = active_ruleset()
    state = build_state(dossier, from_stage)
    try:
        state = Supervisor(ruleset, DBObserver(dossier, version), make_factory()).run(state, from_stage)
        persist(dossier, state, from_stage, version)
    except Exception:
        Dossier.objects.filter(pk=dossier_id).update(status=DossierStatus.ERROR)
        raise
