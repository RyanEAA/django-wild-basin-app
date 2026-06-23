import os
import requests

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from images.models import AppSettings, ImageRecord

from .box_auth import get_box_client

def get_box_access_token():
    app_settings = AppSettings.objects.first()

    if not app_settings or not app_settings.box_access_token:
        return None

    return app_settings.box_access_token

def ensure_cached_image(image_record):
    if image_record.cached_image:
        image_record.touch_cache()
        return image_record.cached_image.url

    client = get_box_client()

    if not client:
        print("No Box client available.")
        return None

    try:
        box_file = client.file(file_id=image_record.file_id).get()
        image_bytes = box_file.content()

    except Exception as error:
        print("Box download failed:", error)
        return None

    file_extension = os.path.splitext(image_record.file_name)[1] or ".jpg"
    cache_name = f"{image_record.file_id}{file_extension}"

    image_record.cached_image.save(
        cache_name,
        ContentFile(image_bytes),
        save=False,
    )

    image_record.cache_last_accessed = timezone.now()
    image_record.save(update_fields=["cached_image", "cache_last_accessed"])

    return image_record.cached_image.url

def check_box_token_status():
    client = get_box_client()

    if not client:
        return {
            "ok": False,
            "message": "Box credentials are missing.",
        }

    try:
        user = client.user().get()

        return {
            "ok": True,
            "message": f"Box token is working. Connected as {user.name}.",
        }

    except Exception as error:
        return {
            "ok": False,
            "message": f"Box token needs attention: {error}",
        }