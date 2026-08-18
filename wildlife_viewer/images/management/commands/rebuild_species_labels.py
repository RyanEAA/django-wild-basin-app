from django.core.management.base import BaseCommand

from images.models import SpeciesDetection, SpeciesLabel, SpeciesNetResult
from images.services.importers import clean_species_label, is_human_label


class Command(BaseCommand):
    help = "Rebuild the species autocomplete lookup from current SpeciesNet metadata."

    def handle(self, *args, **kwargs):
        SpeciesLabel.objects.all().delete()
        seen = {}

        sources = [
            SpeciesNetResult.objects.exclude(prediction__isnull=True).exclude(prediction="").values_list("prediction", flat=True).distinct(),
            SpeciesDetection.objects.exclude(prediction__isnull=True).exclude(prediction="").values_list("prediction", flat=True).distinct(),
        ]

        for queryset in sources:
            for raw_label in queryset.iterator(chunk_size=2000):
                label = clean_species_label(raw_label)
                if label:
                    seen[label.casefold()] = label

        SpeciesLabel.objects.bulk_create(
            [SpeciesLabel(name=label, is_human=is_human_label(label)) for label in seen.values()],
            ignore_conflicts=True,
            batch_size=1000,
        )

        self.stdout.write(self.style.SUCCESS(f"Created {len(seen)} species labels."))
