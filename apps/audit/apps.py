"""Configuración de la app audit."""

from django.apps import AppConfig


class AuditConfig(AppConfig):
    """Registro de auditoría de acciones de usuario."""

    name = "apps.audit"
    label = "audit"
    verbose_name = "Auditoría"

    def ready(self) -> None:
        from . import signals  # noqa: F401
