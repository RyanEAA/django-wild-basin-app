from django import forms

class MetadataUploadForm(forms.Form):
    file_type = forms.ChoiceField(
        choices=[
            ("box_images", "Box image metadata JSON"),
            ("speciesnet", "SpeciesNet JSONL"),
            ("ocr", "PaddleOCR JSONL"),
        ]
    )

    metadata_file = forms.FileField()