from django.shortcuts import render
import time
# Create your views here.
import json

from django.http import Http404, JsonResponse

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator
from django.db.models import Q

from .decorators import researcher_required
from .forms import (
    BoxImageMetadataUploadForm,
    SpeciesNetUploadForm,
    OCRUploadForm,
    GalleryFilterForm,
    SpeciesNetEditForm,
    OCREditForm
)

from .models import (
    ImageRecord, 
    SpeciesNetResult, 
    OCRResult, 
    ImportJob, 
    SpeciesDetection,
    SpeciesLabel
)

from .services.box_cache import (
    ensure_cached_image, check_box_token_status
)

from .services.importers import (
    clean_species_label,
    is_human_label,
    update_species_labels,
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


def species_search(request):
    query = request.GET.get("q", "").strip()

    detections = SpeciesDetection.objects.filter(
        source="animal"
    ).exclude(
        label=""
    )

    if not user_is_researcher(request.user):
        detections = detections.exclude(label__icontains="human")

    if query:
        detections = detections.filter(label__icontains=query)

    labels = (
        detections
        .values_list("label", flat=True)
        .distinct()
        .order_by("label")[:20]
    )

    return JsonResponse({
        "results": [
            {
                "id": label,
                "text": label,
            }
            for label in labels
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
    total_start = time.perf_counter()

    t0 = time.perf_counter()

    images = ImageRecord.objects.select_related(
        "species_result",
        "ocr_result",
    ).prefetch_related(
        "species_result__species_detections",
    ).order_by("-created_at")

    print(f"Querying images took {time.perf_counter() - t0:.4f} seconds")

    if not user_is_researcher(request.user):
        images = images.exclude(
            species_result__species_detections__source="animal",
            species_result__species_detections__label__icontains="human",
        )

    t1 = time.perf_counter()

    form = GalleryFilterForm(request.GET)

    if form.is_valid():
        search = form.cleaned_data.get("search")
        species = form.cleaned_data.get("species")
        has_ocr = form.cleaned_data.get("has_ocr")
        has_speciesnet = form.cleaned_data.get("has_speciesnet")
        min_score = form.cleaned_data.get("min_score")
        start_date = form.cleaned_data.get("start_date")
        end_date = form.cleaned_data.get("end_date")

        if search:
            images = images.filter(
                Q(file_name__icontains=search)
                | Q(file_id__icontains=search)
                | Q(path__icontains=search)
                | Q(ocr_result__ocr_texts__icontains=search)
                | Q(species_result__species_detections__label__icontains=search)
            ).distinct()

        if species:
            selected_species = [
                item.strip()
                for item in species.split(",")
                if item.strip()
            ]

            images = images.filter(
                species_result__species_detections__source="animal",
                species_result__species_detections__label__in=selected_species,
            ).distinct()

        if has_ocr:
            images = images.filter(ocr_result__isnull=False)

        if has_speciesnet:
            images = images.filter(species_result__isnull=False)

        if min_score is not None:
            images = images.filter(
                species_result__species_detections__source="animal",
                species_result__species_detections__confidence__gte=min_score,
            ).distinct()

        if start_date:
            images = images.filter(ocr_result__capture_date__gte=start_date)

        if end_date:
            images = images.filter(ocr_result__capture_date__lte=end_date)

    print(f"Filtering images took {time.perf_counter() - t1:.4f} seconds")

    t2 = time.perf_counter()

    paginator = Paginator(images, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    print(f"Pagination took {time.perf_counter() - t2:.4f} seconds")

    t3 = time.perf_counter()

    image_cards = []

    for image in page_obj:
        image_url = image.cached_image.url if image.cached_image else None

        image_cards.append({
            "image": image,
            "image_url": image_url,
        })

    print(f"Creating image cards took {time.perf_counter() - t3:.4f} seconds")
    print(f"Total gallery view took {time.perf_counter() - total_start:.4f} seconds")

    query_params = request.GET.copy()
    query_params.pop("page", None)
    query_string = query_params.urlencode()

    return render(request, "images/gallery.html", {
        "form": form,
        "page_obj": page_obj,
        "image_cards": image_cards,
        "is_researcher": user_is_researcher(request.user),
        "query_string": query_string,
    })


def user_is_researcher(user):
    return (
        user.is_authenticated
        and (
            user.is_superuser
            or user.groups.filter(name="Researcher").exists()
        )
    )

def image_detail(request, file_id):
    image = get_object_or_404(ImageRecord, file_id=file_id)

    if (
        not user_is_researcher(request.user)
        and hasattr(image, "species_result")
        and "human" in image.species_result.prediction.lower()
    ):
        raise Http404("Image not found")

    image_url = ensure_cached_image(image)

    species_result, _ = SpeciesNetResult.objects.get_or_create(image=image)
    ocr_result, _ = OCRResult.objects.get_or_create(image=image)

    can_edit = user_is_researcher(request.user)

    if request.method == "POST":
        if not can_edit:
            return redirect("image_detail", file_id=image.file_id)

        species_form = SpeciesNetEditForm(request.POST, instance=species_result)
        ocr_form = OCREditForm(request.POST, instance=ocr_result)

        if species_form.is_valid() and ocr_form.is_valid():
            species_form.save()
            ocr_form.save()

            messages.success(request, "Image metadata updated.")
            return redirect("image_detail", file_id=image.file_id)

    else:
        species_form = SpeciesNetEditForm(instance=species_result)
        ocr_form = OCREditForm(instance=ocr_result)

    return render(request, "images/image_detail.html", {
        "image": image,
        "image_url": image_url,
        "species_result": species_result,
        "ocr_result": ocr_result,
        "can_edit": can_edit,
        "species_form": species_form,
        "ocr_form": ocr_form,
    })