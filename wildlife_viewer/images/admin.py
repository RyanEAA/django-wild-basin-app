from django.contrib import admin

from .models import AppSettings, ImportJob
from pgdata.models import (
    CameraPath,
    ImageRecord,
    OCRResult,
    SpeciesDetection,
    SpeciesNetResult,
    SpeciesTaxon,
)


@admin.register(ImageRecord)
class ImageRecordAdmin(admin.ModelAdmin):
    list_display = ("file_name", "file_id", "path_display", "contains_human", "has_detection")
    search_fields = ("file_name", "file_id", "camera_path__path")
    list_filter = ("contains_human", "has_detection")

    @admin.display(description="Path")
    def path_display(self, obj):
        return obj.path


@admin.register(SpeciesNetResult)
class SpeciesNetResultAdmin(admin.ModelAdmin):
    list_display = ("image", "top_taxon", "prediction_score", "prediction_source", "status")
    search_fields = ("image__file_name", "image__file_id", "top_taxon__common_name")


@admin.register(SpeciesDetection)
class SpeciesDetectionAdmin(admin.ModelAdmin):
    list_display = ("image_file_name", "label", "reviewed_taxon", "confidence", "reviewed_score")
    list_filter = ("label",)
    search_fields = (
        "species_result__image__file_id",
        "species_result__image__file_name",
        "reviewed_taxon__common_name",
    )

    @admin.display(description="Image")
    def image_file_name(self, obj):
        return obj.species_result.image.file_name


@admin.register(OCRResult)
class OCRResultAdmin(admin.ModelAdmin):
    list_display = ("image", "status", "temperature", "capture_date_display", "capture_time_display")
    search_fields = ("image__file_name", "image__file_id")

    @admin.display(description="Temperature F")
    def temperature(self, obj):
        return obj.image.temperature_f

    @admin.display(description="Date")
    def capture_date_display(self, obj):
        return obj.image.capture_date

    @admin.display(description="Time")
    def capture_time_display(self, obj):
        return obj.image.capture_time


@admin.register(SpeciesTaxon)
class SpeciesTaxonAdmin(admin.ModelAdmin):
    list_display = ("common_name", "kind", "is_filter_visible", "is_human")
    list_filter = ("kind", "is_filter_visible", "is_human")
    search_fields = ("common_name", "raw_label")


@admin.register(CameraPath)
class CameraPathAdmin(admin.ModelAdmin):
    list_display = ("path",)
    search_fields = ("path",)


@admin.register(ImportJob)
class ImportJobAdmin(admin.ModelAdmin):
    list_display = (
        "file_type", "filename", "researcher", "records_created",
        "records_updated", "records_failed", "uploaded_at",
    )
    list_filter = ("file_type", "uploaded_at")


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    list_display = ("updated_at",)
