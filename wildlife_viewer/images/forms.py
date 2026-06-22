import json
from django import forms
from django.core.exceptions import ValidationError
from django import forms
from .models import ImageRecord, SpeciesNetResult, OCRResult

def validate_json_extension(file):
    if not file.name.lower().endswith(".json"):
        raise ValidationError("Expected a .json file.")


def validate_jsonl_extension(file):
    if not file.name.lower().endswith(".jsonl"):
        raise ValidationError("Expected a .jsonl file.")


def validate_box_metadata_file(file):
    try:
        data = json.load(file)

        if not isinstance(data, list):
            raise ValidationError("Box metadata file must be a JSON list.")

        required_fields = {
            "file_name",
            "file_id",
            "path",
            "file_url",
            "direct_download_url",
            "preview_url",
        }

        for item in data[:5]:
            missing = required_fields - set(item.keys())
            if missing:
                raise ValidationError(
                    f"Box metadata is missing fields: {', '.join(missing)}"
                )

    except json.JSONDecodeError:
        raise ValidationError("Invalid JSON file.")

    finally:
        file.seek(0)


def validate_jsonl_first_line(file, required_fields, file_label):
    try:
        first_line = file.readline()

        if not first_line:
            raise ValidationError(f"{file_label} file is empty.")

        item = json.loads(first_line.decode("utf-8"))

        missing = required_fields - set(item.keys())
        if missing:
            raise ValidationError(
                f"{file_label} is missing fields: {', '.join(missing)}"
            )

    except json.JSONDecodeError:
        raise ValidationError(f"Invalid JSONL file for {file_label}.")

    finally:
        file.seek(0)


def validate_speciesnet_file(file):
    validate_jsonl_first_line(
        file,
        required_fields={
            "file_id",
            "prediction",
            "prediction_score",
            "animals",
            "detections",
        },
        file_label="SpeciesNet",
    )


def validate_ocr_file(file):
    validate_jsonl_first_line(
        file,
        required_fields={
            "file_id",
            "ocr_texts",
        },
        file_label="OCR",
    )


class BoxImageMetadataUploadForm(forms.Form):
    metadata_file = forms.FileField(
        label="Box image metadata JSON",
        validators=[
            validate_json_extension,
            validate_box_metadata_file,
        ],
    )


class SpeciesNetUploadForm(forms.Form):
    metadata_file = forms.FileField(
        label="SpeciesNet results JSONL",
        validators=[
            validate_jsonl_extension,
            validate_speciesnet_file,
        ],
    )

class OCRUploadForm(forms.Form):
    metadata_file = forms.FileField(
        label="PaddleOCR results JSONL",
        validators=[
            validate_jsonl_extension,
            validate_ocr_file,
        ],
    )

class GalleryFilterForm(forms.Form):
    search = forms.CharField(required=False)
    species = forms.CharField(required=False)
    has_ocr = forms.BooleanField(required=False)
    has_speciesnet = forms.BooleanField(required=False)
    min_score = forms.FloatField(required=False, min_value=0.0, max_value=1.0)
    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))


class SpeciesNetEditForm(forms.ModelForm):
    class Meta:
        model = SpeciesNetResult
        fields = ["status", "prediction", "prediction_score", "prediction_source", "animals", "detections"]

class OCREditForm(forms.ModelForm):
    class Meta:
        model = OCRResult
        fields = ["status", "ocr_texts", "temperature_f", "capture_date", "capture_time", "capture_datetime"]