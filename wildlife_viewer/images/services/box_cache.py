import os

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from images.models import AppSettings
from pgdata.models import ImageRecord

from .box_auth import get_box_client


CACHE_DIRECTORY = "cached_box_images"


def get_box_access_token():
    app_settings = AppSettings.objects.first()

    if not app_settings or not app_settings.box_access_token:
        return None

    return app_settings.box_access_token


def get_cache_filename(image_record):
    """Return the deterministic cache filename for an ImageRecord.

    The Box file_id is unique, so it is used as the filename stem. We retain
    the original extension so browsers and Django can still identify the image
    type correctly.
    """
    file_extension = os.path.splitext(image_record.file_name or "")[1].lower()

    if not file_extension:
        file_extension = ".jpg"

    return f"{image_record.file_id}{file_extension}"


def get_cache_storage_name(image_record):
    return f"{CACHE_DIRECTORY}/{get_cache_filename(image_record)}"


def _cached_file_exists(image_record):
    if not image_record.cached_image:
        return False

    storage = image_record.cached_image.storage
    return storage.exists(image_record.cached_image.name)


def _normalize_existing_cache_name(image_record):
    """Rename an existing cached file to the deterministic file_id name.

    Older cache writes may have names such as ``12345_abcd.jpg`` because
    Django's storage layer avoids overwriting an existing filename. Once an
    image is accessed again, normalize it back to ``12345.jpg``.
    """
    if not image_record.cached_image or not _cached_file_exists(image_record):
        return

    current_name = image_record.cached_image.name
    desired_name = get_cache_storage_name(image_record)

    if current_name == desired_name:
        return

    storage = image_record.cached_image.storage

    with storage.open(current_name, "rb") as source:
        contents = ContentFile(source.read())

    # This operation is called while the ImageRecord row is locked, so another
    # application request cannot create a second filename for the same record.
    if storage.exists(desired_name):
        storage.delete(desired_name)

    saved_name = storage.save(desired_name, contents)

    if current_name != saved_name and storage.exists(current_name):
        storage.delete(current_name)

    image_record.cached_image.name = saved_name
    image_record.cache_last_accessed = timezone.now()
    image_record.save(update_fields=["cached_image", "cache_last_accessed"])


def ensure_cached_image(image_record):
    # Fast path for an existing, correctly referenced cache file. The row lock
    # below also lets us normalize legacy filenames without racing another
    # gallery request for the same image.
    if image_record.cached_image:
        with transaction.atomic(using="postgresql"):
            locked_image = ImageRecord.objects.select_for_update().get(
                pk=image_record.pk
            )

            if _cached_file_exists(locked_image):
                _normalize_existing_cache_name(locked_image)
                locked_image.touch_cache()
                return locked_image.cached_image.url

            # The database points at a file that no longer exists. Clear the
            # stale reference so the Box file can be downloaded again.
            locked_image.cached_image = None
            locked_image.cache_last_accessed = None
            locked_image.save(
                update_fields=["cached_image", "cache_last_accessed"]
            )

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

    # Multiple gallery requests can reach this point at nearly the same time.
    # Lock the row before writing. If another request finished while this one
    # was downloading from Box, reuse that file rather than creating a Django
    # storage suffix such as ``_<random>``.
    with transaction.atomic(using="postgresql"):
        locked_image = ImageRecord.objects.select_for_update().get(
            pk=image_record.pk
        )

        if _cached_file_exists(locked_image):
            _normalize_existing_cache_name(locked_image)
            locked_image.touch_cache()
            return locked_image.cached_image.url

        storage = locked_image.cached_image.storage
        cache_filename = get_cache_filename(locked_image)
        storage_name = get_cache_storage_name(locked_image)

        # A stale/orphaned file can exist even when cached_image is empty. If
        # so, remove it first so Django does not invent a suffixed filename.
        if storage.exists(storage_name):
            storage.delete(storage_name)

        locked_image.cached_image.save(
            cache_filename,
            ContentFile(image_bytes),
            save=False,
        )

        locked_image.cache_last_accessed = timezone.now()
        locked_image.save(
            update_fields=["cached_image", "cache_last_accessed"]
        )

        return locked_image.cached_image.url


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
