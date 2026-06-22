from django.shortcuts import render

# Create your views here.
import json

from django.http import Http404

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

from .models import ImageRecord, SpeciesNetResult, OCRResult, ImportJob

from .services.box_cache import ensure_cached_image, check_box_token_status

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

def gallery(request):
    images = ImageRecord.objects.select_related(
        "species_result",
        "ocr_result"
    ).order_by("-created_at")

    # hide images labeled as "human" in Species
    images = images.exclude(
        species_result__prediction__icontains="human"
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

        if search:
            images = images.filter(
                Q(file_name__icontains=search)
                | Q(file_id__icontains=search)
                | Q(path__icontains=search)
                | Q(ocr_result__ocr_texts__icontains=search)
                | Q(species_result__prediction__icontains=search)
            )

        if species:
            images = images.filter(
                Q(species_result__prediction__icontains=species)
                | Q(species_result__animals__icontains=species)
            )

        if has_ocr:
            images = images.filter(ocr_result__isnull=False)

        if has_speciesnet:
            images = images.filter(species_result__isnull=False)

        if min_score is not None:
            images = images.filter(species_result__prediction_score__gte=min_score)

        if start_date:
            images = images.filter(ocr_result__capture_date__gte=start_date)

        if end_date:
            images = images.filter(ocr_result__capture_date__lte=end_date)

    paginator = Paginator(images, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    image_cards = []

    for image in page_obj:
        image_url = ensure_cached_image(image)

        image_cards.append({
            "image": image,
            "image_url": image_url,
        })

    return render(request, "images/gallery.html", {
        "form": form,
        "page_obj": page_obj,
        "image_cards": image_cards,
        "is_researcher": user_is_researcher(request.user),
    })

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

def import_speciesnet_results(uploaded_file):
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
                },
            )

            _, created = SpeciesNetResult.objects.update_or_create(
                image=image,
                defaults={
                    "status": item.get("status", ""),
                    "prediction": item.get("prediction", ""),
                    "prediction_score": item.get("prediction_score"),
                    "prediction_source": item.get("prediction_source", ""),
                    "animals": item.get("animals", []),
                    "detections": item.get("detections", []),
                },
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        except Exception:
            failed_count += 1

    return created_count, updated_count, failed_count

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