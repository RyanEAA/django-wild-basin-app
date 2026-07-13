import re
from datetime import datetime
from django.utils import timezone
from django.db import transaction

import json
from ..models import (
    SpeciesNetResult, SpeciesDetection, ImageRecord, OCRResult
)

def import_box_images(uploaded_file):
    data = json.load(uploaded_file)

    created_count = 0
    updated_count = 0
    failed_count = 0

    for item in data:
        try:
            _, created = ImageRecord.objects.update_or_create(
                file_id=str(item["file_id"]),
                defaults={
                    "file_name": item.get("file_name", ""),
                    "path": item.get("path", ""),
                    "file_url": item.get("file_url", ""),
                    "direct_download_url": item.get("direct_download_url", ""),
                    "preview_url": item.get("preview_url", ""),
                },
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        except Exception:
            failed_count += 1

    return created_count, updated_count, failed_count

def clean_species_label(label):
    if not label:
        return ""

    label = str(label).strip()

    if ";" in label:
        parts = [part.strip() for part in label.split(";") if part.strip()]
        if parts:
            return parts[-1]

    return label


def is_human_label(label):
    label = label.lower()
    return "human" in label or "homo sapiens" in label

def bbox_values(bbox):
    return {
        "bbox_x": bbox[0] if len(bbox) > 0 else None,
        "bbox_y": bbox[1] if len(bbox) > 1 else None,
        "bbox_width": bbox[2] if len(bbox) > 2 else None,
        "bbox_height": bbox[3] if len(bbox) > 3 else None,
    }

def chunks(items, size=200):
    for i in range(0, len(items), size):
        yield items[i:i + size]

########## SpeciesNet Imports

def normalize_speciesnet_item(item):
    """
    Normalize one SpeciesNet result.

    Supports:

    1. Current format:
       {
           "prediction": {
               "detections": [...],
               "prediction": "...",
               "prediction_score": 0.9
           }
       }

    2. Older format using `prediction_entry`.

    3. Older flattened fields.
    """
    file_id = item.get("file_id")

    if file_id is None:
        raise ValueError("Missing file_id")

    nested_prediction = item.get("prediction")

    if isinstance(nested_prediction, dict):
        prediction_entry = nested_prediction

    elif isinstance(item.get("prediction_entry"), dict):
        prediction_entry = item["prediction_entry"]

    else:
        prediction_entry = {}

    # The final image-level species prediction.
    if isinstance(nested_prediction, str):
        prediction_label = nested_prediction
    else:
        prediction_label = (
            prediction_entry.get("prediction")
            or prediction_entry.get("label")
            or ""
        )

    prediction_score = item.get("prediction_score")

    if prediction_score is None:
        prediction_score = prediction_entry.get(
            "prediction_score"
        )

    if prediction_score is None:
        prediction_score = prediction_entry.get("score")

    prediction_source = (
        item.get("prediction_source")
        or prediction_entry.get("prediction_source")
        or prediction_entry.get("source")
        or ""
    )

    detections = prediction_entry.get("detections")

    if not isinstance(detections, list):
        detections = item.get("detections")

    if not isinstance(detections, list):
        detections = []

    animals = prediction_entry.get("animals")

    if not isinstance(animals, list):
        animals = item.get("animals")

    if not isinstance(animals, list):
        animals = []

    return {
        "file_id": str(file_id),
        "file_name": item.get("file_name") or "",
        "file_url": item.get("file_url") or "",
        "status": item.get("status") or "",
        "prediction": prediction_label,
        "prediction_score": prediction_score,
        "prediction_source": prediction_source,
        "animals": animals,
        "detections": detections,
    }


def import_speciesnet_results(uploaded_file):
    created = 0
    updated = 0
    failed = 0

    batch_size = 200
    pending_items = []

    def flush_batch(items):
        nonlocal created, updated, failed

        if not items:
            return

        normalized_items = []

        for item in items:
            try:
                normalized_items.append(normalize_speciesnet_item(item))
            except (KeyError, TypeError, ValueError) as error:
                print("SpeciesNet normalization failed:", error)
                failed += 1

        if not normalized_items:
            return

        file_ids = [
            item["file_id"]
            for item in normalized_items
        ]

        with transaction.atomic():
            image_lookup = {
                image.file_id: image
                for image in ImageRecord.objects.filter(
                    file_id__in=file_ids
                )
            }

            new_images = []

            for item in normalized_items:
                file_id = item["file_id"]

                if file_id not in image_lookup:
                    new_images.append(
                        ImageRecord(
                            file_id=file_id,
                            file_name=item["file_name"],
                            file_url=item["file_url"],
                        )
                    )

            if new_images:
                ImageRecord.objects.bulk_create(
                    new_images,
                    batch_size=batch_size,
                    ignore_conflicts=True,
                )

            # Reload because bulk_create(ignore_conflicts=True) does not
            # reliably populate all created objects in image_lookup.
            image_lookup = {
                image.file_id: image
                for image in ImageRecord.objects.filter(
                    file_id__in=file_ids
                )
            }

            existing_file_ids = set(
                SpeciesNetResult.objects.filter(
                    image__file_id__in=file_ids
                ).values_list(
                    "image__file_id",
                    flat=True,
                )
            )

            # Deleting SpeciesNetResult should delete SpeciesDetection rows
            # automatically when the FK uses on_delete=models.CASCADE.
            SpeciesNetResult.objects.filter(
                image__file_id__in=file_ids
            ).delete()

            species_results = []

            for item in normalized_items:
                file_id = item["file_id"]
                image = image_lookup.get(file_id)

                if image is None:
                    failed += 1
                    continue

                species_results.append(
                    SpeciesNetResult(
                        image=image,
                        status=item["status"],
                        prediction=item["prediction"],
                        prediction_score=item["prediction_score"],
                        prediction_source=item["prediction_source"],
                        animals=item["animals"],
                        detections=item["detections"],
                    )
                )

                if file_id in existing_file_ids:
                    updated += 1
                else:
                    created += 1

            if species_results:
                SpeciesNetResult.objects.bulk_create(
                    species_results,
                    batch_size=batch_size,
                )

            result_lookup = {
                result.image.file_id: result
                for result in SpeciesNetResult.objects.filter(
                    image__file_id__in=file_ids
                ).select_related("image")
            }

            detection_rows = []

            for item in normalized_items:
                file_id = item["file_id"]
                species_result = result_lookup.get(file_id)

                if species_result is None:
                    continue

                for animal in item["animals"]:
                    if not isinstance(animal, dict):
                        continue

                    bbox = animal.get("bbox") or []

                    label = (
                        animal.get("label")
                        or animal.get("taxonomy")
                        or animal.get("category")
                        or ""
                    )

                    confidence = animal.get("score")

                    if confidence is None:
                        confidence = animal.get("conf")

                    detection_rows.append(
                        SpeciesDetection(
                            species_result=species_result,
                            source="animal",
                            label=str(label).strip(),
                            confidence=confidence,
                            **bbox_values(bbox),
                        )
                    )

                for detection in item["detections"]:
                    if not isinstance(detection, dict):
                        continue

                    bbox = detection.get("bbox") or []

                    label = (
                        detection.get("label")
                        or detection.get("taxonomy")
                        or detection.get("category")
                        or ""
                    )

                    confidence = detection.get("conf")

                    if confidence is None:
                        confidence = detection.get("score")

                    detection_rows.append(
                        SpeciesDetection(
                            species_result=species_result,
                            source="detection",
                            label=str(label).strip(),
                            confidence=confidence,
                            **bbox_values(bbox),
                        )
                    )

            if detection_rows:
                SpeciesDetection.objects.bulk_create(
                    detection_rows,
                    batch_size=batch_size,
                )

    for raw_line in uploaded_file:
        try:
            if isinstance(raw_line, bytes):
                line = raw_line.decode("utf-8").strip()
            else:
                line = raw_line.strip()

            if not line:
                continue

            item = json.loads(line)

            if not isinstance(item, dict):
                failed += 1
                continue

            if not item.get("file_id"):
                failed += 1
                continue

            pending_items.append(item)

            if len(pending_items) >= batch_size:
                flush_batch(pending_items)
                pending_items = []

        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            print("SpeciesNet parse failed:", error)
            failed += 1

    flush_batch(pending_items)

    return created, updated, failed

## OCR Management
TEMPERATURE_F_PATTERN = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*°?\s*F",
    re.IGNORECASE,
)

DATE_PATTERN = re.compile(
    r"\b(\d{1,2})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{4})\b"
)

TIME_PATTERN = re.compile(
    r"\b(\d{1,2})\s*:\s*(\d{1,2})\s*:\s*(\d{1,2})\b"
)


def parse_capture_datetime(ocr_texts):
    capture_date = None
    capture_time = None

    for raw_text in ocr_texts or []:
        if not isinstance(raw_text, str):
            continue

        text = raw_text.strip()

        if not text:
            continue

        if capture_date is None:
            date_match = DATE_PATTERN.search(text)

            if date_match:
                try:
                    month, day, year = map(int, date_match.groups())

                    capture_date = datetime(
                        year=year,
                        month=month,
                        day=day,
                    ).date()
                except ValueError:
                    pass

        if capture_time is None:
            time_match = TIME_PATTERN.search(text)

            if time_match:
                try:
                    hour, minute, second = map(int, time_match.groups())

                    capture_time = datetime(
                        year=2000,
                        month=1,
                        day=1,
                        hour=hour,
                        minute=minute,
                        second=second,
                    ).time()
                except ValueError:
                    pass

        if capture_date is not None and capture_time is not None:
            break

    return capture_date, capture_time


def parse_ocr_metadata(ocr_texts):
    """
    Extract Fahrenheit temperature, date, time, and combined datetime
    from a list of OCR strings.
    """
    temperature_f = None

    for raw_text in ocr_texts or []:
        if not isinstance(raw_text, str):
            continue

        text = raw_text.strip()

        if not text:
            continue

        if temperature_f is None:
            temperature_match = TEMPERATURE_F_PATTERN.search(text)

            if temperature_match:
                try:
                    temperature_f = float(temperature_match.group(1))
                except ValueError:
                    pass

    capture_date, capture_time = parse_capture_datetime(ocr_texts)

    capture_datetime = None

    if capture_date and capture_time:
        capture_datetime = datetime.combine(
            capture_date,
            capture_time,
        )

        if timezone.is_naive(capture_datetime):
            capture_datetime = timezone.make_aware(
                capture_datetime,
                timezone.get_current_timezone(),
            )

    return {
        "temperature_f": temperature_f,
        "capture_date": capture_date,
        "capture_time": capture_time,
        "capture_datetime": capture_datetime,
    }

def import_ocr_results(uploaded_file):
    """
    Import PaddleOCR JSONL records.

    Each line is expected to look similar to:

    {
        "status": "ok",
        "file_id": "796153070989",
        "file_name": "10100049.JPG",
        "file_url": "https://app.box.com/file/796153070989",
        "path": "/Ayu Project/...",
        "ocr_texts": [
            "Bushnell",
            "84F29C",
            "08-05-2022 09:11:12"
        ]
    }

    Returns:
        tuple[int, int, int]:
            created_count,
            updated_count,
            failed_count
    """
    created = 0
    updated = 0
    failed = 0

    batch_size = 200
    pending_items = []

    def flush_batch(items):
        nonlocal created, updated, failed

        if not items:
            return

        # If the same file_id appears multiple times in one batch,
        # keep the final occurrence.
        items_by_file_id = {}

        for item in items:
            file_id = item.get("file_id")

            if file_id is None:
                failed += 1
                continue

            file_id = str(file_id).strip()

            if not file_id:
                failed += 1
                continue

            items_by_file_id[file_id] = item

        if not items_by_file_id:
            return

        file_ids = list(items_by_file_id.keys())

        with transaction.atomic():
            # -------------------------------------------------------------
            # Find or create the related ImageRecord objects
            # -------------------------------------------------------------

            image_lookup = {
                image.file_id: image
                for image in ImageRecord.objects.filter(
                    file_id__in=file_ids
                )
            }

            new_images = []

            for file_id, item in items_by_file_id.items():
                if file_id in image_lookup:
                    continue

                new_images.append(
                    ImageRecord(
                        file_id=file_id,
                        file_name=item.get("file_name") or "",
                        file_url=item.get("file_url") or "",
                        path=item.get("path") or "",
                    )
                )

            if new_images:
                ImageRecord.objects.bulk_create(
                    new_images,
                    batch_size=batch_size,
                    ignore_conflicts=True,
                )

            # Reload the images so newly created records are included and
            # have database primary keys.
            image_lookup = {
                image.file_id: image
                for image in ImageRecord.objects.filter(
                    file_id__in=file_ids
                )
            }

            # -------------------------------------------------------------
            # Determine which OCR records are updates
            # -------------------------------------------------------------

            existing_file_ids = set(
                OCRResult.objects.filter(
                    image__file_id__in=file_ids
                ).values_list(
                    "image__file_id",
                    flat=True,
                )
            )

            # Because OCRResult is normally OneToOne with ImageRecord,
            # remove the old rows before bulk-creating their replacements.
            OCRResult.objects.filter(
                image__file_id__in=file_ids
            ).delete()

            # -------------------------------------------------------------
            # Parse and create OCR results
            # -------------------------------------------------------------

            ocr_results = []

            for file_id, item in items_by_file_id.items():
                image = image_lookup.get(file_id)

                if image is None:
                    failed += 1
                    continue

                ocr_texts = item.get("ocr_texts") or []

                if not isinstance(ocr_texts, list):
                    failed += 1
                    continue

                metadata = parse_ocr_metadata(ocr_texts)

                ocr_results.append(
                    OCRResult(
                        image=image,
                        status=item.get("status") or "",
                        ocr_texts=ocr_texts,
                        temperature_f=metadata["temperature_f"],
                        capture_date=metadata["capture_date"],
                        capture_time=metadata["capture_time"],
                        capture_datetime=metadata["capture_datetime"],
                    )
                )

                if file_id in existing_file_ids:
                    updated += 1
                else:
                    created += 1

            if ocr_results:
                OCRResult.objects.bulk_create(
                    ocr_results,
                    batch_size=batch_size,
                )

    # ---------------------------------------------------------------------
    # Read the uploaded JSONL file
    # ---------------------------------------------------------------------

    for line_number, raw_line in enumerate(uploaded_file, start=1):
        try:
            if isinstance(raw_line, bytes):
                line = raw_line.decode("utf-8").strip()
            else:
                line = str(raw_line).strip()

            if not line:
                continue

            item = json.loads(line)

            if not isinstance(item, dict):
                print(
                    f"OCR import failed on line {line_number}: "
                    "JSON value is not an object."
                )
                failed += 1
                continue

            if not item.get("file_id"):
                print(
                    f"OCR import failed on line {line_number}: "
                    "missing file_id."
                )
                failed += 1
                continue

            pending_items.append(item)

            if len(pending_items) >= batch_size:
                flush_batch(pending_items)
                pending_items = []

        except UnicodeDecodeError as error:
            print(
                f"OCR decoding failed on line {line_number}: {error}"
            )
            failed += 1

        except json.JSONDecodeError as error:
            print(
                f"OCR JSON parsing failed on line {line_number}: {error}"
            )
            failed += 1

        except Exception as error:
            print(
                f"OCR import failed on line {line_number}: "
                f"{type(error).__name__}: {error}"
            )
            failed += 1

    flush_batch(pending_items)

    return created, updated, failed