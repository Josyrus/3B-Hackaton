from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
import io

from apps.audit.models import audit
from .models import Document
from .services import read_private


@login_required
def pdf_file(request, doc_id):
    """Entrega controlada del PDF (nunca por URL pública)."""
    doc = get_object_or_404(Document, pk=doc_id)
    try:
        data = read_private(doc)
    except (FileNotFoundError, PermissionError) as exc:
        raise Http404 from exc
    audit(request.user, "document.view", doc.dossier.code, f"doc {doc.pk}")
    resp = FileResponse(io.BytesIO(data), content_type="application/pdf")
    resp["Content-Disposition"] = 'inline; filename="documento.pdf"'
    resp["Cache-Control"] = "private, no-store"
    return resp


@login_required
def evidence_viewer(request, doc_id):
    doc = get_object_or_404(Document, pk=doc_id)
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1
    return render(request, "evidence_viewer.html", {"doc": doc, "page": page, "quote": request.GET.get("q", "")[:300]})
