from django.db import models


class DocStatus(models.TextChoices):
    OK = "ok", "Procesable"
    CORRUPT = "corrupto", "Corrupto/ilegible"
    DUPLICATE = "duplicado", "Duplicado exacto"


class Document(models.Model):
    dossier = models.ForeignKey("dossiers.Dossier", on_delete=models.CASCADE, related_name="documents")
    original_name = models.CharField(max_length=255)
    storage_path = models.CharField(max_length=400)  # relativo a PRIVATE_STORAGE_ROOT
    sha256 = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=10, choices=DocStatus.choices, default=DocStatus.OK)
    status_detail = models.CharField(max_length=200, blank=True)
    page_count = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class DocumentPage(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="pages")
    number = models.PositiveIntegerField()
    text = models.TextField(blank=True)

    class Meta:
        unique_together = [("document", "number")]
        ordering = ["number"]


class Classification(models.Model):
    document = models.OneToOneField(Document, on_delete=models.CASCADE, related_name="classification")
    doc_type = models.CharField(max_length=20)
    confidence = models.FloatField()
    needs_review = models.BooleanField(default=False)
    manual = models.BooleanField(default=False)
    is_content_duplicate = models.BooleanField(default=False)
