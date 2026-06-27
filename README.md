# Wildlife Viewer

A Django web application for managing, visualizing, and reviewing wildlife camera trap images stored in Box.

---

# Project Goals

The purpose of this project is to provide researchers and the public with an easy way to browse wildlife camera images and associated metadata without needing to run machine learning models in the cloud.

SpeciesNet and PaddleOCR are executed locally, and only their outputs are uploaded to the web application.

---

# Features Implemented

## Authentication

* Django authentication system
* Researcher user group
* Public users do not require login
* Researchers can upload metadata files
* Researchers can edit image metadata

## Metadata Upload

Researchers can upload:

### Box Image Metadata

JSON file format:

```json
[
{
"file_name":"08050167.JPG",
"file_id":"994317987264",
"path":"...",
"file_url":"...",
"direct_download_url":"...",
"preview_url":"..."
}
]
```

---

### SpeciesNet Results

JSONL format

```json
{
"file_id":"826325301692",
"prediction":"...",
"prediction_score":0.79,
"animals":[],
"detections":[]
}
```

---

### OCR Results

JSONL format

```json
{
"file_id":"666934501763",
"ocr_texts":[
"Bushnell",
"87F31C",
"02-25-2020",
"13:29:01"
]
}
```

---

# Validation

Uploaded files are validated.

Checks include:

* Correct extension

  .json

  .jsonl

* Required fields present

* JSON parsing

* Empty file detection

---

# Import Statistics

**ImportJob model tracks:**

- File type

- Filename

- Researcher

- Records created

- Records updated

- Records failed

- Upload timestamp

**Dashboard displays:**

- Current image count

- SpeciesNet count

- OCR count

- Coverage percentages

- Recent uploads

---

# OCR Parsing

OCR text is automatically parsed.

Example

```python
ocr_texts = [
"Bushnell",
"87F31C",
"02-25-2020",
"13:29:01"
]
```

**Extracted fields**

- temperature_f

- capture_date

- capture_time

- capture_datetime

---

# Box Integration

Images remain stored in Box.

Images are downloaded only when viewed.

Cached images are saved in

*media/cached_box_images/*

**Each image tracks:**

- cache_last_accessed

Box access token stored in

*AppSettings*

Researchers receive dashboard warnings if token expires.

---

# Gallery

**Implemented features:**

- Pagination

- 20 images per page

- Image cards

- Species prediction

- Prediction score

- OCR text

- Capture date

- Path

- Thumbnail

---

# Human Filtering

Public gallery excludes images containing humans.

Example SpeciesNet prediction

*mammalia;primates;hominidae;homo;sapiens;human*

Researchers can still access these images.

---

# Detail View

Users may click image cards.

**Researchers may edit:**

- ImageRecord

- SpeciesNetResult

- OCRResult

- Public users have read-only access.

---

# Database Models

ImageRecord

SpeciesNetResult

OCRResult

ImportJob

AppSettings

---

# Git Notes

Cached images should never be committed.

.gitignore

media/

.venv/

db.sqlite3

**pycache**/

.env

---

# Current Status

**Completed**

- Authentication

- Researcher permissions

- Metadata uploads

- Validation

- Import statistics

- OCR parsing

- Box integration

- Caching

- Gallery

- Filtering

- Image detail page

- Metadata editing

- Human exclusion

**In Progress**

- Box token refresh

- Cache cleanup

- Planned

- Bounding box overlays

- Species correction workflow

- Researcher review status

- Statistics dashboard

- Advanced filtering

- Temperature range

- Camera ID filtering

- Location filtering

- Blank image filtering

- Background image downloads

- Celery

- RQ

- Huey

- Management command

- python manage.py cleanup_cache

- Docker deployment

- PostgreSQL migration

- Public statistics dashboard

---

# Development Roadmap

**Phase 1**

✓ Upload metadata

✓ Browse images

✓ Edit metadata

**Phase 2**

Bounding box visualization

Species correction workflow

Review queue

**Phase 3**

Statistics dashboard

Background downloads

Cache cleanup

**Phase 4**

Production deployment

Docker

PostgreSQL

DigitalOcean

AWS

University server

---

# Running Locally

Install dependencies
```
pip install -r requirements.txt
```

Run migrations
```
python manage.py makemigrations

python manage.py migrate
```

Create superuser
```
python manage.py createsuperuser
```

Go to admin page and 
- Create user
- Create Researcher group
- Assign user to Researcher group

Run server

```
python manage.py runserver
```

Researcher dashboard
```
http://127.0.0.1:8000/researcher/
```

Gallery
```
http://127.0.0.1:8000/
```

Admin
```
http://127.0.0.1:8000/admin/
```
---

# Future Ideas

Export filtered images

CSV export

Image tagging

Favorite images

Timeline visualization

Bulk metadata editing

Image quality scoring

Multiple Box account support
