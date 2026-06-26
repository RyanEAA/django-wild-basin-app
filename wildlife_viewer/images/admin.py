from django.contrib import admin
from .models import ImageRecord, SpeciesNetResult, OCRResult, ImportJob, AppSettings, SpeciesLabel


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
        "prediction",
        "prediction_score",
        "prediction_source",
    )
    search_fields = ("image__file_name", "image__file_id", "prediction")


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
    list_display = ("name", "is_human", "count", "created_at")
    search_fields = ("name",)
    list_filter = ("is_human",)