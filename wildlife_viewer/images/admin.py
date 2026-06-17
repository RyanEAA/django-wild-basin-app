from django.contrib import admin

from images.models import ImageRecord, OCRResult, SpeciesNetResult, AppSettings

# Register your models here.
admin.site.register(ImageRecord)
admin.site.register(SpeciesNetResult)
admin.site.register(OCRResult)
admin.site.register(AppSettings)

