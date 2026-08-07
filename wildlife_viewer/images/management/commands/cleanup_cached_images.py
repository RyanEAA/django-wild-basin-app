from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from images.models import ImageRecord


class Command(BaseCommand):
    help = (
        "Delete cached Box images whose cache_last_accessed timestamp is older "
        "than the configured number of hours."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=float,
            default=24,
            help="Delete cached images not accessed for this many hours (default: 24).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many cached images would be deleted without changing anything.",
        )

    def handle(self, *args, **options):
        hours = options["hours"]
        dry_run = options["dry_run"]

        if hours <= 0:
            raise CommandError("--hours must be greater than 0.")

        cutoff = timezone.now() - timedelta(hours=hours)

        stale_images = ImageRecord.objects.filter(
            ~Q(cached_image=""),
            cached_image__isnull=False,
            cache_last_accessed__isnull=False,
            cache_last_accessed__lt=cutoff,
        ).only("id", "cached_image", "cache_last_accessed")

        stale_count = stale_images.count()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {stale_count} cached image(s) are older than "
                    f"{hours:g} hours and would be deleted."
                )
            )
            return

        deleted_count = 0
        missing_count = 0
        failed_count = 0

        for image in stale_images.iterator(chunk_size=500):
            try:
                storage = image.cached_image.storage
                storage_name = image.cached_image.name

                if storage_name and storage.exists(storage_name):
                    storage.delete(storage_name)
                else:
                    missing_count += 1

                image.cached_image = None
                image.cache_last_accessed = None
                image.save(
                    update_fields=["cached_image", "cache_last_accessed"]
                )
                deleted_count += 1

            except Exception as error:
                failed_count += 1
                self.stderr.write(
                    f"Failed to clean cache for ImageRecord {image.pk}: {error}"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Cache cleanup complete: {deleted_count} record(s) cleared, "
                f"{missing_count} referenced file(s) were already missing, "
                f"{failed_count} failure(s)."
            )
        )
