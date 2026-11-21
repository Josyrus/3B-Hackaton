from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404

from apps.audit.models import audit
from apps.dossiers.models import Dossier
from .exporters import build_export_dict, to_json, to_pdf


@login_required
def export(request, pk, fmt):
    d = get_object_or_404(Dossier, pk=pk)
    verdict = d.verdicts.first()
    if verdict is None or fmt not in ("json", "pdf"):
        raise Http404
    data = build_export_dict(d, verdict)
    audit(request.user, f"export.{fmt}", d.code)
    if fmt == "json":
        resp = HttpResponse(to_json(data), content_type="application/json")
    else:
        resp = HttpResponse(to_pdf(data), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="dictamen_{d.code}.{fmt}"'
    return resp
