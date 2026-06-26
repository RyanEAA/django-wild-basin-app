from django.core.management.base import BaseCommand
from images.models import SpeciesNetResult, SpeciesLabel


def clean_species_label(label):
    if not label:
        return ""

    label = str(label).strip()

    if ";" in label:
        parts = [part.strip() for part in label.split(";") if part.strip()]
        if parts:
            return parts[-1]

    return label


def is_human_label(label):
    label = label.lower()
    return "human" in label or "homo sapiens" in label


class Command(BaseCommand):
    help = "Rebuild species autocomplete labels from SpeciesNet results."

    def handle(self, *args, **kwargs):
        SpeciesLabel.objects.all().delete()

        counts = {}

        for result in SpeciesNetResult.objects.all():
            labels = []

            if result.prediction:
                labels.append(clean_species_label(result.prediction))

            for animal in result.animals or []:
                if isinstance(animal, dict):
                    labels.append(clean_species_label(animal.get("label", "")))
                    labels.append(clean_species_label(animal.get("taxonomy", "")))

            for label in labels:
                if not label:
                    continue

                counts[label] = counts.get(label, 0) + 1

        for label, count in counts.items():
            SpeciesLabel.objects.create(
                name=label,
                count=count,
                is_human=is_human_label(label),
            )

        self.stdout.write(
            self.style.SUCCESS(f"Created {len(counts)} species labels.")
        )