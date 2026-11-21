from django.db import models


class Verdict(models.Model):
    """Histórico de dictámenes por expediente (cada re-ejecución crea uno nuevo)."""
    dossier = models.ForeignKey("dossiers.Dossier", on_delete=models.CASCADE, related_name="verdicts")
    recommendation = models.CharField(max_length=20)
    confidence = models.FloatField()
    payload = models.JSONField()
    ruleset_version = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
