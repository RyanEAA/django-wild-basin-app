from ..models import SpeciesLabel, SpeciesNetResult

def clean_species_label(label):
    if not label:
        return ""

    label = str(label).strip()

    if ";" in label:
        parts = [part.strip() for part in label.split(";") if part.strip()]
        if parts:
            return parts[-1]

    return label


def is_human_label(label):
    label = label.lower()
    return "human" in label or "homo sapiens" in label


def update_species_labels(species_result):
    labels = []

    if species_result.prediction:
        labels.append(clean_species_label(species_result.prediction))

    for animal in species_result.animals or []:
        if isinstance(animal, dict):
            labels.append(clean_species_label(animal.get("label", "")))
            labels.append(clean_species_label(animal.get("taxonomy", "")))

    for label in labels:
        if not label:
            continue

        species_label, _ = SpeciesLabel.objects.get_or_create(
            name=label,
            defaults={
                "is_human": is_human_label(label),
            }
        )

        species_label.count = SpeciesNetResult.objects.filter(
            prediction__icontains=label
        ).count()
        species_label.save(update_fields=["count", "is_human"])