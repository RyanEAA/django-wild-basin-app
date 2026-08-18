from django.core.management.base import BaseCommand

from images.models import CameraPath, ImageRecord, SpeciesDetection, SpeciesLabel, SpeciesNetResult
from images.services.importers import clean_species_label, is_human_label


class Command(BaseCommand):
    help = "Rebuild species and camera-path autocomplete lookup tables from existing metadata."

    def handle(self, *args, **kwargs):
        self.stdout.write("Rebuilding camera-path lookup...")
        CameraPath.objects.all().delete()

        path_buffer = []
        for path in (
            ImageRecord.objects.exclude(path="")
            .values_list("path", flat=True)
            .distinct()
            .iterator(chunk_size=2000)
        ):
            if path and path.strip():
                path_buffer.append(CameraPath(path=path.strip()))
                if len(path_buffer) >= 1000:
                    CameraPath.objects.bulk_create(path_buffer, ignore_conflicts=True, batch_size=1000)
                    path_buffer = []

        if path_buffer:
            CameraPath.objects.bulk_create(path_buffer, ignore_conflicts=True, batch_size=1000)

        self.stdout.write("Rebuilding species-label lookup...")
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

        self.stdout.write(
            self.style.SUCCESS(
                f"Lookup rebuild complete: {CameraPath.objects.count()} paths, "
                f"{SpeciesLabel.objects.count()} species labels."
            )
        )
