"""Configuración de la app core."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Utilidades transversales (health check)."""

    name = "apps.core"
    label = "core"
    verbose_name = "Núcleo"
