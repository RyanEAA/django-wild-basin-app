from django.db import models
from django.utils import timezone
from django.conf import settings

from images.utils.ocr_parser import parse_ocr_metadata

# Create your models here.
class ImageRecord(models.Model):
    file_id = models.CharField(max_length=255, unique=True)
    field_name = models.CharField(max_length=255)
    path = models.CharField(max_length=255)

    file_url = models.URLField(max_length=500)
    direct_download_url = models.URLField(max_length=500)
    preview_url = models.URLField(max_length=500)

    cached_image = models.ImageField(
        upload_to="cached_box_images/",
        blank=True,
        null=True
    )

    cache_last_accessed = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def touch_cache(self):
        self.cache_last_accessed = timezone.now()
        self.save()

    def __str__(self):
        return f"ImageRecord(file_id={self.file_id}, field_name={self.field_name})"
    

class SpeciesNetResult(models.Model):
    species_name = models.OneToOneField(
        ImageRecord,
        on_delete=models.CASCADE,
        related_name="species_result"
    )

    status = models.CharField(max_length=50)
    prediction = models.TextField(blank=True)
    prediction_score = models.FloatField(null=True, blank=True)
    prediction_source = models.CharField(max_length=255, blank=True)

    animals = models.JSONField(default=list, blank=True)
    detections = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"SpeciesNetResult(species_name={self.species_name.file_id}, status={self.status})"
    

class OCRResult(models.Model):
    image = models.OneToOneField(
        ImageRecord,
        on_delete=models.CASCADE,
        related_name="ocr_result"
    )

    status = models.CharField(max_length=50)

    ocr_texts = models.JSONField(default=list, blank=True)

    temperature_f = models.FloatField(
        null=True, 
        blank=True
    )

    capture_date = models.DateField(
        null=True,
        blank=True
    )

    capture_time = models.TimeField(
        null=True,
        blank=True
    )

    capture_datetime = models.DateTimeField(
        null=True,
        blank=True
    )
 
class AppSettings(models.Model):
    box_access_token = models.CharField(blank=True, max_length=255)
    box_refresh_token = models.TextField(blank=True, max_length=255)

    updated_at = models.DateTimeField(auto_now=True)