import re
from datetime import datetime
from django.utils import timezone

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

        file_ids = [str(item["file_id"]) for item in items]

        image_lookup = {
            image.file_id: image
            for image in ImageRecord.objects.filter(file_id__in=file_ids)
        }

        new_images = []

        for item in items:
            file_id = str(item["file_id"])

            if file_id not in image_lookup:
                new_images.append(
                    ImageRecord(
                        file_id=file_id,
                        file_name=item.get("file_name", ""),
                        file_url=item.get("file_url", ""),
                    )
                )

        ImageRecord.objects.bulk_create(
            new_images,
            batch_size=batch_size,
            ignore_conflicts=True,
        )

        image_lookup = {
            image.file_id: image
            for image in ImageRecord.objects.filter(file_id__in=file_ids)
        }

        existing_results = {
            result.image.file_id: result
            for result in SpeciesNetResult.objects.filter(
                image__file_id__in=file_ids
            ).select_related("image")
        }

        for result in existing_results.values():
            result.species_detections.all().delete()

        SpeciesNetResult.objects.filter(
            image__file_id__in=file_ids
        ).delete()

        species_results = []

        for item in items:
            file_id = str(item["file_id"])
            image = image_lookup.get(file_id)

            if not image:
                failed += 1
                continue

            species_results.append(
                SpeciesNetResult(
                    image=image,
                    status=item.get("status") or "",
                    prediction=item.get("prediction") or "",
                    prediction_score=item.get("prediction_score"),
                    prediction_source=item.get("prediction_source") or "",
                    animals=item.get("animals") or [],
                    detections=item.get("detections") or [],
                )
            )

            if file_id in existing_results:
                updated += 1
            else:
                created += 1

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

        for item in items:
            file_id = str(item["file_id"])
            species_result = result_lookup.get(file_id)

            if not species_result:
                continue

            for animal in item.get("animals") or []:
                bbox = animal.get("bbox") or []

                detection_rows.append(
                    SpeciesDetection(
                        species_result=species_result,
                        source="animal",
                        label=animal.get("label", "").strip(),
                        confidence=animal.get("score"),
                        **bbox_values(bbox),
                    )
                )

            for detection in item.get("detections") or []:
                bbox = detection.get("bbox") or []

                detection_rows.append(
                    SpeciesDetection(
                        species_result=species_result,
                        source="detection",
                        label=detection.get("label", "").strip(),
                        confidence=detection.get("conf"),
                        **bbox_values(bbox),
                    )
                )

        SpeciesDetection.objects.bulk_create(
            detection_rows,
            batch_size=batch_size,
        )

    for raw_line in uploaded_file:
        try:
            line = raw_line.decode("utf-8").strip()

            if not line:
                continue

            item = json.loads(line)

            if "file_id" not in item:
                failed += 1
                continue

            pending_items.append(item)

            if len(pending_items) >= batch_size:
                flush_batch(pending_items)
                pending_items = []

        except Exception as error:
            print("SpeciesNet parse failed:", error)
            failed += 1

    flush_batch(pending_items)

    return created, updated, failed

## OCR Management
TEMPERATURE_F_PATTERN = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s*°?\s*F\s*$",
    re.IGNORECASE,
)

DATE_PATTERN = re.compile(
    r"^\s*(\d{1,2})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{4})\s*$"
)

TIME_PATTERN = re.compile(
    r"^\s*(\d{1,2})\s*:\s*(\d{1,2})\s*:\s*(\d{1,2})\s*$"
)


def parse_ocr_metadata(ocr_texts):
    """
    Extract Fahrenheit temperature, date, time, and combined datetime
    from a list of OCR strings.

    Returns:
        {
            "temperature_f": float | None,
            "capture_date": date | None,
            "capture_time": time | None,
            "capture_datetime": datetime | None,
        }
    """
    temperature_f = None
    capture_date = None
    capture_time = None

    for raw_text in ocr_texts or []:
        text = str(raw_text).strip()

        if not text:
            continue

        # Example: 66F, 66 F, 66°F
        temperature_match = TEMPERATURE_F_PATTERN.fullmatch(text)

        if temperature_match and temperature_f is None:
            try:
                temperature_f = float(temperature_match.group(1))
            except ValueError:
                pass

        # Example: 10-10-2017 or 10/10/2017
        date_match = DATE_PATTERN.fullmatch(text)

        if date_match and capture_date is None:
            try:
                month = int(date_match.group(1))
                day = int(date_match.group(2))
                year = int(date_match.group(3))

                capture_date = datetime(
                    year=year,
                    month=month,
                    day=day,
                ).date()
            except ValueError:
                pass

        # Handles:
        # 13:41:11
        # 13 : 46 : 41
        # 13 :49 : 46
        # 13:49: 47
        time_match = TIME_PATTERN.fullmatch(text)

        if time_match and capture_time is None:
            try:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2))
                second = int(time_match.group(3))

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

    capture_datetime = None

    if capture_date and capture_time:
        capture_datetime = datetime.combine(
            capture_date,
            capture_time,
        )

        # Use a timezone-aware datetime when USE_TZ=True.
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
    created_count = 0
    updated_count = 0
    failed_count = 0

    batch_size = 200
    pending_items = []

    def flush_batch(items):
        nonlocal created_count, updated_count, failed_count

        if not items:
            return

        # Keep only the last OCR result for each file_id in this batch.
        items_by_file_id = {}

        for item in items:
            file_id = str(item.get("file_id", "")).strip()

            if not file_id:
                failed_count += 1
                continue

            items_by_file_id[file_id] = item

        if not items_by_file_id:
            return

        file_ids = list(items_by_file_id.keys())

        # Find ImageRecords already in the database.
        image_lookup = {
            image.file_id: image
            for image in ImageRecord.objects.filter(
                file_id__in=file_ids
            )
        }

        # Build missing ImageRecords.
        new_images = []

        for file_id, item in items_by_file_id.items():
            if file_id not in image_lookup:
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

        # Reload records so newly created objects have database IDs.
        image_lookup = {
            image.file_id: image
            for image in ImageRecord.objects.filter(
                file_id__in=file_ids
            )
        }

        # Find OCR rows that already exist for this batch.
        existing_results = {
            result.image.file_id: result
            for result in OCRResult.objects.filter(
                image__file_id__in=file_ids
            ).select_related("image")
        }

        results_to_create = []
        results_to_update = []

        for file_id, item in items_by_file_id.items():
            image = image_lookup.get(file_id)

            if image is None:
                failed_count += 1
                continue

            ocr_texts = item.get("ocr_texts") or []
            parsed_metadata = parse_ocr_metadata(ocr_texts)

            existing_result = existing_results.get(file_id)

            if existing_result:
                existing_result.status = item.get("status") or ""
                existing_result.ocr_texts = ocr_texts
                existing_result.temperature_f = parsed_metadata["temperature_f"]
                existing_result.capture_date = parsed_metadata["capture_date"]
                existing_result.capture_time = parsed_metadata["capture_time"]
                existing_result.capture_datetime = parsed_metadata["capture_datetime"]

                results_to_update.append(existing_result)
                updated_count += 1

            else:
                results_to_create.append(
                    OCRResult(
                        image=image,
                        status=item.get("status") or "",
                        ocr_texts=ocr_texts,
                        temperature_f=parsed_metadata["temperature_f"],
                        capture_date=parsed_metadata["capture_date"],
                        capture_time=parsed_metadata["capture_time"],
                        capture_datetime=parsed_metadata["capture_datetime"],
                    )
                )

                created_count += 1

        if results_to_create:
            OCRResult.objects.bulk_create(
                results_to_create,
                batch_size=batch_size,
            )

        if results_to_update:
            OCRResult.objects.bulk_update(
                results_to_update,
                fields=[
                    "status",
                    "ocr_texts",
                    "temperature_f",
                    "capture_date",
                    "capture_time",
                    "capture_datetime",
                ],
                batch_size=batch_size,
            )

    for line_number, raw_line in enumerate(uploaded_file, start=1):
        try:
            line = raw_line.decode("utf-8").strip()

            if not line:
                continue

            item = json.loads(line)

            if "file_id" not in item:
                print(
                    f"OCR import line {line_number} failed: "
                    "missing file_id"
                )
                failed_count += 1
                continue

            pending_items.append(item)

            if len(pending_items) >= batch_size:
                flush_batch(pending_items)
                pending_items = []

        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            print(
                f"OCR import line {line_number} failed: {error}"
            )
            failed_count += 1

        except Exception as error:
            print(
                f"OCR import line {line_number} failed unexpectedly: "
                f"{error}"
            )
            failed_count += 1

    flush_batch(pending_items)

    return created_count, updated_count, failed_count