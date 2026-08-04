import csv

from django.shortcuts import render
import time
# Create your views here.
import json

from django.http import Http404, HttpResponse, JsonResponse

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
    SpeciesDetectionFormSet
)

from .models import (
    ImageRecord, 
    SpeciesNetResult, 
    OCRResult, 
    ImportJob, 
    SpeciesDetection,
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
        .select_related(
            "species_result",
            "ocr_result",
        )
        .order_by("-created_at")
    )

    # Public users must not see images where either the image-level
    # prediction or an individual detection identifies a human.
    if not is_researcher:
        images = images.exclude(
            Q(species_result__prediction__icontains="human")
            | Q(
                species_result__species_detections__detection_type="human"
            )
            | Q(
                species_result__species_detections__prediction__icontains="human"
            )
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
                | Q(path__icontains=search)
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

            # filtering species

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

                images = images.filter(species_query)

        if has_ocr:
            images = images.filter(
                ocr_result__isnull=False
            )

        if has_speciesnet:
            images = images.filter(
                species_result__isnull=False
            )

        # This now filters by the image-level SpeciesNet classification
        # confidence rather than the generic detector-box confidence.
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

    return form, images.distinct(), is_researcher

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
    if not can_edit and species_result:
        prediction_contains_human = (
            "human" in (species_result.prediction or "").lower()
        )

        detection_contains_human = (
            species_result.species_detections.filter(
                Q(detection_type="human")
                | Q(prediction__icontains="human")
            ).exists()
        )

        if prediction_contains_human or detection_contains_human:
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

        if (
            species_form.is_valid()
            and ocr_form.is_valid()
            and detection_formset.is_valid()
        ):
            species_form.save()
            ocr_form.save()
            detection_formset.save()

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