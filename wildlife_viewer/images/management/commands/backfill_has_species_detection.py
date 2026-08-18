from django.core.management.base import BaseCommand

from images.models import ImageRecord


class Command(BaseCommand):
    help = (
        "Backfill ImageRecord.has_species_detection from existing "
        "SpeciesDetection rows. Safe to run repeatedly."
    )

    def handle(self, *args, **options):
        self.stdout.write("Resetting has_species_detection flags...")
        ImageRecord.objects.update(has_species_detection=False)

        self.stdout.write("Marking images that have SpeciesDetection rows...")
        updated = (
            ImageRecord.objects
            .filter(species_result__species_detections__isnull=False)
            .update(has_species_detection=True)
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Backfill complete: {updated:,} images have species detections."
            )
        )
