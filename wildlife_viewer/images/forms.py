import json

from django import forms
from django.core.exceptions import ValidationError
from django.forms import modelformset_factory

from .models import AppSettings
from pgdata.models import OCRResult, SpeciesDetection, SpeciesNetResult, SpeciesTaxon
from pgdata.parsers import parse_taxon_label


def validate_json_extension(file):
    if not file.name.lower().endswith('.json'):
        raise ValidationError('Expected a .json file.')


def validate_jsonl_extension(file):
    if not file.name.lower().endswith('.jsonl'):
        raise ValidationError('Expected a .jsonl file.')


def validate_box_metadata_file(file):
    # Validate enough of the upload to catch a wrong file without loading a
    # million-row JSON array into memory. The production importer itself is
    # streaming and performs record-level validation.
    try:
        raw = file.read(1024 * 1024)
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8')
        stripped = raw.lstrip()
        if not stripped.startswith('['):
            raise ValidationError('Box metadata file must be a JSON list.')
    except UnicodeDecodeError:
        raise ValidationError('Box metadata must be UTF-8 JSON.')
    finally:
        file.seek(0)


def validate_jsonl_first_line(file, required_fields, file_label):
    try:
        for raw_line in file:
            if isinstance(raw_line, bytes):
                line = raw_line.decode('utf-8').strip()
            else:
                line = str(raw_line).strip()
            if not line:
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValidationError(f'{file_label} records must be JSON objects.')
            missing = required_fields - set(item.keys())
            if missing:
                raise ValidationError(
                    f"{file_label} is missing fields: {', '.join(sorted(missing))}"
                )
            return
        raise ValidationError(f'{file_label} file is empty.')
    except json.JSONDecodeError:
        raise ValidationError(f'Invalid JSONL file for {file_label}.')
    finally:
        file.seek(0)


SPECIESNET_REQUIRED_FIELDS = {'status', 'file_id', 'file_name', 'file_url', 'prediction'}


def validate_speciesnet_file(uploaded_file, max_lines=20):
    checked = 0
    errors = []
    try:
        uploaded_file.seek(0)
        for line_number, raw_line in enumerate(uploaded_file, start=1):
            if checked >= max_lines:
                break
            try:
                line = raw_line.decode('utf-8').strip() if isinstance(raw_line, bytes) else str(raw_line).strip()
                if not line:
                    continue
                item = json.loads(line)
                if not isinstance(item, dict):
                    errors.append(f'Line {line_number}: expected a JSON object.')
                    continue
                missing = SPECIESNET_REQUIRED_FIELDS - set(item.keys())
                if missing:
                    errors.append(f"Line {line_number}: missing fields: {', '.join(sorted(missing))}")
                elif not isinstance(item.get('prediction'), dict):
                    errors.append(f"Line {line_number}: 'prediction' must be a JSON object.")
                checked += 1
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(f'Line {line_number}: invalid JSON/UTF-8: {exc}')
        if checked == 0 and not errors:
            errors.append('SpeciesNet file is empty.')
        if errors:
            raise ValidationError(errors)
    finally:
        uploaded_file.seek(0)


def validate_ocr_file(file):
    validate_jsonl_first_line(file, {'file_id', 'ocr_texts'}, 'OCR')


class BoxImageMetadataUploadForm(forms.Form):
    metadata_file = forms.FileField(
        label='Box image metadata JSON',
        validators=[validate_json_extension, validate_box_metadata_file],
    )


class SpeciesNetUploadForm(forms.Form):
    metadata_file = forms.FileField(
        label='SpeciesNet results JSONL',
        validators=[validate_jsonl_extension, validate_speciesnet_file],
    )


class OCRUploadForm(forms.Form):
    metadata_file = forms.FileField(
        label='PaddleOCR results JSONL',
        validators=[validate_jsonl_extension, validate_ocr_file],
    )


class GalleryFilterForm(forms.Form):
    search = forms.CharField(required=False)
    species = forms.CharField(required=False, widget=forms.HiddenInput())
    path = forms.CharField(required=False, widget=forms.HiddenInput())
    has_ocr = forms.BooleanField(required=False)
    has_speciesnet = forms.BooleanField(required=False)
    min_score = forms.FloatField(required=False, min_value=0.0, max_value=1.0)
    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))


class OCREditForm(forms.ModelForm):
    temperature_f = forms.FloatField(required=False)
    capture_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    capture_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={'type': 'time', 'step': '1'}))

    class Meta:
        model = OCRResult
        fields = ['status', 'ocr_texts']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['temperature_f'].initial = self.instance.image.temperature_f
            self.fields['capture_date'].initial = self.instance.image.capture_date
            self.fields['capture_time'].initial = self.instance.image.capture_time

    def save(self, commit=True):
        result = super().save(commit=commit)
        image = result.image
        image.temperature_f = self.cleaned_data.get('temperature_f')
        image.capture_date = self.cleaned_data.get('capture_date')
        image.capture_time = self.cleaned_data.get('capture_time')
        if commit:
            image.save(update_fields=['temperature_f', 'capture_date', 'capture_time', 'updated_at'])
        return result


class SpeciesNetEditForm(forms.ModelForm):
    class Meta:
        model = SpeciesNetResult
        fields = ['status']


DETECTION_LABEL_CHOICES = [
    ('animal', 'animal'),
    ('human', 'human'),
    ('vehicle', 'vehicle'),
]


class SpeciesDetectionEditForm(forms.ModelForm):
    detection_type = forms.ChoiceField(required=False, choices=DETECTION_LABEL_CHOICES)
    prediction = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'species-prediction-autocomplete',
                'autocomplete': 'off',
                'placeholder': 'Search for a species...',
            }
        ),
    )

    class Meta:
        model = SpeciesDetection
        fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['detection_type'].initial = self.instance.label
            self.fields['prediction'].initial = (
                self.instance.reviewed_taxon.common_name
                if self.instance.reviewed_taxon_id
                else ''
            )

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.label = self.cleaned_data.get('detection_type') or ''
        prediction = (self.cleaned_data.get('prediction') or '').strip()
        if prediction:
            taxon = (
                SpeciesTaxon.objects.using('postgresql')
                .filter(common_name__iexact=prediction)
                .order_by('id')
                .first()
            )
            if taxon is None:
                values = parse_taxon_label(prediction)
                taxon = SpeciesTaxon.objects.using('postgresql').create(**values)
            instance.reviewed_taxon = taxon
            if not instance.reviewed_source:
                instance.reviewed_source = 'researcher'
        else:
            instance.reviewed_taxon = None
            instance.reviewed_score = None
            instance.reviewed_source = ''
        if commit:
            instance.save()
        return instance


SpeciesDetectionFormSet = modelformset_factory(
    SpeciesDetection,
    form=SpeciesDetectionEditForm,
    extra=0,
    can_delete=True,
)


class AppSettingsForm(forms.ModelForm):
    class Meta:
        model = AppSettings
        fields = ['box_client_id', 'box_client_secret']
        widgets = {
            'box_client_id': forms.TextInput(),
            'box_client_secret': forms.PasswordInput(render_value=True),
        }
        help_texts = {
            'box_client_id': 'Client ID from the Box Developer Console.',
            'box_client_secret': 'Client secret from the Box Developer Console.',
        }


class BoxOAuthCompletionForm(forms.Form):
    redirect_url = forms.URLField(
        label='Redirected localhost URL',
        widget=forms.URLInput(
            attrs={'placeholder': 'http://localhost:3000/callback?code=...&state=...'}
        ),
        help_text='After approving access in Box, copy the full localhost URL from your browser and paste it here.',
    )
