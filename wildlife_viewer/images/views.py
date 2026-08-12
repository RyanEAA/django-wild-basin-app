import csv
import tempfile
import zipfile

from django.shortcuts import render
import time
# Create your views here.
import json

from django.http import FileResponse, Http404, HttpResponse, JsonResponse

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.urls import reverse

from .decorators import researcher_required
from .forms import (
    BoxImageMetadataUploadForm,
    SpeciesNetUploadForm,
    OCRUploadForm,
    GalleryFilterForm,
    SpeciesNetEditForm,
    OCREditForm,
    SpeciesDetectionFormSet,
    AppSettingsForm
)

from .models import (
    ImageRecord, 
    SpeciesNetResult, 
    OCRResult, 
    ImportJob, 
    SpeciesDetection,
    AppSettings,
    )

from .services.box_cache import (
    ensure_cached_image, check_box_token_status
)

from .services.importers import (
    import_box_images,
    import_speciesnet_results,
    import_ocr_results,
)

def get_species_label_from_prediction(prediction):
    if not prediction:
        return ""
    
    parts = prediction.split(";")

    # SpeciesNet format often ends with readable label
    if parts:
        return parts[-1].strip()
    return prediction.strip()

from django.http import JsonResponse


def clean_species_label(label):
    if not label:
        return ""

    label = str(label).strip()

    if ";" in label:
        parts = [part.strip() for part in label.split(";") if part.strip()]
        if parts:
            return parts[-1]

    return label


def _format_capture_datetime(ocr_result):
    capture_date = ""
    capture_time = ""

    if not ocr_result:
        return capture_date, capture_time

    if ocr_result.capture_datetime:
        capture_date = ocr_result.capture_datetime.date().isoformat()
        capture_time = ocr_result.capture_datetime.strftime("%H:%M:%S")
        return capture_date, capture_time

    if ocr_result.capture_date:
        capture_date = ocr_result.capture_date.isoformat()

    if ocr_result.capture_time:
        capture_time = ocr_result.capture_time.strftime("%H:%M:%S")

    return capture_date, capture_time


def _write_json_line(file_handle, payload):
    file_handle.write(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    file_handle.write(b"\n")


def export_json_bundle(request):
    """Export gallery records in formats accepted by the existing importers."""
    _, images, _ = _build_gallery_queryset(request)

    # TemporaryFile automatically spills to disk and is removed when the
    # FileResponse finishes closing it. This avoids holding a large export in RAM.
    export_file = tempfile.TemporaryFile()

    with zipfile.ZipFile(
        export_file,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        allowZip64=True,
    ) as archive:
        # Python's zipfile module permits only one writable member handle at a
        # time. Fully close each entry before opening the next one.
        with archive.open("image_urls.json", mode="w") as image_file:
            image_file.write(b"[\n")
            first_image = True

            for image in images.iterator(chunk_size=1000):
                image_payload = {
                    "file_id": image.file_id,
                    "file_name": image.file_name,
                    "path": image.path,
                    "file_url": image.file_url,
                    "direct_download_url": image.direct_download_url,
                    "preview_url": image.preview_url,
                }

                if not first_image:
                    image_file.write(b",\n")

                image_file.write(
                    json.dumps(
                        image_payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                first_image = False

            image_file.write(b"\n]\n")

        with archive.open("speciesnet_predictions.jsonl", mode="w") as species_file:
            for image in images.iterator(chunk_size=1000):
                species_result = getattr(image, "species_result", None)

                if species_result is not None:
                    # Normal SpeciesNet records keep the original raw detection
                    # payload. Once a researcher edits a per-detection prediction,
                    # status is changed to ``updated`` and the editable
                    # SpeciesDetection rows become the authoritative export data.
                    if species_result.status == "updated":
                        exported_detections = []

                        for detection in species_result.species_detections.all().order_by("id"):
                            exported_detection = {
                                "label": detection.detection_type or "",
                                "conf": detection.detection_confidence,
                                "bbox": [
                                    detection.bbox_x,
                                    detection.bbox_y,
                                    detection.bbox_width,
                                    detection.bbox_height,
                                ],
                                # These fields are Wild Basin round-trip metadata.
                                # The updated importer recognizes them while the
                                # original SpeciesNet fields remain intact.
                                "prediction": detection.prediction or "",
                                "prediction_score": detection.prediction_score,
                                "prediction_source": detection.prediction_source or "",
                            }
                            exported_detections.append(exported_detection)
                    else:
                        exported_detections = species_result.detections or []

                    _write_json_line(species_file, {
                        "status": species_result.status or "",
                        "file_id": image.file_id,
                        "file_name": image.file_name,
                        "file_url": image.file_url,
                        "prediction": {
                            "prediction": species_result.prediction or "",
                            "prediction_score": species_result.prediction_score,
                            "prediction_source": species_result.prediction_source or "",
                            "classifications": species_result.classifications or {},
                            "detections": exported_detections,
                            "model_version": species_result.model_version or "",
                        },
                    })

        with archive.open("ocr_results.jsonl", mode="w") as ocr_file:
            for image in images.iterator(chunk_size=1000):
                ocr_result = getattr(image, "ocr_result", None)

                if ocr_result is not None:
                    _write_json_line(ocr_file, {
                        "status": ocr_result.status or "",
                        "file_id": image.file_id,
                        "file_name": image.file_name,
                        "file_url": image.file_url,
                        "path": image.path,
                        # Parsed date/time/temperature fields are intentionally
                        # omitted because the OCR importer regenerates them from
                        # the original OCR strings.
                        "ocr_texts": ocr_result.ocr_texts or [],
                    })

    export_file.seek(0)

    return FileResponse(
        export_file,
        as_attachment=True,
        filename="wild_basin_json_export.zip",
        content_type="application/zip",
    )


def export_csv(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        'attachment; filename="wild_basin_image_export.csv"'
    )

    writer = csv.writer(response)
    writer.writerow([
        "image_name",
        "box_url",
        "path",
        "prediction",
        "detection",
        "date",
        "time",
    ])

    _, images, _ = _build_gallery_queryset(request)
    images = images.prefetch_related(
        Prefetch(
            "species_result__species_detections",
            queryset=SpeciesDetection.objects.order_by("id"),
        )
    )

    for image in images:
        species_result = getattr(image, "species_result", None)
        ocr_result = getattr(image, "ocr_result", None)
        capture_date, capture_time = _format_capture_datetime(ocr_result)
        prediction = clean_species_label(species_result.prediction) if species_result else ""

        detections = []

        if species_result:
            detections = [
                detection.display_prediction
                for detection in species_result.species_detections.all()
                if detection.display_prediction
            ]

        if not detections:
            detections = [""]

        for detection_label in detections:
            writer.writerow([
                image.file_name,
                image.file_url,
                image.path,
                prediction,
                detection_label,
                capture_date,
                capture_time,
            ])

    return response


def _build_gallery_queryset(request):
    is_researcher = user_is_researcher(request.user)

    images = (
        ImageRecord.objects
        .order_by("-created_at")
    )

    if not is_researcher:
        images = images.filter(
            contains_human=False
        )

    form = GalleryFilterForm(request.GET)

    if form.is_valid():
        search = form.cleaned_data.get("search")
        species = form.cleaned_data.get("species")
        has_ocr = form.cleaned_data.get("has_ocr")
        has_speciesnet = form.cleaned_data.get("has_speciesnet")
        min_score = form.cleaned_data.get("min_score")
        start_date = form.cleaned_data.get("start_date")
        end_date = form.cleaned_data.get("end_date")
        path = form.cleaned_data.get("path")

        if search:
            images = images.filter(
                Q(file_name__icontains=search)
                | Q(file_id__icontains=search)
                | Q(path__icontains=search)
                | Q(ocr_result__ocr_texts__icontains=search)
                | Q(species_result__prediction__icontains=search)
                | Q(
                    species_result__species_detections__prediction__icontains=search
                )
                | Q(
                    species_result__species_detections__detection_type__icontains=search
                )
            )

        if path:
            images = images.filter(
                path__icontains=path
            )

        if species:
            selected_species = [
                item.strip()
                for item in species.split(",")
                if item.strip()
            ]

            if selected_species:
                species_query = Q()

                for selected_label in selected_species:
                    species_query |= Q(
                        species_result__prediction__icontains=selected_label
                    )

                    species_query |= Q(
                        species_result__species_detections__prediction__icontains=
                        selected_label
                    )

                images = images.filter(
                    species_query
                )

        if has_ocr:
            images = images.filter(
                ocr_result__isnull=False
            )

        if has_speciesnet:
            images = images.filter(
                species_result__isnull=False
            )

        if min_score is not None:
            images = images.filter(
                species_result__prediction_score__gte=min_score
            )

        if start_date:
            images = images.filter(
                ocr_result__capture_date__gte=start_date
            )

        if end_date:
            images = images.filter(
                ocr_result__capture_date__lte=end_date
            )

    return (
        form,
        images.distinct(),
        is_researcher,
    )

def path_search(request):
    query = request.GET.get("q", "").strip()

    matching_paths = ImageRecord.objects.exclude(
        path__isnull=True
    ).exclude(
        path=""
    )

    if query:
        matching_paths = matching_paths.filter(
            path__icontains=query
        )

    matching_paths = (
        matching_paths
        .values_list("path", flat=True)
        .distinct()
        .order_by("path")[:20]
    )

    return JsonResponse({
        "results": [
            {
                "id": image_path,
                "text": image_path,
            }
            for image_path in matching_paths
        ]
    })

def species_search(request):
    query = request.GET.get("q", "").strip()
    is_researcher = user_is_researcher(request.user)

    # Original image-level SpeciesNet predictions.
    image_predictions = SpeciesNetResult.objects.exclude(
        prediction__isnull=True,
    ).exclude(
        prediction="",
    )

    # Editable per-detection predictions.
    detection_predictions = SpeciesDetection.objects.exclude(
        prediction__isnull=True,
    ).exclude(
        prediction="",
    )

    # Public users should never receive human as a suggestion.
    if not is_researcher:
        image_predictions = image_predictions.exclude(
            prediction__icontains="human",
        )

        detection_predictions = detection_predictions.exclude(
            prediction__icontains="human",
        )

    if query:
        image_predictions = image_predictions.filter(
            prediction__icontains=query,
        )

        detection_predictions = detection_predictions.filter(
            prediction__icontains=query,
        )

    image_prediction_values = list(
        image_predictions
        .values_list("prediction", flat=True)
        .distinct()
        .order_by("prediction")[:200]
    )

    detection_prediction_values = list(
        detection_predictions
        .values_list("prediction", flat=True)
        .distinct()
        .order_by("prediction")[:200]
    )

    labels = []
    seen_labels = set()

    for prediction in (
        image_prediction_values
        + detection_prediction_values
    ):
        label = clean_species_label(prediction)

        if not label:
            continue

        normalized_label = label.casefold()

        if normalized_label in seen_labels:
            continue

        seen_labels.add(normalized_label)
        labels.append(label)

    labels.sort(key=str.casefold)

    return JsonResponse({
        "results": [
            {
                "id": label,
                "text": label,
            }
            for label in labels[:20]
        ]
    })

@researcher_required
def researcher_dashboard(request):
    box_token_status = check_box_token_status()

    return render(request, "images/researcher_dashboard.html", {
        "box_token_status": box_token_status,
    })

@researcher_required
def app_settings(request):
    settings_obj = AppSettings.objects.order_by("pk").first()
    if settings_obj is None:
        settings_obj = AppSettings.objects.create()

    if request.method == "POST":
        form = AppSettingsForm(request.POST, instance=settings_obj)

        if form.is_valid():
            form.save()
            messages.success(request, "Application settings updated.")
            return redirect("app_settings")
    else:
        form = AppSettingsForm(instance=settings_obj)

    return render(request, "images/app_settings.html", {
        "form": form,
        "app_settings": settings_obj,
    })


@researcher_required
def upload_metadata(request):
    box_form = BoxImageMetadataUploadForm()
    speciesnet_form = SpeciesNetUploadForm()
    ocr_form = OCRUploadForm()

    if request.method == "POST":
        upload_type = request.POST.get("upload_type")

        if upload_type == "box_images":
            box_form = BoxImageMetadataUploadForm(request.POST, request.FILES)

            if box_form.is_valid():
                uploaded_file = request.FILES["metadata_file"]
                created, updated, failed = import_box_images(uploaded_file)

                ImportJob.objects.create(
                    researcher=request.user,
                    file_type="box_images",
                    filename=uploaded_file.name,
                    records_created=created,
                    records_updated=updated,
                    records_failed=failed,
                )

                messages.success(
                    request,
                    f"Box metadata imported. Created: {created}, Updated: {updated}, Failed: {failed}"
                )

                return redirect("upload_metadata")

        elif upload_type == "speciesnet":
            speciesnet_form = SpeciesNetUploadForm(request.POST, request.FILES)

            if speciesnet_form.is_valid():
                uploaded_file = request.FILES["metadata_file"]
                created, updated, failed = import_speciesnet_results(uploaded_file)

                ImportJob.objects.create(
                    researcher=request.user,
                    file_type="speciesnet",
                    filename=uploaded_file.name,
                    records_created=created,
                    records_updated=updated,
                    records_failed=failed,
                )

                messages.success(
                    request,
                    f"SpeciesNet imported. Created: {created}, Updated: {updated}, Failed: {failed}"
                )

                return redirect("upload_metadata")

        elif upload_type == "ocr":
            ocr_form = OCRUploadForm(request.POST, request.FILES)

            if ocr_form.is_valid():
                uploaded_file = request.FILES["metadata_file"]
                created, updated, failed = import_ocr_results(uploaded_file)

                ImportJob.objects.create(
                    researcher=request.user,
                    file_type="ocr",
                    filename=uploaded_file.name,
                    records_created=created,
                    records_updated=updated,
                    records_failed=failed,
                )

                messages.success(
                    request,
                    f"OCR imported. Created: {created}, Updated: {updated}, Failed: {failed}"
                )

                return redirect("upload_metadata")

    box_count = ImageRecord.objects.count()
    speciesnet_count = SpeciesNetResult.objects.count()
    ocr_count = OCRResult.objects.count()
    import_job_count = ImportJob.objects.count()
    recent_jobs = ImportJob.objects.order_by("-uploaded_at")[:5]

    if box_count > 0:
        speciesnet_coverage = round((speciesnet_count / box_count) * 100, 2)
        ocr_coverage = round((ocr_count / box_count) * 100, 2)
    else:
        speciesnet_coverage = 0
        ocr_coverage = 0

    return render(request, "images/upload_metadata.html", {
        "box_form": box_form,
        "speciesnet_form": speciesnet_form,
        "ocr_form": ocr_form,

        "box_count": box_count,
        "speciesnet_count": speciesnet_count,
        "ocr_count": ocr_count,
        "import_job_count": import_job_count,
        "recent_jobs": recent_jobs,
        "speciesnet_coverage": speciesnet_coverage,
        "ocr_coverage": ocr_coverage,
    })

def cache_image_ajax(request, file_id):
    image = get_object_or_404(ImageRecord, file_id=file_id)

    image_url = ensure_cached_image(image)

    if image_url:
        return JsonResponse({
            "ok": True,
            "image_url": image_url,
        })
    
    return JsonResponse({
        "ok": False,
        "image_url": None,
    })

def gallery(request):
    form, images, is_researcher = _build_gallery_queryset(request)

    paginator = Paginator(images, 20)
    page_obj = paginator.get_page(
        request.GET.get("page")
    )

    image_cards = []

    for image in page_obj:
        image_url = (
            image.cached_image.url
            if image.cached_image
            else None
        )

        image_cards.append({
            "image": image,
            "image_url": image_url,
        })

    query_params = request.GET.copy()
    query_params.pop("page", None)
    query_string = query_params.urlencode()

    return render(
        request,
        "images/gallery.html",
        {
            "form": form,
            "page_obj": page_obj,
            "image_cards": image_cards,
            "is_researcher": is_researcher,
            "query_string": query_string,
        },
    )

def user_is_researcher(user):
    return (
        user.is_authenticated
        and (
            user.is_superuser
            or user.groups.filter(name="Researcher").exists()
        )
    )

def image_detail(request, file_id):
    back_url = (
        request.GET.get("next")
        or request.POST.get("next")
        or reverse("gallery")
    )

    image = get_object_or_404(
        ImageRecord.objects.prefetch_related(
            "species_result__species_detections"
        ),
        file_id=file_id,
    )

    can_edit = user_is_researcher(request.user)

    species_result = SpeciesNetResult.objects.filter(
        image=image
    ).first()

    ocr_result = OCRResult.objects.filter(
        image=image
    ).first()

    # Public users must not see images containing humans.
    # Public users must not see images containing humans.
    if not can_edit and image.contains_human:
        raise Http404("Image not found")

    image_url = ensure_cached_image(image)

    if species_result:
        detection_queryset = (
            species_result.species_detections
            .all()
            .order_by("id")
        )
    else:
        detection_queryset = SpeciesDetection.objects.none()

    bbox_overlays = []
    for detection in detection_queryset:
        if None in (
            detection.bbox_x,
            detection.bbox_y,
            detection.bbox_width,
            detection.bbox_height,
        ):
            continue

        bbox_overlays.append({
            "id": detection.id,
            "left": max(0.0, min(100.0, detection.bbox_x * 100)),
            "top": max(0.0, min(100.0, detection.bbox_y * 100)),
            "width": max(0.0, min(100.0, detection.bbox_width * 100)),
            "height": max(0.0, min(100.0, detection.bbox_height * 100)),
            "prediction": detection.display_prediction or detection.get_detection_type_display() or "Detection",
            "confidence": detection.prediction_score if detection.prediction_score is not None else detection.detection_confidence,
        })

    if request.method == "POST":
        if not can_edit:
            return redirect(
                "image_detail",
                file_id=image.file_id,
            )

        # Only create records when a researcher submits edits.
        if species_result is None:
            species_result = SpeciesNetResult.objects.create(
                image=image
            )

        if ocr_result is None:
            ocr_result = OCRResult.objects.create(
                image=image
            )

        species_post_data = request.POST.copy()

        species_form = SpeciesNetEditForm(
            species_post_data,
            instance=species_result,
        )

        ocr_form = OCREditForm(
            request.POST,
            instance=ocr_result,
        )

        detection_formset = SpeciesDetectionFormSet(
            request.POST,
            queryset=detection_queryset,
            prefix="detections",
        )

        # SpeciesNetEditForm is not rendered on this page, so saving the
        # bound form here would replace the existing image-level prediction,
        # score, and source with blank POST values. Preserve the original
        # SpeciesNet result and only save the fields that the researcher can
        # actually edit on this page.
        if (
            ocr_form.is_valid()
            and detection_formset.is_valid()
        ):
            species_detections_changed = detection_formset.has_changed()

            ocr_form.save()
            detection_formset.save()

            if species_detections_changed:
                species_result.status = "updated"
                species_result.save(
                    update_fields=["status"]
                )

                prediction_contains_human = (
                    "human"
                    in (
                        species_result.prediction
                        or ""
                    ).lower()
                )

                detection_contains_human = (
                    species_result.species_detections
                    .filter(
                        detection_type="human"
                    )
                    .exists()
                )

                image.contains_human = (
                    prediction_contains_human
                    or detection_contains_human
                )

                image.save(
                    update_fields=[
                        "contains_human"
                    ]
                )

            messages.success(
                request,
                "Image metadata updated.",
            )

            detail_url = reverse(
                "image_detail",
                args=[image.file_id],
            )

            return redirect(
                f"{detail_url}?next={back_url}"
            )

    else:
        species_form = SpeciesNetEditForm(
            instance=species_result
        )

        ocr_form = OCREditForm(
            instance=ocr_result
        )

        detection_formset = SpeciesDetectionFormSet(
            queryset=detection_queryset,
            prefix="detections",
        )

    return render(
        request,
        "images/image_detail.html",
        {
            "image": image,
            "image_url": image_url,
            "species_result": species_result,
            "ocr_result": ocr_result,
            "detections": detection_queryset,
            "bbox_overlays": bbox_overlays,
            "can_edit": can_edit,
            "species_form": species_form,
            "ocr_form": ocr_form,
            "detection_formset": detection_formset,
            "back_url": back_url,
        },
    )


def about(request):
    return render(request, "images/about.html")


def research(request):
    return render(request, "images/research.html")


def contact(request):
    return render(request, "images/contact.html")