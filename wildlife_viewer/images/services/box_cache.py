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
    #print("Checking image:", image_record.file_name)

    if image_record.cached_image:
        #print("Already cached:", image_record.cached_image.url)
        image_record.touch_cache()
        return image_record.cached_image.url

    token = get_box_access_token()
    #print("Has token:", bool(token))

    if not token:
        #print("No Box access token found.")
        return None

    if not image_record.direct_download_url:
        #print("No direct_download_url.")
        return None

    headers = {
        "Authorization": f"Bearer {token}"
    }

    response = requests.get(
        image_record.direct_download_url,
        headers=headers,
        timeout=30
    )

    #print("Box response status:", response.status_code)
    #print("Box content type:", response.headers.get("Content-Type"))

    if response.status_code != 200:
        #print("Box error text:", response.text[:500])
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

    #print("Saved cached image:", image_record.cached_image.url)

    return image_record.cached_image.url

def check_box_token_status():
    token = get_box_access_token()

    if not token:
        return {
            "ok": False,
            "message": "No Box access token has been added yet.",
        }

    headers = {
        "Authorization": f"Bearer {token}"
    }

    response = requests.get(
        "https://api.box.com/2.0/users/me",
        headers=headers,
        timeout=10
    )

    if response.status_code == 200:
        return {
            "ok": True,
            "message": "Box token is working.",
        }

    return {
        "ok": False,
        "message": f"Box token may need to be updated. Box returned status {response.status_code}.",
    }