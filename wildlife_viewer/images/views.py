from django.shortcuts import render

# Create your views here.
import json

from django.contrib import messages
from django.shortcuts import render, redirect

from .decorators import researcher_required
from .forms import (
    BoxImageMetadataUploadForm,
    SpeciesNetUploadForm,
    OCRUploadForm,
)

from .models import ImageRecord, SpeciesNetResult, OCRResult, ImportJob

@researcher_required
def researcher_dashboard(request):
    return render(request, "images/researcher_dashboard.html")


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
                created, updated, failed = import_box_images(request.FILES["metadata_file"])

            ImportJob.objects.create(
                researcher=request.user,
                file_type="box_images",
                filename=request.FILES["metadata_file"].name,
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
            created, updated, failed = import_speciesnet_results(request.FILES["metadata_file"])

            ImportJob.objects.create(
                researcher=request.user,
                file_type="speciesnet",
                filename=request.FILES["metadata_file"].name,
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
            created, updated, failed = import_ocr_results(request.FILES["metadata_file"])

            ImportJob.objects.create(
                researcher=request.user,
                file_type="ocr",
                filename=request.FILES["metadata_file"].name,
                records_created=created,
                records_updated=updated,
                records_failed=failed,
            )

            messages.success(
                request,
                f"OCR imported. Created: {created}, Updated: {updated}, Failed: {failed}"
            )

            return redirect("upload_metadata")

    return render(request, "images/upload_metadata.html", {
        "box_form": box_form,
        "speciesnet_form": speciesnet_form,
        "ocr_form": ocr_form,
    })

def gallery(request):
    return render(request, "images/gallery.html")

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