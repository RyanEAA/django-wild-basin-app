from django.db import models
from django.utils import timezone
from django.conf import settings


class ImportJob(models.Model):
    FILE_TYPES = [
        ("box_images", "Box Image Metadata"),
        ("speciesnet", "SpeciesNet JSONL"),
        ("ocr", "PaddleOCR JSONL"),
    ]

    researcher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    file_type = models.CharField(max_length=50, choices=FILE_TYPES)
    filename = models.CharField(max_length=255)

    records_created = models.IntegerField(default=0)
    records_updated = models.IntegerField(default=0)
    records_failed = models.IntegerField(default=0)

    error_message = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.file_type} - {self.filename}"


class ImageRecord(models.Model):
    file_id = models.CharField(max_length=255, unique=True)
    file_name = models.CharField(max_length=255, blank=True)
    path = models.TextField(blank=True)

    file_url = models.URLField(max_length=500, blank=True)
    direct_download_url = models.URLField(max_length=500, blank=True)
    preview_url = models.URLField(max_length=500, blank=True)

    cached_image = models.ImageField(
        upload_to="cached_box_images/",
        blank=True,
        null=True,
    )

    cache_last_accessed = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def touch_cache(self):
        self.cache_last_accessed = timezone.now()
        self.save(update_fields=["cache_last_accessed"])

    def __str__(self):
        return f"{self.file_name} ({self.file_id})"


class SpeciesNetResult(models.Model):
    image = models.OneToOneField(
        ImageRecord,
        on_delete=models.CASCADE,
        related_name="species_result",
    )

    status = models.CharField(max_length=50, blank=True)
    prediction = models.TextField(blank=True)
    prediction_score = models.FloatField(null=True, blank=True)
    prediction_source = models.CharField(max_length=255, blank=True)

    animals = models.JSONField(default=list, blank=True)
    detections = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"SpeciesNetResult(image={self.image.file_id}, status={self.status})"


class OCRResult(models.Model):
    image = models.OneToOneField(
        ImageRecord,
        on_delete=models.CASCADE,
        related_name="ocr_result",
    )

    status = models.CharField(max_length=50, blank=True)
    ocr_texts = models.JSONField(default=list, blank=True)

    temperature_f = models.FloatField(null=True, blank=True)
    capture_date = models.DateField(null=True, blank=True)
    capture_time = models.TimeField(null=True, blank=True)
    capture_datetime = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"OCRResult(image={self.image.file_id}, status={self.status})"


class AppSettings(models.Model):
    box_client_id = models.TextField(blank=True)
    box_client_secret = models.TextField(blank=True)
    
    box_access_token = models.TextField(blank=True)
    box_refresh_token = models.TextField(blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "Application Settings"