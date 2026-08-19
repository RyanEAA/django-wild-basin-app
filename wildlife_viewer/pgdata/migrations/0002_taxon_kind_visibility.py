from django.db import migrations, models


def classify_existing_taxa(apps, schema_editor):
    SpeciesTaxon = apps.get_model("pgdata", "SpeciesTaxon")
    from pgdata.parsers import classify_taxon

    alias = schema_editor.connection.alias
    updates = []
    for taxon in SpeciesTaxon.objects.using(alias).all().iterator(chunk_size=2000):
        classification = classify_taxon(
            common_name=taxon.common_name,
            raw_label=taxon.raw_label,
            class_name=taxon.class_name,
            order_name=taxon.order_name,
            family_name=taxon.family_name,
            genus_name=taxon.genus_name,
            species_name=taxon.species_name,
        )
        taxon.kind = classification["kind"]
        taxon.is_filter_visible = classification["is_filter_visible"]
        # Recompute the existing flags too so historical rows follow the same
        # rules as newly imported rows.
        taxon.is_human = classification["is_human"]
        taxon.is_blank = classification["is_blank"]
        taxon.is_vehicle = classification["is_vehicle"]
        updates.append(taxon)
        if len(updates) >= 2000:
            SpeciesTaxon.objects.using(alias).bulk_update(
                updates,
                ["kind", "is_filter_visible", "is_human", "is_blank", "is_vehicle"],
                batch_size=2000,
            )
            updates = []
    if updates:
        SpeciesTaxon.objects.using(alias).bulk_update(
            updates,
            ["kind", "is_filter_visible", "is_human", "is_blank", "is_vehicle"],
            batch_size=2000,
        )


class Migration(migrations.Migration):
    dependencies = [("pgdata", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="speciestaxon",
            name="kind",
            field=models.CharField(db_index=True, default="other", max_length=24),
        ),
        migrations.AddField(
            model_name="speciestaxon",
            name="is_filter_visible",
            field=models.BooleanField(db_index=True, default=True),
        ),
        migrations.RunPython(classify_existing_taxa, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name="speciestaxon",
            index=models.Index(
                fields=["is_filter_visible", "common_name"],
                name="pg_taxon_visible_name_idx",
            ),
        ),
    ]
