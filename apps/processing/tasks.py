"""Tareas Celery."""

from celery import shared_task


@shared_task(name="processing.ping")
def ping() -> str:
    """Tarea de humo para verificar que el worker está operativo."""
    return "pong"
