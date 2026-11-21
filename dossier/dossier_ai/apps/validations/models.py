from django.conf import settings
from django.db import models


class RuleSetVersion(models.Model):
    """Versiones de la configuración YAML (reglas, esquemas, umbrales). La activa es la más reciente."""
    version = models.CharField(max_length=40)
    yaml_text = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]


class RuleResult(models.Model):
    dossier = models.ForeignKey("dossiers.Dossier", on_delete=models.CASCADE, related_name="rule_results")
    rule_id = models.CharField(max_length=80)
    doc_type = models.CharField(max_length=20, blank=True)
    outcome = models.CharField(max_length=15)
    category = models.CharField(max_length=20)
    provisional = models.BooleanField(default=False)
    message = models.TextField(blank=True)
    evidence = models.JSONField(default=list)
    ruleset_version = models.CharField(max_length=40)


class CrossDiscrepancy(models.Model):
    dossier = models.ForeignKey("dossiers.Dossier", on_delete=models.CASCADE, related_name="discrepancies")
    field = models.CharField(max_length=60)
    kind = models.CharField(max_length=25)
    critical = models.BooleanField(default=False)
    values = models.JSONField(default=list)
