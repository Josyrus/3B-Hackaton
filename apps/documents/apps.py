"""Configuración de la app documents."""

from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    """Gestión documental: almacenamiento privado (Fase 2); carga y OCR (Fase 3)."""

    name = "apps.documents"
    label = "documents"
    verbose_name = "Documentos"

    def ready(self) -> None:
        from . import checks  # noqa: F401
