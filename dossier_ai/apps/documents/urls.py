from django.urls import path
from . import views

urlpatterns = [
    path("documentos/<int:doc_id>/pdf/", views.pdf_file, name="pdf_file"),
    path("documentos/<int:doc_id>/evidencia/", views.evidence_viewer, name="evidence_viewer"),
]
