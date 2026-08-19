from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.models import Count, Exists, OuterRef, Q

from pgdata.models import (
    CameraPath,
    ImageRecord,
    OCRResult,
    SpeciesClassification,
    SpeciesDetection,
    SpeciesNetResult,
    SpeciesTaxon,
)


class Command(BaseCommand):
    help = "Validate counts, semantics, and core relationships in the parallel PostgreSQL database."

    def add_arguments(self, parser):
        parser.add_argument("--database", default="postgresql")
        parser.add_argument("--sample", type=int, default=5)

    def handle(self, *args, **options):
        alias = options["database"]
        if alias not in connections.databases:
            raise CommandError(f"Database alias '{alias}' is not configured.")

        counts = {
            "ImageRecord": ImageRecord.objects.using(alias).count(),
            "CameraPath": CameraPath.objects.using(alias).count(),
            "SpeciesTaxon": SpeciesTaxon.objects.using(alias).count(),
            "SpeciesNetResult": SpeciesNetResult.objects.using(alias).count(),
            "SpeciesClassification": SpeciesClassification.objects.using(alias).count(),
            "SpeciesDetection": SpeciesDetection.objects.using(alias).count(),
            "OCRResult": OCRResult.objects.using(alias).count(),
        }

        self.stdout.write("PostgreSQL data validation")
        for name, count in counts.items():
            self.stdout.write(f"  {name:24} {count:,}")

        missing_path = ImageRecord.objects.using(alias).filter(camera_path__isnull=True).count()
        missing_top_taxon = SpeciesNetResult.objects.using(alias).filter(
            ~Q(raw_prediction=""), top_taxon__isnull=True
        ).count()
        human_images = ImageRecord.objects.using(alias).filter(contains_human=True).count()
        detection_images = ImageRecord.objects.using(alias).filter(has_detection=True).count()
        classification_mismatches = (
            SpeciesNetResult.objects.using(alias)
            .annotate(classification_count=Count("classifications"))
            .filter(classification_count=0)
            .exclude(raw_data__prediction__classifications={})
            .count()
        )

        human_box = SpeciesDetection.objects.using(alias).filter(
            species_result__image_id=OuterRef("pk"),
            label__iexact="human",
        )
        human_semantic_mismatches = (
            ImageRecord.objects.using(alias)
            .filter(contains_human=True)
            .annotate(has_human_box=Exists(human_box))
            .filter(has_human_box=False)
            .exclude(species_result__top_taxon__is_human=True)
            .count()
        )

        public_eligible = ImageRecord.objects.using(alias).filter(
            contains_human=False,
            species_result__top_taxon__is_filter_visible=True,
        ).count()

        self.stdout.write("")
        self.stdout.write(f"  Images missing CameraPath:       {missing_path:,}")
        self.stdout.write(f"  Results missing parsed top taxon:{missing_top_taxon:,}")
        self.stdout.write(f"  Human images:                    {human_images:,}")
        self.stdout.write(f"  Images with detections:          {detection_images:,}")
        self.stdout.write(f"  Public-eligible top predictions: {public_eligible:,}")
        self.stdout.write(f"  Possible classification issues:  {classification_mismatches:,}")
        self.stdout.write(f"  Human semantic mismatches:       {human_semantic_mismatches:,}")

        self.stdout.write("\nTaxon kinds")
        kind_counts = (
            SpeciesTaxon.objects.using(alias)
            .values("kind")
            .annotate(count=Count("id"))
            .order_by("kind")
        )
        for row in kind_counts:
            self.stdout.write(f"  {row['kind'] or '[blank]':18} {row['count']:,}")

        hidden = list(
            SpeciesTaxon.objects.using(alias)
            .filter(is_filter_visible=False)
            .order_by("kind", "common_name")
            .values_list("kind", "common_name", "raw_label")[:20]
        )
        if hidden:
            self.stdout.write("\nHidden-from-filter taxonomy examples")
            for kind, common_name, raw_label in hidden:
                self.stdout.write(f"  {kind:12} | {common_name:24} | {raw_label[:100]}")

        sample_size = max(0, options["sample"])
        if sample_size:
            self.stdout.write("\nEnd-to-end sample")
            samples = (
                ImageRecord.objects.using(alias)
                .select_related(
                    "camera_path",
                    "species_result__top_taxon",
                    "ocr_result",
                )
                .order_by("id")[:sample_size]
            )
            for image in samples:
                result = getattr(image, "species_result", None)
                taxon = result.top_taxon if result else None
                self.stdout.write(
                    f"  {image.file_id} | path={image.path!r} | "
                    f"top={taxon.common_name if taxon else None!r} | "
                    f"kind={taxon.kind if taxon else None!r} | "
                    f"human={image.contains_human} | detections={image.has_detection} | "
                    f"date={image.capture_date} | temp_f={image.temperature_f}"
                )
