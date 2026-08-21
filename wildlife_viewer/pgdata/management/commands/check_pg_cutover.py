from django.core.management.base import BaseCommand, CommandError

from pgdata.models import ImageRecord, OCRResult, SpeciesNetResult


class Command(BaseCommand):
    help = "Verify PostgreSQL content counts and public visibility invariants before cutover."

    def handle(self, *args, **options):
        db = "postgresql"
        images = ImageRecord.objects.using(db)

        total = images.count()
        species = SpeciesNetResult.objects.using(db).count()
        ocr = OCRResult.objects.using(db).count()
        public = images.filter(
            contains_human=False,
            has_detection=True,
            species_result__top_taxon__is_filter_visible=True,
        )

        human_leaks = public.filter(contains_human=True).count()
        no_detection_leaks = public.filter(has_detection=False).count()
        hidden_taxon_leaks = public.filter(
            species_result__top_taxon__is_filter_visible=False
        ).count()

        self.stdout.write("PostgreSQL cutover check")
        self.stdout.write(f"  ImageRecord:       {total:,}")
        self.stdout.write(f"  SpeciesNetResult:  {species:,}")
        self.stdout.write(f"  OCRResult:         {ocr:,}")
        self.stdout.write(f"  Public eligible:   {public.count():,}")
        self.stdout.write(f"  Human leaks:       {human_leaks:,}")
        self.stdout.write(f"  No-detection leaks:{no_detection_leaks:,}")
        self.stdout.write(f"  Hidden-taxon leaks:{hidden_taxon_leaks:,}")

        problems = []
        if total == 0:
            problems.append("PostgreSQL ImageRecord is empty")
        if species != total:
            problems.append(f"SpeciesNet count differs from ImageRecord by {total - species:,}")
        if human_leaks or no_detection_leaks or hidden_taxon_leaks:
            problems.append("public visibility invariant failed")

        if problems:
            raise CommandError("; ".join(problems))

        self.stdout.write(self.style.SUCCESS("Cutover checks passed."))
