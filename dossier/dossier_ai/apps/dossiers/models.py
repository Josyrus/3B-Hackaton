import builtins

from django.conf import settings
from django.db import models


class Property(models.Model):
    """Inmueble. Un expediente corresponde a un inmueble."""
    address = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class DossierStatus(models.TextChoices):
    CREATED = "creado", "Creado"
    PROCESSING = "procesando", "Procesando"
    ANALYZED = "analizado", "Analizado"
    ERROR = "error", "Error"


class Dossier(models.Model):
    code = models.CharField(max_length=20, unique=True, editable=False)
    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name="dossiers")
    required_use = models.CharField("Uso comercial requerido", max_length=200, blank=True)
    status = models.CharField(max_length=12, choices=DossierStatus.choices, default=DossierStatus.CREATED, db_index=True)
    progress = models.PositiveSmallIntegerField(default=0)
    current_stage = models.CharField(max_length=30, blank=True)
    recommendation = models.CharField(max_length=20, blank=True, db_index=True)
    confidence = models.FloatField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.code:
            from django.utils import timezone
            n = Dossier.objects.count() + 1
            self.code = f"EXP-{timezone.now():%Y}-{n:05d}"
            while Dossier.objects.filter(code=self.code).exists():
                n += 1
                self.code = f"EXP-{timezone.now():%Y}-{n:05d}"
        super().save(*args, **kwargs)

    @builtins.property
    def get_recommendation_label(self) -> str:
        from .labels import verdict_label
        return verdict_label(self.recommendation)

    @builtins.property
    def verdict_key(self) -> str:
        """Clave visual binaria: 'cumple' (Aprobado) o 'no_cumple' (No aprobado); vacío si aún no hay dictamen."""
        return "" if not self.recommendation else ("cumple" if self.recommendation == "cumple" else "no_cumple")

    def __str__(self) -> str:
        return self.code
