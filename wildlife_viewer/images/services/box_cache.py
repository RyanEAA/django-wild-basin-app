import os
import requests

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from images.models import AppSettings, ImageRecord

def get_box_access_token():
    app_settings = AppSettings.objects.first()

    if not app_settings or not app_settings.box_access_token:
        return None

    return app_settings.box_access_token

def ensure_cached_image(image_record):
    if image_record.cached_image:
        image_record.cache_last_accessed = timezone.now()
        image_record.save(update_fields=["cache_last_accessed"])
        return image_record.cached_image.url
    
    token = get_box_access_token()

    if not token:
        return None
    
    if not image_record.direct_download_url:
        return None
    
    headers = {
        "Authorization": f"Bearer {token}"
    }

    response = requests.get(
        image_record.direct_download_url,
        headers=headers,
        timeout=30
    )

    if response.status_code != 200:
        return None
    
    file_extension = os.path.splitext(image_record.file_name)[1] or ".jpg"
    cache_name = f"{image_record.file_id}{file_extension}"

    image_record.cached_image.save(
        cache_name,
        ContentFile(response.content),
        save=False
    )

    image_record.cache_last_accessed = timezone.now()
    image_record.save(update_fields=["cached_image", "cache_last_accessed"])

    return image_record.cached_image.url
