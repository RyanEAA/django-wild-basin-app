from statistics import median
from time import perf_counter

from django.core.management.base import BaseCommand
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from images.models import CameraPath, ImageRecord, SpeciesLabel
from images.views import gallery, path_search, species_search


class Command(BaseCommand):
    help = (
        "Benchmark the real gallery and autocomplete views against the current "
        "database without modifying data."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--repeat",
            type=int,
            default=3,
            help="Timed repetitions after one warm-up run (default: 3).",
        )
        parser.add_argument(
            "--species",
            help="Species label to benchmark. Defaults to an existing non-human lookup label.",
        )
        parser.add_argument(
            "--path",
            dest="camera_path",
            help="Camera path to benchmark. Defaults to an existing lookup path.",
        )
        parser.add_argument(
            "--search",
            help="Optional free-text gallery search to benchmark.",
        )
        parser.add_argument(
            "--show-sql",
            action="store_true",
            help="Print the slowest SQL statement for each scenario.",
        )

    def handle(self, *args, **options):
        repeat = max(1, options["repeat"])
        factory = RequestFactory()

        species = options.get("species") or self._default_species()
        camera_path = options.get("camera_path") or self._default_path()
        search = options.get("search")

        self.stdout.write(self.style.MIGRATE_HEADING("Production query benchmark"))
        self.stdout.write(f"Database engine: {connection.vendor}")
        self.stdout.write(f"Timed repetitions: {repeat} (plus 1 warm-up)")
        self.stdout.write(f"Species sample: {species or '[none available]'}")
        self.stdout.write(f"Path sample: {camera_path or '[none available]'}")
        if search:
            self.stdout.write(f"Search sample: {search}")
        self.stdout.write("")

        # These counts are useful context and are deliberately outside the timed
        # scenarios so they do not contaminate the request measurements.
        self._print_counts()

        scenarios = [
            (
                "Gallery: unfiltered public page",
                lambda: gallery(factory.get("/")),
            ),
        ]

        if species:
            scenarios.extend(
                [
                    (
                        f"Species autocomplete: {self._autocomplete_term(species)!r}",
                        lambda: species_search(
                            factory.get(
                                "/ajax/species-search/",
                                {"q": self._autocomplete_term(species)},
                            )
                        ),
                    ),
                    (
                        f"Gallery: species={species!r}",
                        lambda: gallery(factory.get("/", {"species": species})),
                    ),
                ]
            )

        if camera_path:
            scenarios.extend(
                [
                    (
                        f"Path autocomplete: {self._autocomplete_term(camera_path)!r}",
                        lambda: path_search(
                            factory.get(
                                "/ajax/path-search/",
                                {"q": self._autocomplete_term(camera_path)},
                            )
                        ),
                    ),
                    (
                        f"Gallery: path={camera_path!r}",
                        lambda: gallery(factory.get("/", {"path": camera_path})),
                    ),
                ]
            )

        if search:
            scenarios.append(
                (
                    f"Gallery: search={search!r}",
                    lambda: gallery(factory.get("/", {"search": search})),
                )
            )

        for name, callback in scenarios:
            self._benchmark(
                name,
                callback,
                repeat=repeat,
                show_sql=options["show_sql"],
            )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Benchmark complete. These are server-side Django/DB timings; "
                "browser, Box image download/cache, Gunicorn queueing, and Nginx/network latency are not included."
            )
        )

    def _default_species(self):
        return (
            SpeciesLabel.objects.filter(is_human=False)
            .order_by("name")
            .values_list("name", flat=True)
            .first()
        )

    def _default_path(self):
        return (
            CameraPath.objects.order_by("path")
            .values_list("path", flat=True)
            .first()
        )

    @staticmethod
    def _autocomplete_term(value):
        value = (value or "").strip()
        if len(value) <= 4:
            return value
        return value[:4]

    def _print_counts(self):
        counts = [
            ("ImageRecord", ImageRecord.objects.count()),
            ("SpeciesLabel", SpeciesLabel.objects.count()),
            ("CameraPath", CameraPath.objects.count()),
        ]

        self.stdout.write(self.style.HTTP_INFO("Table sizes"))
        for label, value in counts:
            self.stdout.write(f"  {label:14s} {value:,}")
        self.stdout.write("")

    def _benchmark(self, name, callback, repeat, show_sql):
        # Warm up Python/Django code paths and give SQLite/PostgreSQL a chance to
        # populate normal caches. We report steady-state repetitions separately.
        callback()

        elapsed_ms = []
        db_ms = []
        query_counts = []
        slowest_query = None
        slowest_query_ms = -1.0

        for _ in range(repeat):
            with CaptureQueriesContext(connection) as captured:
                started = perf_counter()
                response = callback()
                elapsed = (perf_counter() - started) * 1000.0

            if getattr(response, "status_code", 200) >= 400:
                self.stderr.write(
                    self.style.ERROR(
                        f"{name}: response status {response.status_code}"
                    )
                )

            query_time = 0.0
            for item in captured.captured_queries:
                try:
                    item_ms = float(item.get("time") or 0.0) * 1000.0
                except (TypeError, ValueError):
                    item_ms = 0.0

                query_time += item_ms
                if item_ms > slowest_query_ms:
                    slowest_query_ms = item_ms
                    slowest_query = item.get("sql", "")

            elapsed_ms.append(elapsed)
            db_ms.append(query_time)
            query_counts.append(len(captured))

        self.stdout.write(self.style.HTTP_INFO(name))
        self.stdout.write(
            "  request: "
            f"median {median(elapsed_ms):.1f} ms | "
            f"min {min(elapsed_ms):.1f} | max {max(elapsed_ms):.1f}"
        )
        self.stdout.write(
            "  SQL:     "
            f"median {median(db_ms):.1f} ms | "
            f"queries {min(query_counts)}-{max(query_counts)}"
        )

        if show_sql and slowest_query:
            compact_sql = " ".join(slowest_query.split())
            self.stdout.write(f"  slowest SQL ({slowest_query_ms:.1f} ms):")
            self.stdout.write(f"    {compact_sql}")

        self.stdout.write("")
