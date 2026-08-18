from django.contrib import admin
from .models import (
    ImageRecord, SpeciesNetResult, OCRResult, ImportJob, AppSettings, SpeciesDetection, SpeciesLabel, CameraPath
)

@admin.register(ImageRecord)
class ImageRecordAdmin(admin.ModelAdmin):
    list_display = (
        "file_name",
        "file_id",
        "path",
        "cache_last_accessed",
    )
    search_fields = ("file_name", "file_id", "path")


@admin.register(SpeciesNetResult)
class SpeciesNetResultAdmin(admin.ModelAdmin):
    list_display = (
        "image",
        "prediction_score",
        "prediction_source",
        "status",
    )
    search_fields = ("image__file_name", "image__file_id", "prediction")

@admin.register(SpeciesDetection)
class SpeciesDetectionAdmin(admin.ModelAdmin):
    list_display = (
        "image_file_name",
        "detection_type",
        "display_prediction",
        "detection_confidence",
        "prediction_score",
        "prediction_source",
    )

    list_filter = (
        "detection_type",
        "prediction_source",
    )

    search_fields = (
        "species_result__image__file_id",
        "species_result__image__file_name",
        "prediction",
    )

    @admin.display(description="Image")
    def image_file_name(self, obj):
        return obj.species_result.image.file_name


@admin.register(OCRResult)
class OCRResultAdmin(admin.ModelAdmin):
    list_display = (
        "image",
        "status",
        "temperature_f",
        "capture_date",
        "capture_time",
    )
    search_fields = ("image__file_name", "image__file_id")


@admin.register(ImportJob)
class ImportJobAdmin(admin.ModelAdmin):
    list_display = (
        "file_type",
        "filename",
        "researcher",
        "records_created",
        "records_updated",
        "records_failed",
        "uploaded_at",
    )
    list_filter = ("file_type", "uploaded_at")


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    list_display = ("updated_at",)


@admin.register(SpeciesLabel)
class SpeciesLabelAdmin(admin.ModelAdmin):
    list_display = ("name", "is_human")
    list_filter = ("is_human",)
    search_fields = ("name",)


@admin.register(CameraPath)
class CameraPathAdmin(admin.ModelAdmin):
    list_display = ("path",)
    search_fields = ("path",)
