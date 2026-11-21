from django.db import models


class AgentRun(models.Model):
    """Bitácora de agentes: entrada/salida estructurada, estado, tiempo, errores y reintentos."""
    dossier = models.ForeignKey("dossiers.Dossier", on_delete=models.CASCADE, related_name="agent_runs")
    agent = models.CharField(max_length=40)
    stage = models.CharField(max_length=20)
    status = models.CharField(max_length=12, default="running")  # running | ok | error
    output = models.JSONField(default=dict)
    duration_ms = models.PositiveIntegerField(default=0)
    retries = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=200, blank=True)
    ruleset_version = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
