import codecs
import json
from itertools import islice

from django.db import transaction

from .models import (
    CameraPath,
    ImageRecord,
    OCRResult,
    SpeciesClassification,
    SpeciesDetection,
    SpeciesNetResult,
    SpeciesTaxon,
)
from .parsers import parse_ocr_metadata, parse_taxon_label


DEFAULT_DB = "postgresql"


def _chunks(iterable, size):
    iterator = iter(iterable)
    while True:
        chunk = list(islice(iterator, size))
        if not chunk:
            return
        yield chunk


def _report(progress, *, source, processed, created, updated, failed):
    if progress is not None:
        progress(
            source=source,
            processed=processed,
            created=created,
            updated=updated,
            failed=failed,
        )


def _json_array_items(uploaded_file, read_size=1024 * 1024):
    """Stream objects from a top-level JSON array without loading it all.

    The Box export is a JSON array rather than JSONL. This incremental decoder
    keeps memory bounded even for million-record exports.
    """
    decoder = json.JSONDecoder()
    utf8_decoder = codecs.getincrementaldecoder("utf-8")()
    buffer = ""
    pos = 0
    eof = False
    started = False

    def read_more():
        nonlocal buffer, pos, eof
        raw = uploaded_file.read(read_size)
        if raw in (b"", ""):
            if not eof:
                buffer = buffer[pos:] + utf8_decoder.decode(b"", final=True)
                pos = 0
            eof = True
            return False
        if isinstance(raw, bytes):
            text = utf8_decoder.decode(raw, final=False)
        else:
            text = str(raw)
        buffer = buffer[pos:] + text
        pos = 0
        return True

    while True:
        while pos >= len(buffer) and not eof:
            read_more()
        while pos < len(buffer) and buffer[pos].isspace():
            pos += 1

        if not started:
            if pos >= len(buffer) and eof:
                raise ValueError("Box metadata is empty.")
            if pos >= len(buffer):
                continue
            if buffer[pos] != "[":
                raise ValueError("Box metadata must be a top-level JSON list.")
            pos += 1
            started = True
            continue

        while True:
            while pos < len(buffer) and (buffer[pos].isspace() or buffer[pos] == ","):
                pos += 1
            if pos < len(buffer):
                break
            if eof:
                raise ValueError("Unexpected end of Box JSON array.")
            read_more()

        if buffer[pos] == "]":
            return

        while True:
            try:
                item, next_pos = decoder.raw_decode(buffer, pos)
                pos = next_pos
                break
            except json.JSONDecodeError:
                if eof:
                    raise
                read_more()

        if isinstance(item, dict):
            yield item


def _jsonl_items(uploaded_file):
    for raw_line in uploaded_file:
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8").strip()
        else:
            line = str(raw_line).strip()
        if not line:
            continue
        item = json.loads(line)
        if isinstance(item, dict):
            yield item


def _ensure_taxa(raw_labels, using=DEFAULT_DB):
    """Ensure taxonomy rows and return a mapping keyed by the supplied label.

    Full SpeciesNet taxonomy strings are authoritative. A simple researcher
    label such as ``coyote`` first reuses an existing taxon with the same
    common name instead of creating a duplicate taxonomic concept.
    """
    supplied = {str(label).strip() for label in raw_labels if str(label).strip()}
    if not supplied:
        return {}

    full_labels = {label for label in supplied if ";" in label}
    simple_labels = supplied - full_labels

    parsed_full = {
        label: parse_taxon_label(label)
        for label in full_labels
    }
    parsed_full = {label: values for label, values in parsed_full.items() if values}

    if parsed_full:
        SpeciesTaxon.objects.using(using).bulk_create(
            [SpeciesTaxon(**values) for values in parsed_full.values()],
            ignore_conflicts=True,
            batch_size=1000,
        )

    mapping = {
        taxon.raw_label: taxon
        for taxon in SpeciesTaxon.objects.using(using).filter(raw_label__in=full_labels)
    }

    # Reuse a normalized SpeciesNet taxon for a simple reviewed common name
    # whenever possible.
    if simple_labels:
        existing_by_common = {}
        for taxon in SpeciesTaxon.objects.using(using).filter(common_name__in=simple_labels).order_by("id"):
            existing_by_common.setdefault(taxon.common_name.casefold(), taxon)

        missing_simple = []
        for label in simple_labels:
            existing = existing_by_common.get(label.casefold())
            if existing is not None:
                mapping[label] = existing
            else:
                values = parse_taxon_label(label)
                if values:
                    missing_simple.append(SpeciesTaxon(**values))

        if missing_simple:
            SpeciesTaxon.objects.using(using).bulk_create(
                missing_simple,
                ignore_conflicts=True,
                batch_size=1000,
            )
            created_simple = {
                taxon.raw_label: taxon
                for taxon in SpeciesTaxon.objects.using(using).filter(raw_label__in=simple_labels)
            }
            mapping.update(created_simple)

    return mapping


def import_box_images(uploaded_file, *, using=DEFAULT_DB, batch_size=5000, progress=None):
    """Import the Box image JSON into the normalized PostgreSQL schema."""
    created = updated = failed = processed = 0

    for batch in _chunks(_json_array_items(uploaded_file), batch_size):
        valid = []
        for item in batch:
            try:
                file_id = str(item["file_id"])
                valid.append((file_id, item))
            except (KeyError, TypeError, ValueError):
                failed += 1

        if not valid:
            continue

        paths = {
            str(item.get("path") or "").strip()
            for _, item in valid
            if str(item.get("path") or "").strip()
        }

        with transaction.atomic(using=using):
            if paths:
                CameraPath.objects.using(using).bulk_create(
                    [CameraPath(path=path) for path in paths],
                    ignore_conflicts=True,
                    batch_size=1000,
                )

            path_lookup = {
                row.path: row
                for row in CameraPath.objects.using(using).filter(path__in=paths)
            }
            file_ids = [file_id for file_id, _ in valid]
            existing = set(
                ImageRecord.objects.using(using)
                .filter(file_id__in=file_ids)
                .values_list("file_id", flat=True)
            )

            rows = []
            for file_id, item in valid:
                path = str(item.get("path") or "").strip()
                rows.append(
                    ImageRecord(
                        file_id=file_id,
                        file_name=item.get("file_name") or "",
                        camera_path=path_lookup.get(path),
                        file_url=item.get("file_url") or "",
                        direct_download_url=item.get("direct_download_url") or "",
                        preview_url=item.get("preview_url") or "",
                    )
                )

            ImageRecord.objects.using(using).bulk_create(
                rows,
                update_conflicts=True,
                unique_fields=["file_id"],
                update_fields=[
                    "file_name",
                    "camera_path",
                    "file_url",
                    "direct_download_url",
                    "preview_url",
                ],
                batch_size=1000,
            )

            created += sum(1 for file_id in file_ids if file_id not in existing)
            updated += sum(1 for file_id in file_ids if file_id in existing)

        processed += len(batch)
        _report(progress, source="Box", processed=processed, created=created, updated=updated, failed=failed)

    return created, updated, failed


def normalize_speciesnet_item(item):
    file_id = item.get("file_id")
    if file_id is None:
        raise ValueError("Missing file_id")

    nested = item.get("prediction")
    if isinstance(nested, dict):
        prediction_entry = nested
    elif isinstance(item.get("prediction_entry"), dict):
        prediction_entry = item["prediction_entry"]
    else:
        prediction_entry = {}

    raw_prediction = (
        prediction_entry.get("prediction")
        or (nested if isinstance(nested, str) else "")
        or item.get("prediction_label")
        or ""
    )
    score = item.get("prediction_score")
    if score is None:
        score = prediction_entry.get("prediction_score")
    if score is None:
        score = prediction_entry.get("score")

    classifications = prediction_entry.get("classifications")
    if not isinstance(classifications, dict):
        classifications = {}

    detections = prediction_entry.get("detections")
    if not isinstance(detections, list):
        detections = item.get("detections")
    if not isinstance(detections, list):
        detections = []

    return {
        "file_id": str(file_id),
        "status": item.get("status") or "",
        "raw_prediction": str(raw_prediction or ""),
        "prediction_score": score,
        "prediction_source": (
            item.get("prediction_source")
            or prediction_entry.get("prediction_source")
            or prediction_entry.get("source")
            or ""
        ),
        "model_version": prediction_entry.get("model_version") or "",
        "classifications": classifications,
        "detections": detections,
        "raw_data": item,
    }


def import_speciesnet_results(uploaded_file, *, using=DEFAULT_DB, batch_size=2000, progress=None):
    """Import SpeciesNet JSONL without inventing detection-to-species links.

    Each batch is atomic, so an interrupted import can be safely rerun. Existing
    SpeciesNet results in a completed batch are replaced together with their
    classifications/detections, preventing stale child rows.
    """
    created = updated = failed = processed = 0

    for raw_batch in _chunks(_jsonl_items(uploaded_file), batch_size):
        normalized = []
        for item in raw_batch:
            try:
                normalized.append(normalize_speciesnet_item(item))
            except (TypeError, ValueError, KeyError, json.JSONDecodeError):
                failed += 1

        if not normalized:
            continue

        file_ids = [item["file_id"] for item in normalized]
        image_lookup = {
            image.file_id: image
            for image in ImageRecord.objects.using(using).filter(file_id__in=file_ids)
        }

        missing = [item for item in normalized if item["file_id"] not in image_lookup]
        failed += len(missing)
        normalized = [item for item in normalized if item["file_id"] in image_lookup]
        if not normalized:
            continue

        file_ids = [item["file_id"] for item in normalized]
        existing = set(
            SpeciesNetResult.objects.using(using)
            .filter(image__file_id__in=file_ids)
            .values_list("image__file_id", flat=True)
        )

        all_taxon_labels = set()
        for item in normalized:
            if item["raw_prediction"]:
                all_taxon_labels.add(item["raw_prediction"])
            classes = item["classifications"].get("classes") or []
            if isinstance(classes, list):
                all_taxon_labels.update(str(label) for label in classes if label)
            for detection in item["detections"]:
                if isinstance(detection, dict) and detection.get("prediction"):
                    all_taxon_labels.add(str(detection["prediction"]))

        with transaction.atomic(using=using):
            taxon_lookup = _ensure_taxa(all_taxon_labels, using=using)

            # Re-imports replace a result atomically; classifications/detections
            # cascade, preventing stale children from surviving updated files.
            SpeciesNetResult.objects.using(using).filter(
                image__file_id__in=file_ids
            ).delete()

            result_rows = []
            human_flags = {}
            detection_flags = {}

            for item in normalized:
                image = image_lookup[item["file_id"]]
                top_taxon = taxon_lookup.get(item["raw_prediction"])

                contains_human = bool(top_taxon and top_taxon.is_human)
                for detection in item["detections"]:
                    if isinstance(detection, dict) and str(
                        detection.get("label") or ""
                    ).strip().casefold() == "human":
                        contains_human = True
                        break

                human_flags[image.pk] = contains_human
                detection_flags[image.pk] = bool(item["detections"])

                result_rows.append(
                    SpeciesNetResult(
                        image=image,
                        status=item["status"],
                        top_taxon=top_taxon,
                        raw_prediction=item["raw_prediction"],
                        prediction_score=item["prediction_score"],
                        prediction_source=item["prediction_source"],
                        model_version=item["model_version"],
                        raw_data=item["raw_data"],
                    )
                )

            SpeciesNetResult.objects.using(using).bulk_create(
                result_rows,
                batch_size=1000,
            )

            result_lookup = {
                result.image.file_id: result
                for result in SpeciesNetResult.objects.using(using)
                .filter(image__file_id__in=file_ids)
                .select_related("image")
            }

            classification_rows = []
            detection_rows = []

            for item in normalized:
                result = result_lookup[item["file_id"]]
                classes = item["classifications"].get("classes") or []
                scores = item["classifications"].get("scores") or []

                if isinstance(classes, list) and isinstance(scores, list):
                    for rank, (raw_label, score) in enumerate(zip(classes, scores), start=1):
                        taxon = taxon_lookup.get(str(raw_label))
                        if taxon is None:
                            continue
                        try:
                            numeric_score = float(score)
                        except (TypeError, ValueError):
                            continue
                        classification_rows.append(
                            SpeciesClassification(
                                species_result=result,
                                taxon=taxon,
                                score=numeric_score,
                                rank=rank,
                            )
                        )

                for index, detection in enumerate(item["detections"]):
                    if not isinstance(detection, dict):
                        continue
                    bbox = detection.get("bbox") or []
                    try:
                        confidence = detection.get("conf")
                        if confidence is None:
                            confidence = detection.get("score")
                        confidence = float(confidence) if confidence is not None else None
                    except (TypeError, ValueError):
                        confidence = None

                    reviewed_label = str(detection.get("prediction") or "").strip()
                    reviewed_taxon = taxon_lookup.get(reviewed_label) if reviewed_label else None
                    reviewed_score = detection.get("prediction_score")
                    try:
                        reviewed_score = float(reviewed_score) if reviewed_score is not None else None
                    except (TypeError, ValueError):
                        reviewed_score = None

                    detection_rows.append(
                        SpeciesDetection(
                            species_result=result,
                            detection_index=index,
                            category=str(detection.get("category") or ""),
                            label=str(detection.get("label") or "").strip(),
                            confidence=confidence,
                            reviewed_taxon=reviewed_taxon,
                            reviewed_score=reviewed_score,
                            reviewed_source=str(detection.get("prediction_source") or ""),
                            bbox_x=bbox[0] if len(bbox) > 0 else None,
                            bbox_y=bbox[1] if len(bbox) > 1 else None,
                            bbox_width=bbox[2] if len(bbox) > 2 else None,
                            bbox_height=bbox[3] if len(bbox) > 3 else None,
                        )
                    )

            if classification_rows:
                SpeciesClassification.objects.using(using).bulk_create(
                    classification_rows, batch_size=2000
                )
            if detection_rows:
                SpeciesDetection.objects.using(using).bulk_create(
                    detection_rows, batch_size=2000
                )

            human_ids = [pk for pk, value in human_flags.items() if value]
            nonhuman_ids = [pk for pk, value in human_flags.items() if not value]
            detection_ids = [pk for pk, value in detection_flags.items() if value]
            nodetection_ids = [pk for pk, value in detection_flags.items() if not value]

            if human_ids:
                ImageRecord.objects.using(using).filter(pk__in=human_ids).update(contains_human=True)
            if nonhuman_ids:
                ImageRecord.objects.using(using).filter(pk__in=nonhuman_ids).update(contains_human=False)
            if detection_ids:
                ImageRecord.objects.using(using).filter(pk__in=detection_ids).update(has_detection=True)
            if nodetection_ids:
                ImageRecord.objects.using(using).filter(pk__in=nodetection_ids).update(has_detection=False)

        created += sum(1 for file_id in file_ids if file_id not in existing)
        updated += sum(1 for file_id in file_ids if file_id in existing)
        processed += len(raw_batch)
        _report(progress, source="SpeciesNet", processed=processed, created=created, updated=updated, failed=failed)

    return created, updated, failed


def import_ocr_results(uploaded_file, *, using=DEFAULT_DB, batch_size=5000, progress=None):
    """Import OCR JSONL and denormalize parsed filter fields onto ImageRecord."""
    created = updated = failed = processed = 0

    for batch in _chunks(_jsonl_items(uploaded_file), batch_size):
        valid = []
        for item in batch:
            file_id = item.get("file_id")
            ocr_texts = item.get("ocr_texts")
            if file_id is None or not isinstance(ocr_texts, list):
                failed += 1
                continue
            valid.append((str(file_id), item))

        if not valid:
            continue

        file_ids = [file_id for file_id, _ in valid]
        image_lookup = {
            image.file_id: image
            for image in ImageRecord.objects.using(using).filter(file_id__in=file_ids)
        }
        existing = set(
            OCRResult.objects.using(using)
            .filter(image__file_id__in=file_ids)
            .values_list("image__file_id", flat=True)
        )

        rows = []
        image_updates = []
        for file_id, item in valid:
            image = image_lookup.get(file_id)
            if image is None:
                failed += 1
                continue

            metadata = parse_ocr_metadata(item.get("ocr_texts") or [])
            image.capture_date = metadata["capture_date"]
            image.capture_time = metadata["capture_time"]
            image.temperature_f = metadata["temperature_f"]
            image_updates.append(image)

            rows.append(
                OCRResult(
                    image=image,
                    status=item.get("status") or "",
                    ocr_texts=item.get("ocr_texts") or [],
                    raw_data=item,
                )
            )

        if not rows:
            continue

        with transaction.atomic(using=using):
            OCRResult.objects.using(using).bulk_create(
                rows,
                update_conflicts=True,
                unique_fields=["image"],
                update_fields=["status", "ocr_texts", "raw_data", "imported_at"],
                batch_size=1000,
            )
            ImageRecord.objects.using(using).bulk_update(
                image_updates,
                ["capture_date", "capture_time", "temperature_f"],
                batch_size=1000,
            )

        imported_ids = {row.image.file_id for row in rows}
        created += sum(1 for file_id in imported_ids if file_id not in existing)
        updated += sum(1 for file_id in imported_ids if file_id in existing)
        processed += len(batch)
        _report(progress, source="OCR", processed=processed, created=created, updated=updated, failed=failed)

    return created, updated, failed
