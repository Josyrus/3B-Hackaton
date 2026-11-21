"""Endpoint de salud para monitoreo (sin datos sensibles)."""

from __future__ import annotations

import logging

import redis
from django.conf import settings
from django.db import DatabaseError, connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


def _check_database() -> str:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        logger.warning("health: base de datos no disponible")
        return "error"
    return "ok"


def _check_broker() -> str:
    if settings.CELERY_TASK_ALWAYS_EAGER:
        return "skipped"
    try:
        redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2).ping()
    except redis.RedisError:
        logger.warning("health: broker no disponible")
        return "error"
    return "ok"


@require_GET
def health(request: HttpRequest) -> JsonResponse:
    """Devuelve 200 si DB y broker responden, 503 en otro caso.

    Los errores no se detallan en la respuesta para no filtrar información.
    """
    checks = {"database": _check_database(), "broker": _check_broker()}
    healthy = all(value in {"ok", "skipped"} for value in checks.values())
    return JsonResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status=200 if healthy else 503,
    )
