from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=60, db_index=True)
    object_ref = models.CharField(max_length=80, blank=True)
    detail = models.CharField(max_length=300, blank=True)  # metadatos, nunca contenido documental
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]


def audit(user, action: str, object_ref: str = "", detail: str = "") -> None:
    AuditLog.objects.create(user=user if getattr(user, "pk", None) else None, action=action,
                            object_ref=object_ref, detail=detail[:300])
