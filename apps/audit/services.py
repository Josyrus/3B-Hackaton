"""Servicio de aplicación para registrar eventos de auditoría."""

from __future__ import annotations

from typing import Any

from django.db.models import Model
from django.http import HttpRequest

from .models import AuditAction, AuditLog


def record_audit(
    action: AuditAction,
    *,
    user: Any = None,
    request: HttpRequest | None = None,
    obj: Model | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Registra un evento de auditoría.

    El usuario se toma de ``request`` si no se indica. La IP es siempre
    ``REMOTE_ADDR`` (X-Forwarded-For es falsificable y no se usa).
    ``metadata`` debe contener solo identificadores, nunca texto documental.
    """
    if user is None and request is not None:
        candidate = getattr(request, "user", None)
        if candidate is not None and candidate.is_authenticated:
            user = candidate
    return AuditLog.objects.create(
        user=user if user is not None and user.is_authenticated else None,
        action=action,
        object_type=obj._meta.label_lower if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
        ip_address=request.META.get("REMOTE_ADDR") if request is not None else None,
        metadata=metadata or {},
    )
