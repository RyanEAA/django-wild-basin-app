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