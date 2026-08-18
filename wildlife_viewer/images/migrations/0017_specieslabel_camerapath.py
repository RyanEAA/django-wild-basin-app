from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("images", "0016_remove_appsettings_box_redirect_uri"),
    ]

    operations = [
        migrations.CreateModel(
            name="SpeciesLabel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255, unique=True)),
                ("is_human", models.BooleanField(db_index=True, default=False)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="CameraPath",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("path", models.TextField(unique=True)),
            ],
            options={"ordering": ["path"]},
        ),
    ]
