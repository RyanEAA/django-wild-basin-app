import json
from ..models import (
    SpeciesLabel, SpeciesNetResult, SpeciesDetection, ImageRecord, OCRResult
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

def update_species_labels(species_result):
    labels = []

    if species_result.prediction:
        labels.append(clean_species_label(species_result.prediction))

    for animal in species_result.animals or []:
        if isinstance(animal, dict):
            labels.append(clean_species_label(animal.get("label", "")))
            labels.append(clean_species_label(animal.get("taxonomy", "")))

    for label in labels:
        if not label:
            continue

        species_label, _ = SpeciesLabel.objects.get_or_create(
            name=label,
            defaults={
                "is_human": is_human_label(label),
            }
        )

        species_label.count = SpeciesNetResult.objects.filter(
            prediction__icontains=label
        ).count()
        species_label.save(update_fields=["count", "is_human"])


def import_ocr_results(uploaded_file):
    created_count = 0
    updated_count = 0
    failed_count = 0

    for raw_line in uploaded_file:
        try:
            line = raw_line.decode("utf-8").strip()

            if not line:
                continue

            item = json.loads(line)

            image, _ = ImageRecord.objects.get_or_create(
                file_id=str(item["file_id"]),
                defaults={
                    "file_name": item.get("file_name", ""),
                    "file_url": item.get("file_url", ""),
                    "path": item.get("path", ""),
                },
            )

            _, created = OCRResult.objects.update_or_create(
                image=image,
                defaults={
                    "status": item.get("status", ""),
                    "ocr_texts": item.get("ocr_texts", []),
                },
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        except Exception:
            failed_count += 1

    return created_count, updated_count, failed_count