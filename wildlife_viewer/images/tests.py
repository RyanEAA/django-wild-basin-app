import csv
from datetime import date, datetime, time

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from .models import ImageRecord, OCRResult, SpeciesDetection, SpeciesNetResult


class ImageDetailEditTests(TestCase):
    def test_researcher_can_see_editable_prediction_field(self):
        image = ImageRecord.objects.create(
            file_id="file-editable",
            file_name="camera-editable.jpg",
            path="Box/Wild Basin/Camera Editable",
        )
        SpeciesNetResult.objects.create(
            image=image,
            prediction="uuid;american black bear",
        )

        researcher_group = Group.objects.create(name="Researcher")
        researcher = User.objects.create_user(
            username="researcher",
            password="secret123",
        )
        researcher.groups.add(researcher_group)
        self.client.force_login(researcher)

        response = self.client.get(reverse("image_detail", args=[image.file_id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="prediction"')
        self.assertContains(response, 'class="species-prediction-autocomplete')


class ExportCsvTests(TestCase):
    def test_public_users_can_export_only_visible_images(self):
        human_image = ImageRecord.objects.create(
            file_id="file-human",
            file_name="camera-human.jpg",
            path="Box/Wild Basin/Camera Human",
        )
        human_species = SpeciesNetResult.objects.create(
            image=human_image,
            prediction="uuid;human",
        )
        SpeciesDetection.objects.create(
            species_result=human_species,
            source="animal",
            label="human",
        )
        OCRResult.objects.create(
            image=human_image,
            capture_date=date(2026, 7, 1),
            capture_time=time(9, 30, 0),
        )

        visible_image = ImageRecord.objects.create(
            file_id="file-2",
            file_name="camera-02.jpg",
            path="Box/Wild Basin/Camera 2",
        )
        visible_species = SpeciesNetResult.objects.create(
            image=visible_image,
            prediction="uuid;ursus;american black bear",
        )
        SpeciesDetection.objects.create(
            species_result=visible_species,
            source="animal",
            label="black bear",
        )
        OCRResult.objects.create(
            image=visible_image,
            capture_datetime=datetime(2026, 7, 2, 14, 45, 0),
        )

        response = self.client.get(reverse("export_csv"))

        self.assertEqual(response.status_code, 200)
        rows = list(csv.reader(response.content.decode("utf-8").splitlines()))

        self.assertEqual(
            rows,
            [
                ["image_name", "box_directory", "prediction", "detection", "date", "time"],
                ["camera-02.jpg", "Box/Wild Basin/Camera 2", "american black bear", "black bear", "2026-07-02", "14:45:00"],
            ],
        )

    def test_export_respects_gallery_filters(self):
        image_one = ImageRecord.objects.create(
            file_id="file-1",
            file_name="camera-01.jpg",
            path="Box/Wild Basin/Camera 1",
        )
        species_one = SpeciesNetResult.objects.create(
            image=image_one,
            prediction="uuid;carnivora;canidae;canis;latrans;coyote",
        )
        SpeciesDetection.objects.create(
            species_result=species_one,
            source="animal",
            label="coyote",
        )
        SpeciesDetection.objects.create(
            species_result=species_one,
            source="detection",
            label="animal box",
        )
        OCRResult.objects.create(
            image=image_one,
            capture_date=date(2026, 7, 1),
            capture_time=time(9, 30, 0),
        )

        image_two = ImageRecord.objects.create(
            file_id="file-2",
            file_name="camera-02.jpg",
            path="Box/Wild Basin/Camera 2",
        )
        species_two = SpeciesNetResult.objects.create(
            image=image_two,
            prediction="uuid;ursus;american black bear",
        )
        SpeciesDetection.objects.create(
            species_result=species_two,
            source="animal",
            label="black bear",
        )
        OCRResult.objects.create(
            image=image_two,
            capture_datetime=datetime(2026, 7, 2, 14, 45, 0),
        )

        response = self.client.get(f"{reverse('export_csv')}?search=camera-02")

        self.assertEqual(response.status_code, 200)
        rows = list(csv.reader(response.content.decode("utf-8").splitlines()))

        self.assertEqual(
            rows,
            [
                ["image_name", "box_directory", "prediction", "detection", "date", "time"],
                ["camera-02.jpg", "Box/Wild Basin/Camera 2", "american black bear", "black bear", "2026-07-02", "14:45:00"],
            ],
        )

class ExportJsonBundleTests(TestCase):
    def test_export_uses_import_compatible_formats(self):
        import io
        import json
        import zipfile

        image = ImageRecord.objects.create(
            file_id="round-trip-1",
            file_name="camera-01.jpg",
            path="/Wild Basin/Camera 1",
            file_url="https://app.box.com/file/round-trip-1",
            direct_download_url="https://example.com/download/round-trip-1",
            preview_url="https://example.com/preview/round-trip-1",
        )
        SpeciesNetResult.objects.create(
            image=image,
            status="ok",
            prediction="uuid;ursus;american black bear",
            prediction_score=0.91,
            prediction_source="classifier",
            classifications={"animal": 0.91},
            detections=[
                {"label": "animal", "conf": 0.98, "bbox": [0.1, 0.2, 0.3, 0.4]}
            ],
            model_version="speciesnet-test",
        )
        OCRResult.objects.create(
            image=image,
            status="ok",
            ocr_texts=["Bushnell", "66F", "10-10-2017", "13:41:11"],
        )

        response = self.client.get(reverse("export_json_bundle"))
        self.assertEqual(response.status_code, 200)
        archive_bytes = b"".join(response.streaming_content)

        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "image_urls.json",
                    "speciesnet_predictions.jsonl",
                    "ocr_results.jsonl",
                },
            )

            images = json.loads(archive.read("image_urls.json"))
            species = json.loads(
                archive.read("speciesnet_predictions.jsonl").decode("utf-8").strip()
            )
            ocr = json.loads(
                archive.read("ocr_results.jsonl").decode("utf-8").strip()
            )

        self.assertEqual(images[0]["file_id"], image.file_id)
        self.assertEqual(images[0]["direct_download_url"], image.direct_download_url)
        self.assertEqual(species["prediction"]["detections"][0]["bbox"], [0.1, 0.2, 0.3, 0.4])
        self.assertEqual(species["prediction"]["model_version"], "speciesnet-test")
        self.assertEqual(ocr["ocr_texts"], ["Bushnell", "66F", "10-10-2017", "13:41:11"])

    def test_export_respects_gallery_filters(self):
        ImageRecord.objects.create(file_id="one", file_name="camera-01.jpg")
        ImageRecord.objects.create(file_id="two", file_name="camera-02.jpg")

        response = self.client.get(
            f"{reverse('export_json_bundle')}?search=camera-02"
        )
        archive_bytes = b"".join(response.streaming_content)

        import io
        import json
        import zipfile

        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            images = json.loads(archive.read("image_urls.json"))

        self.assertEqual([item["file_id"] for item in images], ["two"])
