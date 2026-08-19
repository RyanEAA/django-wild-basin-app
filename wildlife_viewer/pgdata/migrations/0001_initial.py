from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="CameraPath",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("path", models.TextField(unique=True)),
            ],
            options={"ordering": ["path"]},
        ),
        migrations.CreateModel(
            name="SpeciesTaxon",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("taxon_identifier", models.CharField(blank=True, db_index=True, max_length=64)),
                ("class_name", models.CharField(blank=True, max_length=128)),
                ("order_name", models.CharField(blank=True, max_length=128)),
                ("family_name", models.CharField(blank=True, max_length=128)),
                ("genus_name", models.CharField(blank=True, max_length=128)),
                ("species_name", models.CharField(blank=True, max_length=128)),
                ("common_name", models.CharField(db_index=True, max_length=255)),
                ("raw_label", models.TextField(unique=True)),
                ("is_human", models.BooleanField(db_index=True, default=False)),
                ("is_blank", models.BooleanField(db_index=True, default=False)),
                ("is_vehicle", models.BooleanField(db_index=True, default=False)),
            ],
            options={"ordering": ["common_name", "id"]},
        ),
        migrations.CreateModel(
            name="ImageRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file_id", models.CharField(max_length=64, unique=True)),
                ("file_name", models.CharField(blank=True, max_length=255)),
                ("file_url", models.URLField(blank=True, max_length=500)),
                ("direct_download_url", models.URLField(blank=True, max_length=500)),
                ("preview_url", models.URLField(blank=True, max_length=500)),
                ("cached_image", models.ImageField(blank=True, null=True, upload_to="cached_box_images/")),
                ("cache_last_accessed", models.DateTimeField(blank=True, null=True)),
                ("capture_date", models.DateField(blank=True, db_index=True, null=True)),
                ("capture_time", models.TimeField(blank=True, null=True)),
                ("temperature_f", models.FloatField(blank=True, null=True)),
                ("contains_human", models.BooleanField(db_index=True, default=False)),
                ("has_detection", models.BooleanField(db_index=True, default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("camera_path", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="images", to="pgdata.camerapath")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="SpeciesNetResult",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(blank=True, max_length=50)),
                ("raw_prediction", models.TextField(blank=True)),
                ("prediction_score", models.FloatField(blank=True, db_index=True, null=True)),
                ("prediction_source", models.CharField(blank=True, max_length=64)),
                ("model_version", models.CharField(blank=True, max_length=100)),
                ("raw_data", models.JSONField(blank=True, default=dict)),
                ("imported_at", models.DateTimeField(auto_now=True)),
                ("image", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="species_result", to="pgdata.imagerecord")),
                ("top_taxon", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="top_results", to="pgdata.speciestaxon")),
            ],
        ),
        migrations.CreateModel(
            name="OCRResult",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(blank=True, max_length=50)),
                ("ocr_texts", models.JSONField(blank=True, default=list)),
                ("raw_data", models.JSONField(blank=True, default=dict)),
                ("imported_at", models.DateTimeField(auto_now=True)),
                ("image", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="ocr_result", to="pgdata.imagerecord")),
            ],
        ),
        migrations.CreateModel(
            name="SpeciesClassification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("score", models.FloatField()),
                ("rank", models.PositiveSmallIntegerField()),
                ("species_result", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="classifications", to="pgdata.speciesnetresult")),
                ("taxon", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="classifications", to="pgdata.speciestaxon")),
            ],
            options={"ordering": ["rank"]},
        ),
        migrations.CreateModel(
            name="SpeciesDetection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("detection_index", models.PositiveSmallIntegerField()),
                ("category", models.CharField(blank=True, max_length=16)),
                ("label", models.CharField(blank=True, db_index=True, max_length=32)),
                ("confidence", models.FloatField(blank=True, db_index=True, null=True)),
                ("reviewed_score", models.FloatField(blank=True, null=True)),
                ("reviewed_source", models.CharField(blank=True, max_length=64)),
                ("bbox_x", models.FloatField(blank=True, null=True)),
                ("bbox_y", models.FloatField(blank=True, null=True)),
                ("bbox_width", models.FloatField(blank=True, null=True)),
                ("bbox_height", models.FloatField(blank=True, null=True)),
                ("reviewed_taxon", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_detections", to="pgdata.speciestaxon")),
                ("species_result", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="detections", to="pgdata.speciesnetresult")),
            ],
            options={"ordering": ["detection_index", "id"]},
        ),
        migrations.AddConstraint(
            model_name="speciesclassification",
            constraint=models.UniqueConstraint(fields=("species_result", "rank"), name="pg_unique_classification_rank"),
        ),
        migrations.AddConstraint(
            model_name="speciesdetection",
            constraint=models.UniqueConstraint(fields=("species_result", "detection_index"), name="pg_unique_detection_index"),
        ),
        migrations.AddIndex(model_name="speciestaxon", index=models.Index(fields=["common_name", "id"], name="pg_taxon_name_idx")),
        migrations.AddIndex(model_name="imagerecord", index=models.Index(fields=["camera_path", "id"], name="pg_img_path_id_idx")),
        migrations.AddIndex(model_name="imagerecord", index=models.Index(fields=["capture_date", "id"], name="pg_img_date_id_idx")),
        migrations.AddIndex(model_name="imagerecord", index=models.Index(fields=["contains_human", "id"], name="pg_img_human_id_idx")),
        migrations.AddIndex(model_name="speciesnetresult", index=models.Index(fields=["top_taxon", "image"], name="pg_result_taxon_img_idx")),
        migrations.AddIndex(model_name="speciesclassification", index=models.Index(fields=["taxon", "species_result"], name="pg_class_taxon_res_idx")),
        migrations.AddIndex(model_name="speciesclassification", index=models.Index(fields=["species_result", "rank"], name="pg_class_res_rank_idx")),
        migrations.AddIndex(model_name="speciesdetection", index=models.Index(fields=["species_result", "label"], name="pg_detect_res_label_idx")),
    ]
