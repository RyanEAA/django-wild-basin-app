import json
from django import forms
from django.core.exceptions import ValidationError
from django import forms
from .models import (
    ImageRecord, SpeciesNetResult, OCRResult, SpeciesDetection, AppSettings
)
from django.forms import modelformset_factory

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


SPECIESNET_REQUIRED_FIELDS = {
    "status",
    "file_id",
    "file_name",
    "file_url",
    "prediction",
}


def validate_speciesnet_item(item):
    """
    Validate one SpeciesNet JSONL record.

    Returns a list of validation error strings.
    An empty list means the record is valid.
    """
    errors = []

    missing_top_level = sorted(
        field
        for field in SPECIESNET_REQUIRED_FIELDS
        if field not in item
    )

    if missing_top_level:
        errors.append(
            "Missing top-level fields: "
            + ", ".join(missing_top_level)
        )
        return errors

    prediction_entry = item.get("prediction")

    if not isinstance(prediction_entry, dict):
        errors.append(
            "'prediction' must be a JSON object."
        )
        return errors

    required_prediction_fields = {
        "detections",
        "prediction",
        "prediction_score",
        "prediction_source",
    }

    missing_prediction_fields = sorted(
        field
        for field in required_prediction_fields
        if field not in prediction_entry
    )

    if missing_prediction_fields:
        errors.append(
            "Prediction is missing fields: "
            + ", ".join(missing_prediction_fields)
        )

    detections = prediction_entry.get("detections")

    if not isinstance(detections, list):
        errors.append(
            "'prediction.detections' must be a list."
        )

    prediction_score = prediction_entry.get(
        "prediction_score"
    )

    if (
        prediction_score is not None
        and not isinstance(prediction_score, (int, float))
    ):
        errors.append(
            "'prediction.prediction_score' must be numeric."
        )

    return errors


def validate_speciesnet_file(uploaded_file, max_lines=20):
    """
    Validate the first several non-empty records in a SpeciesNet JSONL file.
    """
    errors = []
    checked_lines = 0

    try:
        uploaded_file.seek(0)

        for line_number, raw_line in enumerate(
            uploaded_file,
            start=1,
        ):
            if checked_lines >= max_lines:
                break

            try:
                if isinstance(raw_line, bytes):
                    line = raw_line.decode("utf-8").strip()
                else:
                    line = str(raw_line).strip()

                if not line:
                    continue

                item = json.loads(line)

                if not isinstance(item, dict):
                    errors.append(
                        f"Line {line_number}: "
                        "expected a JSON object."
                    )
                    continue

                item_errors = validate_speciesnet_item(item)

                for error in item_errors:
                    errors.append(
                        f"Line {line_number}: {error}"
                    )

                checked_lines += 1

            except UnicodeDecodeError as error:
                errors.append(
                    f"Line {line_number}: "
                    f"invalid UTF-8: {error}"
                )

            except json.JSONDecodeError as error:
                errors.append(
                    f"Line {line_number}: "
                    f"invalid JSON: {error}"
                )

        if checked_lines == 0 and not errors:
            errors.append("SpeciesNet file is empty.")

        if errors:
            raise ValidationError(errors)

    finally:
        uploaded_file.seek(0)

def validate_ocr_file(file):
    validate_jsonl_first_line(
        file,
        required_fields={
            "file_id",
            "ocr_texts",
        },
        file_label="OCR",
    )

# upload forms for Box metadata, SpeciesNet results, and OCR results

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

    species = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )

    path = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )

    has_ocr = forms.BooleanField(required=False)
    has_speciesnet = forms.BooleanField(required=False)

    min_score = forms.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
    )

    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

class OCREditForm(forms.ModelForm):
    class Meta:
        model = OCRResult
        fields = ["status", "ocr_texts", "temperature_f", "capture_date", "capture_time", "capture_datetime"]

# SpeciesNetEditForm and SpeciesDetectionEditForm are defined below, along with a formset for SpeciesDetection.

DETECTION_LABEL_CHOICES = [
    ("animal", "animal"),
    ("human", "human"),
    ("vehicle", "vehicle"),
]

class SpeciesNetEditForm(forms.ModelForm):
    prediction = forms.CharField(
        required=False,
        widget=forms.Select(
            attrs={
                "class": "species-prediction-autocomplete",
                "data-placeholder": "Search for a species...",
            }
        ),
    )

    class Meta:
        model = SpeciesNetResult
        fields = [
            "status",
            "prediction",
            "prediction_score",
            "prediction_source",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        current_prediction = self.instance.prediction if self.instance.pk else ""

        choices = [("", "")]

        if current_prediction:
            display_prediction = current_prediction.split(";")[-1].strip()

            choices.append(
                (
                    current_prediction,
                    display_prediction or current_prediction,
                )
            )

        self.fields["prediction"].widget.choices = choices

class SpeciesDetectionEditForm(forms.ModelForm):
    prediction = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "species-prediction-autocomplete",
                "autocomplete": "off",
                "placeholder": "Search for a species...",
            }
        ),
    )
    class Meta:
        model = SpeciesDetection
        fields = [
            "detection_type",
            "prediction",
        ]


SpeciesDetectionFormSet = modelformset_factory(
    SpeciesDetection,
    form=SpeciesDetectionEditForm,
    extra=0,
    can_delete=True,
)

class AppSettingsForm(forms.ModelForm):
    class Meta:
        model = AppSettings

        fields = [
            "box_client_id",
            "box_client_secret",
        ]

        widgets = {
            "box_client_id": forms.TextInput(),
            "box_client_secret": forms.PasswordInput(
                render_value=True,
            ),
        }

        help_texts = {
            "box_client_id": (
                "Client ID from the Box Developer Console."
            ),
            "box_client_secret": (
                "Client secret from the Box Developer Console."
            ),
        }

class BoxOAuthCompletionForm(forms.Form):
    redirect_url = forms.URLField(
        label="Redirected localhost URL",
        widget=forms.URLInput(
            attrs={
                "placeholder": (
                    "http://localhost:3000/callback"
                    "?code=...&state=..."
                ),
            }
        ),
        help_text=(
            "After approving access in Box, copy the full "
            "localhost URL from your browser and paste it here."
        ),
    )