"""Auditoría automática de autenticación."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import AuditAction
from .services import record_audit


@receiver(user_logged_in)
def audit_login(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    record_audit(AuditAction.LOGIN, user=user, request=request)


@receiver(user_logged_out)
def audit_logout(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    if user is not None:
        record_audit(AuditAction.LOGOUT, user=user, request=request)


@receiver(user_login_failed)
def audit_login_failed(
    sender: Any, credentials: dict[str, Any], request: Any = None, **kwargs: Any
) -> None:
    # Se guarda solo el nombre de usuario intentado, nunca la contraseña.
    attempted = str(credentials.get("username", ""))[:150]
    record_audit(AuditAction.LOGIN_FAILED, request=request, metadata={"username": attempted})
