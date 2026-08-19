from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from pgdata.importers import (
    import_box_images,
    import_ocr_results,
    import_speciesnet_results,
)


class Command(BaseCommand):
    help = "Import original Box, SpeciesNet, and OCR files into the parallel PostgreSQL schema."

    def add_arguments(self, parser):
        parser.add_argument("--box", dest="box_path")
        parser.add_argument("--speciesnet", dest="speciesnet_path")
        parser.add_argument("--ocr", dest="ocr_path")
        parser.add_argument("--database", default="postgresql")
        parser.add_argument("--box-batch-size", type=int, default=5000)
        parser.add_argument("--speciesnet-batch-size", type=int, default=2000)
        parser.add_argument("--ocr-batch-size", type=int, default=5000)
        parser.add_argument(
            "--progress-every",
            type=int,
            default=10000,
            help="Print cumulative progress after roughly this many source records.",
        )

    def handle(self, *args, **options):
        alias = options["database"]
        if alias not in connections.databases:
            raise CommandError(
                f"Database alias '{alias}' is not configured. Set POSTGRES_DB and related environment variables."
            )

        supplied = [options.get("box_path"), options.get("speciesnet_path"), options.get("ocr_path")]
        if not any(supplied):
            raise CommandError("Provide at least one of --box, --speciesnet, or --ocr.")

        progress_every = max(1, options["progress_every"])
        last_reported = {}

        def progress(**stats):
            source = stats["source"]
            processed = stats["processed"]
            previous = last_reported.get(source, 0)
            if processed - previous >= progress_every:
                self.stdout.write(
                    f"  {source}: processed={processed:,} "
                    f"created={stats['created']:,} updated={stats['updated']:,} "
                    f"failed={stats['failed']:,}"
                )
                last_reported[source] = processed

        steps = [
            (
                "Box",
                options.get("box_path"),
                import_box_images,
                "rb",
                options["box_batch_size"],
            ),
            (
                "SpeciesNet",
                options.get("speciesnet_path"),
                import_speciesnet_results,
                "rb",
                options["speciesnet_batch_size"],
            ),
            (
                "OCR",
                options.get("ocr_path"),
                import_ocr_results,
                "rb",
                options["ocr_batch_size"],
            ),
        ]

        for label, raw_path, importer, mode, batch_size in steps:
            if not raw_path:
                continue
            path = Path(raw_path).expanduser().resolve()
            if not path.exists():
                raise CommandError(f"{label} file not found: {path}")

            self.stdout.write(f"Importing {label}: {path}")
            self.stdout.write(f"  batch_size={batch_size:,}")
            with path.open(mode) as handle:
                created, updated, failed = importer(
                    handle,
                    using=alias,
                    batch_size=max(1, batch_size),
                    progress=progress,
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f"{label}: created={created:,} updated={updated:,} failed={failed:,}"
                )
            )
