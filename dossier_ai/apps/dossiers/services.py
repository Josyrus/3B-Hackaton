"""Casos de uso del expediente (Facade): crear, iniciar análisis, corregir y re-ejecutar."""
from __future__ import annotations

from django.db import transaction

from apps.audit.models import audit
from apps.documents.models import Classification, Document
from apps.documents.services import IngestReport, UploadItem, ingest_items
from apps.findings.models import ExtractedField
from .models import Dossier, DossierStatus, Property


class DossierAnalysisFacade:
    """Punto de entrada único para vistas y API."""

    @staticmethod
    @transaction.atomic
    def create_from_items(user, items: list[UploadItem], required_use: str = "", address: str = "") -> tuple[Dossier, IngestReport]:
        prop = Property.objects.create(address=address)
        dossier = Dossier.objects.create(property=prop, required_use=required_use, created_by=user)
        report = ingest_items(dossier, items)
        audit(user, "dossier.create", dossier.code, f"{len(report.created)} archivo(s)")
        DossierAnalysisFacade.start(dossier)
        return dossier, report

    @staticmethod
    def start(dossier: Dossier, from_stage: str = "ingest") -> None:
        from apps.processing.tasks import analyze_dossier
        Dossier.objects.filter(pk=dossier.pk).update(status=DossierStatus.PROCESSING, progress=0, current_stage=from_stage)
        transaction.on_commit(lambda: analyze_dossier.delay(dossier.pk, from_stage))

    @staticmethod
    @transaction.atomic
    def correct_classification(user, document: Document, doc_type: str) -> None:
        cls, _ = Classification.objects.get_or_create(document=document, defaults={"doc_type": doc_type, "confidence": 1.0})
        cls.doc_type, cls.confidence, cls.manual, cls.needs_review = doc_type, 1.0, True, False
        cls.save()
        ExtractedField.objects.filter(document=document, origin="agent").update(is_current=False)
        audit(user, "classification.correct", document.dossier.code, f"doc {document.pk} -> {doc_type}")
        DossierAnalysisFacade.start(document.dossier, "classify")

    @staticmethod
    @transaction.atomic
    def correct_field(user, field: ExtractedField, new_value: str) -> None:
        """Nueva versión manual del dato; conserva la original. Se re-ejecutan validaciones."""
        field.is_current = False
        field.save(update_fields=["is_current"])
        ExtractedField.objects.create(
            dossier=field.dossier, document=field.document, doc_type=field.doc_type, name=field.name,
            raw_value=new_value, normalized_value="", page=field.page, quote=field.quote,
            verification="corregida_manualmente", origin="manual", version=field.version + 1, corrected_by=user)
        audit(user, "field.correct", field.dossier.code, f"{field.doc_type}.{field.name} v{field.version + 1}")
        DossierAnalysisFacade.start(field.dossier, "extract")
