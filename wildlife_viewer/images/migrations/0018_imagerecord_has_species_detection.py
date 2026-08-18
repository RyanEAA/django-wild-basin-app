from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("images", "0017_specieslabel_camerapath"),
    ]

    operations = [
        migrations.AddField(
            model_name="imagerecord",
            name="has_species_detection",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
