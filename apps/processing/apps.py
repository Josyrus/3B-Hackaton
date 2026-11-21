"""Configuración de la app processing."""

from django.apps import AppConfig


class ProcessingConfig(AppConfig):
    """Tareas asíncronas Celery. Aquí vivirá la ejecución del análisis (Fase 4)."""

    name = "apps.processing"
    label = "processing"
    verbose_name = "Procesamiento"
