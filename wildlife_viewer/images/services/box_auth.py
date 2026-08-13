from urllib.parse import urlencode

import requests
from boxsdk import OAuth2, Client

from images.models import AppSettings


from urllib.parse import urlencode, urlparse, parse_qs

BOX_AUTH_URL = "https://account.box.com/api/oauth2/authorize"
BOX_TOKEN_URL = "https://api.box.com/oauth2/token"

BOX_REDIRECT_URI = "http://localhost:3000/callback"


def store_tokens(access_token, refresh_token):
    app_settings = AppSettings.objects.first()

    if not app_settings:
        return

    app_settings.box_access_token = access_token
    app_settings.box_refresh_token = refresh_token

    app_settings.save(
        update_fields=[
            "box_access_token",
            "box_refresh_token",
            "updated_at",
        ]
    )


def get_box_client():
    app_settings = AppSettings.objects.first()

    if not app_settings:
        return None

    if (
        not app_settings.box_client_id
        or not app_settings.box_client_secret
    ):
        return None

    if (
        not app_settings.box_access_token
        or not app_settings.box_refresh_token
    ):
        return None

    oauth = OAuth2(
        client_id=app_settings.box_client_id,
        client_secret=app_settings.box_client_secret,
        access_token=app_settings.box_access_token,
        refresh_token=app_settings.box_refresh_token,
        store_tokens=store_tokens,
    )

    return Client(oauth)

def build_box_authorization_url(
    client_id,
    state,
):
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": BOX_REDIRECT_URI,
        "state": state,
    }

    return f"{BOX_AUTH_URL}?{urlencode(params)}"

def exchange_box_authorization_code(
    *,
    client_id,
    client_secret,
    code,
):
    response = requests.post(
        BOX_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": BOX_REDIRECT_URI,
        },
        timeout=30,
    )

    response.raise_for_status()

    token_data = response.json()

    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")

    if not access_token or not refresh_token:
        raise ValueError(
            "Box did not return both an access token "
            "and refresh token."
        )

    return token_data


def parse_box_redirect_url(value):
    value = value.strip()

    if not value:
        raise ValueError(
            "Paste the redirected localhost URL."
        )

    parsed = urlparse(value)
    params = parse_qs(parsed.query)

    code = params.get("code", [None])[0]
    state = params.get("state", [None])[0]
    error = params.get("error", [None])[0]

    if error:
        raise ValueError(
            f"Box authorization failed: {error}"
        )

    if not code:
        raise ValueError(
            "The pasted URL does not contain a Box authorization code."
        )

    if not state:
        raise ValueError(
            "The pasted URL does not contain an OAuth state value."
        )

    return code, state