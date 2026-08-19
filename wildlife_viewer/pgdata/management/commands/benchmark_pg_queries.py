import statistics
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, reset_queries

from pgdata.models import CameraPath, ImageRecord, SpeciesTaxon


class Command(BaseCommand):
    help = "Benchmark representative PostgreSQL gallery/filter queries before cutover."

    def add_arguments(self, parser):
        parser.add_argument("--database", default="postgresql")
        parser.add_argument("--repeat", type=int, default=5)
        parser.add_argument("--species")
        parser.add_argument("--path")

    def handle(self, *args, **options):
        alias = options["database"]
        repeat = max(1, options["repeat"])
        if alias not in connections.databases:
            raise CommandError(f"Database alias '{alias}' is not configured.")

        species = options.get("species") or (
            SpeciesTaxon.objects.using(alias)
            .filter(is_filter_visible=True)
            .order_by("common_name")
            .first()
        )
        if isinstance(species, str):
            species = SpeciesTaxon.objects.using(alias).filter(common_name__iexact=species).first()

        camera_path = options.get("path") or CameraPath.objects.using(alias).order_by("path").first()
        if isinstance(camera_path, str):
            camera_path = CameraPath.objects.using(alias).filter(path=camera_path).first()

        self.stdout.write("PostgreSQL query benchmark")
        self.stdout.write(f"Database: {connections[alias].settings_dict['NAME']}")
        self.stdout.write(f"Images: {ImageRecord.objects.using(alias).count():,}")
        self.stdout.write(f"Species: {species.common_name if species else '[none]'}")
        self.stdout.write(f"Path: {camera_path.path if camera_path else '[none]'}\n")

        public = ImageRecord.objects.using(alias).filter(
            contains_human=False,
            species_result__top_taxon__isnull=False,
            species_result__top_taxon__is_blank=False,
            species_result__top_taxon__is_vehicle=False,
        ).order_by("-id")

        self._bench("Public gallery fetch 20", lambda: list(public[:20]), repeat)
        self._bench("Public gallery COUNT", lambda: public.count(), repeat)

        if species:
            species_qs = public.filter(species_result__top_taxon_id=species.pk)
            self._bench(
                f"Species '{species.common_name}' fetch 20",
                lambda: list(species_qs[:20]),
                repeat,
            )
            self._bench(
                f"Species '{species.common_name}' COUNT",
                lambda: species_qs.count(),
                repeat,
            )
            prefix = species.common_name[:4]
            self._bench(
                f"Species autocomplete '{prefix}'",
                lambda: list(
                    SpeciesTaxon.objects.using(alias)
                    .filter(common_name__icontains=prefix, is_filter_visible=True)
                    .values_list("id", "common_name")[:20]
                ),
                repeat,
            )

        if camera_path:
            path_qs = public.filter(camera_path_id=camera_path.pk)
            self._bench(
                "Path fetch 20",
                lambda: list(path_qs[:20]),
                repeat,
            )
            self._bench("Path COUNT", lambda: path_qs.count(), repeat)
            prefix = camera_path.path[:4]
            self._bench(
                f"Path autocomplete '{prefix}'",
                lambda: list(
                    CameraPath.objects.using(alias)
                    .filter(path__icontains=prefix)
                    .values_list("id", "path")[:20]
                ),
                repeat,
            )

    def _bench(self, label, callback, repeat):
        callback()  # warm-up
        values = []
        for _ in range(repeat):
            reset_queries()
            start = time.perf_counter()
            callback()
            values.append((time.perf_counter() - start) * 1000)
        self.stdout.write(
            f"{label}: median {statistics.median(values):.1f} ms "
            f"| min {min(values):.1f} | max {max(values):.1f}"
        )
