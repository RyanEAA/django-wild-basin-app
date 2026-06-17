from django.shortcuts import render

# Create your views here.
import json

from django.contrib import messages
from django.shortcuts import render, redirect

from .decorators import researcher_required
from .forms import MetadataUploadForm
from .models import ImageRecord, SpeciesNetResult, OCRResult

@researcher_required
def researcher_dashboard(request):
    return render(request, "images/researcher_dashboard.html")


@researcher_required
def upload_metadata(request):
    if request.method == "POST":
        form = MetadataUploadForm(request.POST, request.FILES)
        
        if form.is_valid():
            file_type = form.cleaned_data["file_type"]
            uploaded_file = request.FILES["metadata_file"]

            if file_type == "box_images":
                import_box_images(uploaded_file)

            elif file_type == "speciesnet":
                import_speciesnet_results(uploaded_file)

            elif file_type == "ocr":
                import_ocr_results(uploaded_file)

            messages.success(request, "Metadata uploaded successfully!")
            return redirect("researcher_dashboard")
        
        else:
            form = MetadataUploadForm()

        return render(request, "images/upload_metadata.html", {"form": form})
    
def gallery(request):
    return render(request, "images/gallery.html")

def import_box_images(uploaded_file):
    data = json.load(uploaded_file)

    for item in data:
        ImageRecord.objects.update_or_create(
            file_id=item["file_id"],
            defaults={
                "field_name": item["field_name"],
                "path": item["path"],
                "file_url": item["file_url"],
                "direct_download_url": item["direct_download_url"],
                "preview_url": item["preview_url"]
            }
        )

def import_speciesnet_results(uploaded_file):
    for raw_line in uploaded_file:
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

        SpeciesNetResult.objects.update_or_create(
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

def import_ocr_results(uploaded_file):
    for raw_line in uploaded_file:
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

        OCRResult.objects.update_or_create(
            image=image,
            defaults={
                "status": item.get("status", ""),
                "ocr_texts": item.get("ocr_texts", []),
            },
        )