"""Modelo de auditoría (append-only)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models


class AuditAction(models.TextChoices):
    """Catálogo de acciones auditables."""

    LOGIN = "login", "Inicio de sesión"
    LOGOUT = "logout", "Cierre de sesión"
    LOGIN_FAILED = "login_failed", "Intento de sesión fallido"
    DOSSIER_CREATED = "dossier_created", "Expediente creado"
    DOCUMENT_UPLOADED = "document_uploaded", "Documento cargado"
    DOCUMENT_VIEWED = "document_viewed", "Documento consultado"
    CLASSIFICATION_CORRECTED = "classification_corrected", "Clasificación corregida"
    DATA_CORRECTED = "data_corrected", "Dato extraído corregido"
    ANALYSIS_STARTED = "analysis_started", "Análisis iniciado"
    ANALYSIS_RERUN = "analysis_rerun", "Validación re-ejecutada"
    REPORT_EXPORTED = "report_exported", "Dictamen exportado"
    CONFIG_CHANGED = "config_changed", "Configuración modificada"


class AuditLog(models.Model):
    """Evento de auditoría.

    Solo registra QUIÉN hizo QUÉ y CUÁNDO, con identificadores. Nunca debe
    guardar contenido documental en ``metadata``.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    action = models.CharField(max_length=40, choices=AuditAction.choices, db_index=True)
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["object_type", "object_id"])]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M:%S} {self.action}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise PermissionError("Los registros de auditoría son inmutables.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise PermissionError("Los registros de auditoría no se pueden eliminar.")
