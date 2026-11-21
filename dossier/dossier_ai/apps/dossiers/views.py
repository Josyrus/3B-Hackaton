from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import role_required
from apps.audit.models import audit
from apps.documents.models import Document
from apps.documents.services import UploadRejected, expand_uploads
from apps.findings.models import ExtractedField
from core.contracts import DocumentType
from . import specs
from .labels import AGENTS
from .models import Dossier, DossierStatus
from .services import DossierAnalysisFacade


def _home_context() -> dict:
    qs = Dossier.objects
    total = qs.count()
    labels = {"cumple": "Aprobado", "no_cumple": "No aprobado"}
    raw = {r["recommendation"]: r["n"] for r in qs.exclude(recommendation="").values("recommendation").annotate(n=Count("id"))}
    counts = {"cumple": raw.get("cumple", 0), "no_cumple": sum(n for k, n in raw.items() if k != "cumple")}
    judged = sum(counts.values())
    return {
        "total": total,
        "pending": qs.exclude(status=DossierStatus.ANALYZED).count(),
        "analyzed": qs.filter(status=DossierStatus.ANALYZED).count(),
        "distribution": [{"key": k, "label": v, "n": counts.get(k, 0),
                          "pct": round(100 * counts.get(k, 0) / judged) if judged else 0} for k, v in labels.items()],
        "judged": judged,
        "recent": qs.select_related("property")[:6],
        "max_mb": settings.MAX_UPLOAD_MB,
    }


@login_required
def dashboard(request):
    """Inicio: carga de documentos (acción principal) y resumen."""
    if request.method == "POST":
        files = [(f.name, f.read()) for f in request.FILES.getlist("files")]
        try:
            items = expand_uploads(files)
        except UploadRejected as exc:
            messages.error(request, str(exc))
            return render(request, "dashboard.html", _home_context(), status=400)
        dossier, report = DossierAnalysisFacade.create_from_items(
            request.user, items, address=request.POST.get("address", "").strip())
        for m in report.messages:
            messages.warning(request, m)
        messages.success(request, f"Expediente {dossier.code} creado. El análisis inició automáticamente.")
        return redirect("progress", pk=dossier.pk)
    return render(request, "dashboard.html", _home_context())


@login_required
def upload(request):
    """Ruta histórica: la carga ahora vive en el inicio."""
    if request.method == "POST":
        return dashboard(request)
    return redirect("dashboard")


@login_required
def dossier_list(request):
    qs = Dossier.objects.filter(specs.from_params(request.GET).q).select_related("property")
    return render(request, "list.html", {"dossiers": qs, "statuses": DossierStatus.choices, "f": request.GET})


@login_required
def progress(request, pk):
    return render(request, "progress.html", {"dossier": get_object_or_404(Dossier, pk=pk),
                                             "runs": get_object_or_404(Dossier, pk=pk).agent_runs.all()})


@login_required
def progress_json(request, pk):
    d = get_object_or_404(Dossier, pk=pk)
    runs = [{"agent": AGENTS.get(r.agent, r.agent), "status": r.status, "ms": r.duration_ms, "retries": r.retries, "error": r.error} for r in d.agent_runs.all()]
    return JsonResponse({"status": d.status, "progress": d.progress, "stage": d.current_stage, "runs": runs})


def _reasons(payload: dict) -> list[str]:
    """Motivos mostrados en el dictamen final. Se omiten las líneas de 'confianza' (métrica interna que ya no se muestra)."""
    return [j for j in payload.get("justification", []) if "confianza" not in j.lower()]


@login_required
def detail(request, pk):
    d = get_object_or_404(Dossier.objects.select_related("property"), pk=pk)
    verdict = d.verdicts.first()
    payload = verdict.payload if verdict else {}
    docs = d.documents.select_related("classification").annotate(ocr_avg=Avg("pages__ocr_confidence"))
    fields = d.fields.filter(is_current=True, origin__in=["agent", "manual"]).select_related("document")
    ctx = {
        "dossier": d, "verdict": verdict, "payload": payload, "documents": docs,
        "doc_types": [t for t in DocumentType], "fields": fields,
        "found_fields": [f for f in fields if f.raw_value != "no encontrado"],
        "rules": d.rule_results.all(), "discrepancies": d.discrepancies.all(), "runs": d.agent_runs.all(),
        "warnings": payload.get("warnings", []),
        "reasons": _reasons(payload),
    }
    return render(request, "detail.html", ctx)


@require_POST
@role_required("can_correct")
def correct_classification(request, doc_id):
    doc = get_object_or_404(Document, pk=doc_id)
    doc_type = request.POST.get("doc_type", "")
    if doc_type not in {t.value for t in DocumentType}:
        messages.error(request, "Tipo documental inválido.")
    else:
        DossierAnalysisFacade.correct_classification(request.user, doc, doc_type)
        messages.success(request, "Clasificación corregida; se re-ejecutaron las etapas afectadas.")
    return redirect("progress", pk=doc.dossier_id)


@require_POST
@role_required("can_correct")
def correct_field(request, field_id):
    f = get_object_or_404(ExtractedField, pk=field_id, is_current=True)
    value = request.POST.get("value", "").strip()
    if not value:
        messages.error(request, "El valor no puede estar vacío.")
        return redirect("detail", pk=f.dossier_id)
    DossierAnalysisFacade.correct_field(request.user, f, value)
    messages.success(request, "Dato corregido (nueva versión); validaciones re-ejecutadas.")
    return redirect("progress", pk=f.dossier_id)


@require_POST
@role_required("can_correct")
def rerun(request, pk):
    d = get_object_or_404(Dossier, pk=pk)
    audit(request.user, "dossier.rerun", d.code)
    DossierAnalysisFacade.start(d, "rules")
    return redirect("progress", pk=d.pk)
