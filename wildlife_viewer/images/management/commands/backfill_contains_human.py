from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef, Q

from images.models import ImageRecord, SpeciesDetection


class Command(BaseCommand):
    help = "Backfill ImageRecord.contains_human from SpeciesNet data"

    def handle(self, *args, **options):
        human_detection = SpeciesDetection.objects.filter(
            species_result__image_id=OuterRef("pk"),
            detection_type="human",
        )

        human_images = (
            ImageRecord.objects
            .annotate(
                has_human_detection=Exists(human_detection)
            )
            .filter(
                Q(
                    species_result__prediction__icontains="human"
                )
                | Q(has_human_detection=True)
            )
            .values_list("pk", flat=True)
        )

        self.stdout.write(
            "Resetting contains_human=False..."
        )

        ImageRecord.objects.update(
            contains_human=False
        )

        self.stdout.write(
            "Marking human images..."
        )

        batch_size = 5000
        batch = []

        for image_id in human_images.iterator(
            chunk_size=batch_size
        ):
            batch.append(image_id)

            if len(batch) >= batch_size:
                ImageRecord.objects.filter(
                    pk__in=batch
                ).update(
                    contains_human=True
                )

                batch = []

        if batch:
            ImageRecord.objects.filter(
                pk__in=batch
            ).update(
                contains_human=True
            )

        total = ImageRecord.objects.filter(
            contains_human=True
        ).count()

        self.stdout.write(
            self.style.SUCCESS(
                f"Backfill complete. "
                f"{total} images marked as containing humans."
            )
        )