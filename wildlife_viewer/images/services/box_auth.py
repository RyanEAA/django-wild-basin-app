from boxsdk import OAuth2, Client
from images.models import AppSettings


def store_tokens(access_token, refresh_token):
    app_settings = AppSettings.objects.first()

    if not app_settings:
        return

    app_settings.box_access_token = access_token
    app_settings.box_refresh_token = refresh_token
    app_settings.save(update_fields=[
        "box_access_token",
        "box_refresh_token",
        "updated_at",
    ])


def get_box_client():
    app_settings = AppSettings.objects.first()

    if not app_settings:
        return None

    if not app_settings.box_client_id or not app_settings.box_client_secret:
        return None

    if not app_settings.box_access_token or not app_settings.box_refresh_token:
        return None

    oauth = OAuth2(
        client_id=app_settings.box_client_id,
        client_secret=app_settings.box_client_secret,
        access_token=app_settings.box_access_token,
        refresh_token=app_settings.box_refresh_token,
        store_tokens=store_tokens,
    )

    return Client(oauth)