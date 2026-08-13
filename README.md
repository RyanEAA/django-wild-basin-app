# Wildlife Viewer

A Django web application for managing, browsing, filtering, exporting,
and reviewing wildlife camera-trap images stored in Box.

The application is designed for the Wild Basin trail-camera workflow.
Large-scale image processing is performed locally with SpeciesNet and
PaddleOCR, while the Django application stores image metadata, model
results, OCR results, review data, and Box references. Images remain in
Box and are cached by the web application only when needed.

------------------------------------------------------------------------

## Project Goals

Wildlife Viewer provides two main experiences:

-   A public-facing wildlife image gallery that does not expose images
    identified as containing humans.
-   A researcher-facing workflow for importing metadata, reviewing
    images and model results, managing Box authorization, and exporting
    data.

The project avoids running SpeciesNet or PaddleOCR on the production web
server. Instead, those tools run locally and their JSON/JSONL outputs
are imported into Django.

------------------------------------------------------------------------

## Current Features

### Public Gallery

The gallery supports:

-   Paginated image browsing.
-   Image thumbnails loaded from Box and cached locally.
-   Species filtering.
-   Path filtering.
-   OCR text search.
-   Date-range filtering.
-   Prediction/confidence filtering.
-   Image detail pages.
-   SpeciesNet prediction information.
-   OCR metadata including capture date, time, and temperature.
-   Public exclusion of images marked as containing humans.
-   CSV export.
-   JSON/JSONL bundle export.

### Researcher Access

Researchers can:

-   Sign in with Django authentication.
-   Access the researcher dashboard.
-   Upload Box image metadata.
-   Upload SpeciesNet JSONL results.
-   Upload PaddleOCR JSONL results.
-   View import statistics and recent import jobs.
-   Review image metadata and model results.
-   Edit supported metadata from the image detail page.
-   Configure Box application credentials.
-   Authorize or reauthorize the application with Box.

Researcher access is controlled through the Django `Researcher` group.

### Human Image Protection

`ImageRecord` contains an indexed `contains_human` flag.

Public gallery requests exclude human images. Authenticated researchers
and administrators can access them for research and review purposes.

A management command is also available for backfilling this flag from
existing SpeciesNet data:

``` bash
python manage.py backfill_contains_human
```

------------------------------------------------------------------------

## Data Import Formats

Researchers upload processed metadata rather than raw model workloads.

### Box Image Metadata

Box image metadata is imported from JSON.

Example:

``` json
[
  {
    "file_name": "08050167.JPG",
    "file_id": "994317987264",
    "path": "/Ayu Project/...",
    "file_url": "https://app.box.com/file/994317987264",
    "direct_download_url": "...",
    "preview_url": "..."
  }
]
```

`file_id` is the primary external identifier used to associate Box,
SpeciesNet, and OCR records.

### SpeciesNet Results

SpeciesNet results are imported from JSONL.

Example:

``` json
{
  "status": "ok",
  "file_id": "826325301692",
  "prediction": "animal;...",
  "prediction_score": 0.79,
  "prediction_source": "...",
  "classifications": {},
  "detections": [],
  "model_version": "..."
}
```

The importer preserves the original image-level SpeciesNet result and
also creates normalized `SpeciesDetection` records for individual
detections when available.

### PaddleOCR Results

OCR results are imported from JSONL.

Example:

``` json
{
  "status": "ok",
  "file_id": "666934501763",
  "ocr_texts": [
    "Bushnell",
    "87F31C",
    "02-25-2020",
    "13:29:01"
  ]
}
```

The OCR importer stores the original text and attempts to extract:

-   Fahrenheit temperature.
-   Capture date.
-   Capture time.
-   Combined capture datetime.

------------------------------------------------------------------------

## Upload Validation and Import Tracking

Uploaded metadata files are validated before or during import.

Validation includes:

-   Expected `.json` or `.jsonl` format.
-   JSON parsing.
-   Required identifiers and fields.
-   Empty-file handling.
-   Per-record failure tracking.

Each upload creates an `ImportJob` containing:

-   File type.
-   Filename.
-   Researcher.
-   Records created.
-   Records updated.
-   Records failed.
-   Error information.
-   Upload timestamp.

The researcher dashboard also displays dataset coverage information and
recent uploads.

------------------------------------------------------------------------

## Box Integration

Images remain stored in Box rather than being copied permanently into
the Django project.

When an image is requested, the application can download and cache it
under:

``` text
media/cached_box_images/
```

`ImageRecord.cache_last_accessed` records cache usage.

### Box Credentials

Box configuration is stored in the singleton-style `AppSettings` record:

-   `box_client_id`
-   `box_client_secret`
-   `box_access_token`
-   `box_refresh_token`

Access and refresh tokens are updated automatically by the Box SDK when
refreshed.

### Box Authorization Flow

The current authorization workflow is designed so a researcher can
authorize the production application even though the Box OAuth redirect
points to localhost.

The Box application must allow this redirect URI:

``` text
http://localhost:3000/callback
```

The workflow is:

1.  Open **Researcher Dashboard → Application Settings**.
2.  Enter the Box Client ID and Client Secret.
3.  Click **Authorize with Box**.
4.  Approve the application in Box.
5.  The browser is redirected to `http://localhost:3000/callback?...`.
6.  The localhost page does not need to load successfully.
7.  Copy the complete redirected URL from the browser address bar.
8.  Return to Wildlife Viewer and paste the URL into the authorization
    form.
9.  Wildlife Viewer extracts the OAuth authorization code, verifies the
    OAuth state, exchanges the code for tokens, and stores the resulting
    access and refresh tokens.

Do not commit Box credentials or tokens to Git.

------------------------------------------------------------------------

## Database Models

### `ImageRecord`

Stores the Box image identity and image-level application metadata,
including:

-   Box file ID.
-   Filename.
-   Box path.
-   Box URLs.
-   Cached image.
-   Human-content flag.
-   Cache access timestamp.

### `SpeciesNetResult`

One-to-one SpeciesNet result for an image.

Stores:

-   Status.
-   Original image-level prediction.
-   Prediction score.
-   Prediction source.
-   Classifications JSON.
-   Detections JSON.
-   Model version.

### `SpeciesDetection`

Normalized per-detection SpeciesNet data.

Stores:

-   Detection type (`animal`, `human`, or `vehicle`).
-   Detection confidence.
-   Bounding box coordinates.
-   Detection-level species prediction.
-   Prediction score and source.

### `OCRResult`

One-to-one OCR result for an image.

Stores:

-   OCR status.
-   Original OCR text.
-   Parsed temperature.
-   Capture date.
-   Capture time.
-   Capture datetime.

### `ImportJob`

Tracks metadata import jobs and their results.

### `AppSettings`

Stores Box application credentials and OAuth tokens.

------------------------------------------------------------------------

---

## Architecture

Wildlife Viewer follows a conventional Django server-rendered architecture, with the `images` application containing most of the domain logic.

At a high level:

```text
                         ┌──────────────────────┐
                         │      Web Browser     │
                         │ Public / Researcher  │
                         └──────────┬───────────┘
                                    │ HTTPS
                                    ▼
                         ┌──────────────────────┐
                         │        Nginx         │
                         │ Reverse proxy/static │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │       Gunicorn       │
                         │      WSGI server     │
                         └──────────┬───────────┘
                                    │
                                    ▼
┌──────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
│       Box        │◄───►│        Django        │◄───►│       SQLite         │
│ Original images │     │    `images` app      │     │ Metadata/results     │
└──────────────────┘     └──────────┬───────────┘     └──────────────────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   Local media cache  │
                         │ cached_box_images/   │
                         └──────────────────────┘
```

SpeciesNet and PaddleOCR are intentionally outside the production request path:

```text
Box Images
    │
    ▼
Local Processing Application
    ├── Box metadata JSON
    ├── SpeciesNet JSONL
    └── PaddleOCR JSONL
             │
             ▼
      Researcher Upload
             │
             ▼
        Django Importers
             │
             ▼
        Django Database
```

This architecture keeps computationally expensive ML inference off the production server.

### Application Layers

The main responsibilities are separated roughly as follows:

```text
HTTP / Templates
    │
    ▼
images/views.py
    │
    ├── Gallery and filtering
    ├── Detail/researcher editing
    ├── Metadata uploads
    ├── CSV/JSON exports
    ├── AJAX search/cache endpoints
    └── Box OAuth workflow
    │
    ▼
Forms / Services
    │
    ├── images/forms.py
    ├── services/importers.py
    ├── services/box_auth.py
    ├── services/box_cache.py
    └── utils/ocr_parser.py
    │
    ▼
Django ORM
    │
    ▼
Models / SQLite
```

The application is primarily server-rendered Django rather than a separate JavaScript frontend/API architecture. JavaScript/AJAX is used where useful, such as species/path autocomplete and asynchronous image caching.

---

## Data Model Architecture

The central database entity is `ImageRecord`. SpeciesNet and OCR results attach to an image using one-to-one relationships, while normalized SpeciesNet detections use a one-to-many relationship.

```text
                         ┌─────────────────┐
                         │   ImageRecord   │
                         │─────────────────│
                         │ file_id         │
                         │ file_name       │
                         │ path            │
                         │ Box URLs        │
                         │ cached_image    │
                         │ contains_human  │
                         └───────┬─────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
                  1 │                       1 │
                    ▼                         ▼
        ┌────────────────────┐     ┌─────────────────┐
        │ SpeciesNetResult   │     │    OCRResult    │
        │────────────────────│     │─────────────────│
        │ prediction         │     │ ocr_texts       │
        │ prediction_score   │     │ temperature_f   │
        │ classifications    │     │ capture_date    │
        │ detections JSON    │     │ capture_time    │
        │ model_version      │     │ capture_datetime│
        └─────────┬──────────┘     └─────────────────┘
                  │
                1 │
                  │
                  ▼ *
        ┌────────────────────┐
        │ SpeciesDetection   │
        │────────────────────│
        │ detection_type     │
        │ confidence         │
        │ bounding box       │
        │ prediction         │
        │ prediction_score   │
        └────────────────────┘
```

Two additional models support application operations:

```text
ImportJob
    └── Records who uploaded a metadata file and the
        created / updated / failed counts for that import.

AppSettings
    └── Stores the Box Client ID, Client Secret,
        access token, and refresh token.
```

### Model Relationships

- `ImageRecord → SpeciesNetResult`: one-to-one through `species_result`.
- `ImageRecord → OCRResult`: one-to-one through `ocr_result`.
- `SpeciesNetResult → SpeciesDetection`: one-to-many through `species_detections`.
- `ImportJob → User`: optional many-to-one researcher relationship.
- `AppSettings`: application-wide Box configuration record.

### Why Both `SpeciesNetResult` and `SpeciesDetection` Exist

`SpeciesNetResult` preserves SpeciesNet's original image-level output, including the original prediction and JSON structures.

`SpeciesDetection` provides normalized database rows for individual detections. This makes it easier to query detection type, confidence, species, and bounding-box information without repeatedly parsing the original SpeciesNet JSON.

`ImageRecord.contains_human` is also stored directly and indexed so public gallery filtering does not need to parse SpeciesNet output for every request.

---

## Major Application Workflows

### 1. Metadata Processing and Import

The primary data-ingestion workflow begins outside Django.

```text
Camera-trap images in Box
          │
          ▼
Local Image Processor
          │
          ├── Collect Box file metadata
          ├── Run SpeciesNet
          └── Run PaddleOCR
          │
          ▼
JSON / JSONL result files
          │
          ▼
Researcher Dashboard
          │
          ▼
Upload + Validation
          │
          ▼
services/importers.py
          │
          ├── import_box_images()
          ├── import_speciesnet_results()
          └── import_ocr_results()
          │
          ▼
Database
```

Each upload creates an `ImportJob`, allowing the application to report how many records were created, updated, or failed.

The common `file_id` supplied by Box is what connects independently generated metadata files to the same `ImageRecord`.

### 2. SpeciesNet Import Workflow

```text
SpeciesNet JSONL
      │
      ▼
normalize_speciesnet_item()
      │
      ├── Normalize image-level prediction
      ├── Preserve classifications
      ├── Preserve original detections JSON
      └── Normalize individual detections
      │
      ▼
SpeciesNetResult
      │
      ├── SpeciesDetection rows
      └── Update ImageRecord.contains_human
```

The importer uses batched database operations where appropriate because the dataset can contain a very large number of records.

### 3. OCR Import Workflow

```text
PaddleOCR JSONL
       │
       ▼
OCR text list
       │
       ▼
OCR parsing
       │
       ├── Temperature
       ├── Date
       ├── Time
       └── Combined datetime
       │
       ▼
OCRResult
```

The original OCR text is retained even when structured metadata cannot be extracted.

### 4. Public Gallery Request

```text
GET /
 │
 ▼
_build_gallery_queryset()
 │
 ├── Apply public human exclusion
 ├── Apply search/filter parameters
 ├── Apply species filters
 ├── Apply path filters
 ├── Apply OCR/date filters
 └── Apply confidence filters
 │
 ▼
Pagination
 │
 ▼
Gallery template
 │
 ▼
Browser
```

For public users, `contains_human=True` records are excluded before results are displayed.

Researchers can access the full research dataset.

### 5. Image Cache Workflow

The database stores Box references rather than permanent copies of every source image.

```text
Gallery needs image
       │
       ▼
cache_image_ajax()
       │
       ▼
ensure_cached_image()
       │
       ├── Cached already? ── Yes ──► Return local media URL
       │
       └── No
             │
             ▼
        Get Box client
             │
             ▼
        Download from Box
             │
             ▼
 media/cached_box_images/
             │
             ▼
 Update cached_image +
 cache_last_accessed
```

This prevents the web server from needing a permanent local copy of the full Box image collection.

Old cached files can be removed using the cache-cleanup management command.

### 6. Box Authentication Workflow

Box uses OAuth 2.0. The current production-friendly workflow handles the fact that the configured Box callback is a localhost URL.

```text
Researcher
    │
    ▼
Application Settings
    │
    ▼
Authorize with Box
    │
    ▼
build_box_authorization_url()
    │
    ▼
Box authorization page
    │
    ▼
Researcher approves access
    │
    ▼
http://localhost:3000/callback?code=...&state=...
    │
    ▼
Researcher copies complete URL
    │
    ▼
Wildlife Viewer completion form
    │
    ▼
parse_box_redirect_url()
    │
    ├── Validate OAuth state
    └── Extract authorization code
    │
    ▼
exchange_box_authorization_code()
    │
    ▼
Access + refresh tokens
    │
    ▼
AppSettings
```

Once authorized, `get_box_client()` creates an authenticated Box SDK client. Refreshed access and refresh tokens are persisted through `store_tokens()`.

### 7. Researcher Editing Workflow

```text
Researcher opens image detail
          │
          ▼
Permission check
          │
          ▼
ImageRecord + SpeciesNetResult + OCRResult
          │
          ▼
Researcher edits supported fields
          │
          ▼
Django ModelForms
          │
          ▼
Validation
          │
          ▼
Database update
```

Public users receive a read-only detail view.

### 8. Export Workflow

```text
Current database
      │
      ├───────────────┐
      ▼               ▼
 /export/csv/    /export/json/
      │               │
      ▼               ▼
Tabular export    JSON bundle
```

Exports allow researchers to move processed metadata back out of the web application for analysis, backup, or other research workflows.

---

## Request and Permission Architecture

There are three practical access levels:

```text
Public User
    └── Gallery/detail access with human images excluded.

Researcher
    ├── Full research gallery access
    ├── Metadata upload
    ├── Metadata editing
    ├── Application settings
    └── Box authorization

Administrator
    └── Django Admin + researcher capabilities
```

Researcher-only views use the project's `researcher_required` decorator.

The public/researcher distinction is especially important because camera-trap datasets can contain people. The `contains_human` database flag provides a fast application-level boundary between public wildlife data and researcher-only records.

---

## Deployment Architecture

Production uses Nginx in front of Gunicorn:

```text
                         Internet
                            │
                            ▼
                    ┌───────────────┐
                    │     Nginx     │
                    │ 80 / 443      │
                    └───────┬───────┘
                            │
                  proxy to 127.0.0.1
                            │
                            ▼
                    ┌───────────────┐
                    │   Gunicorn    │
                    │   :8000       │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │    Django     │
                    └───┬───────┬───┘
                        │       │
             ┌──────────┘       └───────────┐
             ▼                              ▼
      ┌─────────────┐                ┌─────────────┐
      │   SQLite    │                │     Box     │
      │  Metadata   │                │   Images    │
      └─────────────┘                └─────────────┘
```

systemd manages the Gunicorn process, while Nginx handles the public HTTP/HTTPS connection and reverse proxying.

Django static files are collected into `staticfiles/`, while Box image cache files are stored under `media/`.


## Project Structure

The current application is centered around the `images` Django app.

``` text
.
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── images/
│   ├── management/
│   │   └── commands/
│   │       ├── backfill_contains_human.py
│   │       ├── cleanup_cached_images.py
│   │       └── rebuild_species_labels.py
│   ├── services/
│   │   ├── box_auth.py
│   │   ├── box_cache.py
│   │   └── importers.py
│   ├── static/
│   ├── templates/
│   ├── utils/
│   │   └── ocr_parser.py
│   ├── admin.py
│   ├── decorators.py
│   ├── forms.py
│   ├── models.py
│   ├── tests.py
│   ├── urls.py
│   └── views.py
├── manage.py
├── requirements.txt
└── README.md
```

### Important Modules

-   `images/services/importers.py` --- Box, SpeciesNet, and OCR import
    logic.
-   `images/services/box_auth.py` --- Box OAuth, token storage, and Box
    client creation.
-   `images/services/box_cache.py` --- Box image download/cache
    handling.
-   `images/utils/ocr_parser.py` --- OCR date, time, and temperature
    parsing.
-   `images/views.py` --- Gallery, exports, researcher tools, Box
    authorization, and application pages.
-   `images/forms.py` --- Gallery filters, upload forms, metadata
    editing, and application settings.

------------------------------------------------------------------------

## Running Locally

### 1. Clone the Repository

``` bash
git clone <repository-url>
cd <repository-directory>
```

Run the remaining commands from the directory containing `manage.py`.

### 2. Create a Virtual Environment

macOS/Linux:

``` bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

``` powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

``` bash
pip install -r requirements.txt
```

The project currently uses Django 6.0.6 along with the Box SDK, Pillow,
python-dotenv, and related dependencies.

### 4. Run Database Migrations

``` bash
python manage.py migrate
```

Use `makemigrations` only after changing Django models:

``` bash
python manage.py makemigrations
python manage.py migrate
```

### 5. Create an Administrator

``` bash
python manage.py createsuperuser
```

### 6. Start the Development Server

`manage.py` defaults to:

``` text
config.settings.development
```

Start Django with:

``` bash
python manage.py runserver
```

Then open:

``` text
Gallery:              http://127.0.0.1:8000/
Researcher Dashboard: http://127.0.0.1:8000/researcher/
Django Admin:         http://127.0.0.1:8000/admin/
```

### 7. Create a Researcher Account

In Django Admin:

1.  Create or select a user.
2.  Create the `Researcher` group if it does not already exist.
3.  Add the user to the `Researcher` group.

The user can then access researcher-only pages.

------------------------------------------------------------------------

## Settings

Settings are split by environment.

### Development

``` text
config.settings.development
```

Development currently uses:

-   `DEBUG = True`
-   SQLite.
-   A development-only Django secret key.

### Production

``` text
config.settings.production
```

Production loads secrets and host configuration from environment
variables.

Required variables include:

``` env
DJANGO_SECRET_KEY=replace-with-a-secure-secret
DJANGO_ALLOWED_HOSTS=example.org,www.example.org
DJANGO_CSRF_TRUSTED_ORIGINS=https://example.org,https://www.example.org
DJANGO_SETTINGS_MODULE=config.settings.production
```

`DJANGO_CSRF_TRUSTED_ORIGINS` values must include the URL scheme.

Production enables secure cookies, HTTPS redirect behavior, proxy SSL
handling, HSTS, content-type protection, and clickjacking protection.

Run the production security check with:

``` bash
python manage.py check --deploy --settings=config.settings.production
```

------------------------------------------------------------------------

## Production Deployment

The current production architecture uses:

``` text
Internet
   ↓
Nginx
   ↓
Gunicorn
   ↓
Django
   ↓
SQLite + Box
```

The deployed application currently uses:

-   Ubuntu 24.04 LTS.
-   Nginx as the public reverse proxy.
-   Gunicorn bound to `127.0.0.1:8000`.
-   systemd to manage Gunicorn.
-   UFW firewall rules.
-   Django production settings loaded from `.env`.
-   `collectstatic` output under `staticfiles/`.
-   Media/cache data under `media/`.

### Typical Deployment Update

After pushing changes to the server:

``` bash
cd /home/django/apps/django-wild-basin-app
git pull
source .venv/bin/activate
cd wildlife_viewer
pip install -r ../requirements.txt
python manage.py migrate --settings=config.settings.production
python manage.py collectstatic --noinput --settings=config.settings.production
python manage.py check --deploy --settings=config.settings.production
```

Then restart Gunicorn:

``` bash
sudo systemctl restart wildlife-viewer
sudo systemctl status wildlife-viewer
```

Reload Nginx if its configuration changed:

``` bash
sudo nginx -t
sudo systemctl reload nginx
```

A normal Django code-only deployment generally requires a Gunicorn
restart. Nginx only needs to be reloaded when its configuration changes.

> The exact repository and `requirements.txt` paths may differ depending
> on the server checkout. Verify paths before running deployment
> commands.

### Database Backups

The production database is currently SQLite and can be large. Back it up
before migrations or other potentially destructive database operations.

Do not commit the production database to Git.

------------------------------------------------------------------------

## Management Commands

### Rebuild Species Data

``` bash
python manage.py rebuild_species_labels
```

Rebuilds species-related normalized data used by the application.

### Backfill Human Flags

``` bash
python manage.py backfill_contains_human
```

Updates `ImageRecord.contains_human` from existing SpeciesNet
information.

### Clean Cached Images

``` bash
python manage.py cleanup_cached_images
```

Removes old cached Box images according to the command's configured
cleanup behavior.

For production, add:

``` bash
--settings=config.settings.production
```

when the environment does not already set `DJANGO_SETTINGS_MODULE`.

------------------------------------------------------------------------

## Exports

The application provides two export paths:

``` text
/export/csv/
/export/json/
```

The CSV export is intended for tabular analysis.

The JSON export produces a bundle representing the application's image
metadata and associated SpeciesNet/OCR data in machine-readable form.

------------------------------------------------------------------------

## Git and Sensitive Files

Do not commit generated, local, cached, database, or secret files.

A typical `.gitignore` should include at least:

``` gitignore
.venv/
.env
db.sqlite3
db.sqlite3.*
media/
staticfiles/
__pycache__/
*.py[cod]
.DS_Store
```

Box Client Secrets, OAuth access tokens, OAuth refresh tokens, Django
production secrets, and production database backups must remain outside
version control.

------------------------------------------------------------------------

## Testing

Run the Django test suite with:

``` bash
python manage.py test
```

For production-specific checks:

``` bash
python manage.py check --deploy --settings=config.settings.production
```

------------------------------------------------------------------------

## Current Status

### Implemented

-   Django authentication.
-   Researcher permissions.
-   Public/researcher access separation.
-   Box metadata import.
-   SpeciesNet JSONL import.
-   PaddleOCR JSONL import.
-   Upload validation.
-   Import statistics.
-   OCR parsing.
-   Box OAuth authorization.
-   Box access/refresh token storage and refresh support.
-   On-demand Box image caching.
-   Gallery pagination and filtering.
-   Species search/autocomplete.
-   Path search/autocomplete.
-   Image detail view.
-   Researcher metadata editing.
-   Human-image exclusion for public users.
-   Human flag backfill command.
-   Cache cleanup command.
-   Species rebuild command.
-   CSV export.
-   JSON/JSONL export bundle.
-   Split development/production settings.
-   Gunicorn + Nginx production deployment.

### Next Improvements

Potential future work includes:

-   Bounding-box overlays in the image viewer.
-   A more complete species-correction/research review workflow.
-   Researcher review status and annotations.
-   Expanded statistics dashboards.
-   Additional camera/location filters.
-   Image quality and blank-image filtering.
-   Background cache/download jobs.
-   PostgreSQL migration if SQLite becomes a bottleneck.
-   Additional automated tests around imports, exports, permissions, and
    Box authorization.

------------------------------------------------------------------------

## Workflow Summary

The intended end-to-end workflow is:

``` text
Box camera-trap images
        ↓
Local processing application
        ├── Box image metadata JSON
        ├── SpeciesNet JSONL
        └── PaddleOCR JSONL
        ↓
Researcher upload
        ↓
Wildlife Viewer database
        ↓
Public gallery / researcher review / exports
```

This keeps expensive machine-learning inference off the production web
server while allowing researchers and the public to work with the
resulting wildlife dataset through a centralized web interface.
