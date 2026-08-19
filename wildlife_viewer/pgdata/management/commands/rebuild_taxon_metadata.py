from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from pgdata.models import SpeciesTaxon
from pgdata.parsers import classify_taxon


class Command(BaseCommand):
    help = "Recompute SpeciesTaxon kind/visibility flags without changing raw taxonomy labels."

    def add_arguments(self, parser):
        parser.add_argument("--database", default="postgresql")
        parser.add_argument("--batch-size", type=int, default=2000)

    def handle(self, *args, **options):
        alias = options["database"]
        if alias not in connections.databases:
            raise CommandError(f"Database alias '{alias}' is not configured.")

        batch_size = max(1, options["batch_size"])
        rows = []
        processed = 0
        for taxon in SpeciesTaxon.objects.using(alias).all().iterator(chunk_size=batch_size):
            metadata = classify_taxon(
                common_name=taxon.common_name,
                raw_label=taxon.raw_label,
                class_name=taxon.class_name,
                order_name=taxon.order_name,
                family_name=taxon.family_name,
                genus_name=taxon.genus_name,
                species_name=taxon.species_name,
            )
            for field, value in metadata.items():
                setattr(taxon, field, value)
            rows.append(taxon)
            if len(rows) >= batch_size:
                SpeciesTaxon.objects.using(alias).bulk_update(
                    rows,
                    ["kind", "is_filter_visible", "is_human", "is_blank", "is_vehicle"],
                    batch_size=batch_size,
                )
                processed += len(rows)
                self.stdout.write(f"Processed {processed:,} taxa...")
                rows = []

        if rows:
            SpeciesTaxon.objects.using(alias).bulk_update(
                rows,
                ["kind", "is_filter_visible", "is_human", "is_blank", "is_vehicle"],
                batch_size=batch_size,
            )
            processed += len(rows)

        self.stdout.write(self.style.SUCCESS(f"Rebuilt metadata for {processed:,} taxa."))
