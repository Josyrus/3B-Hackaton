from django.conf import settings
from django.db import models


class ExtractedField(models.Model):
    """Dato extraído con evidencia. Las correcciones manuales crean una nueva versión (no sobrescriben)."""
    dossier = models.ForeignKey("dossiers.Dossier", on_delete=models.CASCADE, related_name="fields")
    document = models.ForeignKey("documents.Document", on_delete=models.CASCADE, related_name="fields")
    doc_type = models.CharField(max_length=20)
    name = models.CharField(max_length=60)
    raw_value = models.TextField()
    normalized_value = models.TextField()
    page = models.PositiveIntegerField(null=True)
    quote = models.TextField(blank=True)
    verification = models.CharField(max_length=24, default="pendiente")
    origin = models.CharField(max_length=10, default="agent")
    version = models.PositiveIntegerField(default=1)
    is_current = models.BooleanField(default=True, db_index=True)
    corrected_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["doc_type", "name", "-version"]
