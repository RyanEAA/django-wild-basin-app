import re
from datetime import datetime


TEMPERATURE_F_PATTERN = re.compile(r"(-?\d+(?:\.\d+)?)\s*°?\s*F", re.IGNORECASE)
DATE_PATTERN = re.compile(r"\b(\d{1,2})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{4})\b")
TIME_PATTERN = re.compile(r"\b(\d{1,2})\s*:\s*(\d{1,2})\s*:\s*(\d{1,2})\b")


TAXON_KIND_SPECIES = "species"
TAXON_KIND_GENUS = "genus"
TAXON_KIND_FAMILY = "family"
TAXON_KIND_ORDER = "order"
TAXON_KIND_CLASS = "class"
TAXON_KIND_BROAD = "broad"
TAXON_KIND_HUMAN = "human"
TAXON_KIND_VEHICLE = "vehicle"
TAXON_KIND_BLANK = "blank"
TAXON_KIND_NO_RESULT = "no_result"
TAXON_KIND_OTHER = "other"

NO_RESULT_NAMES = {
    "no cv result",
    "no result",
    "no prediction",
    "unknown",
}
BROAD_NAMES = {
    "animal",
    "carnivorous mammal",
    "mammal",
    "wildlife",
}


def classify_taxon(*, common_name, raw_label, class_name="", order_name="", family_name="", genus_name="", species_name=""):
    """Classify a normalized label without rewriting the source taxonomy.

    The raw SpeciesNet label remains authoritative. ``kind`` and
    ``is_filter_visible`` only describe how the UI should treat the label.
    """
    folded = str(common_name or "").strip().casefold()

    is_human = folded in {"human", "homo sapiens"} or "human" in folded
    is_blank = folded == "blank"
    is_vehicle = folded == "vehicle"

    if is_human:
        kind = TAXON_KIND_HUMAN
    elif is_blank:
        kind = TAXON_KIND_BLANK
    elif is_vehicle:
        kind = TAXON_KIND_VEHICLE
    elif folded in NO_RESULT_NAMES:
        kind = TAXON_KIND_NO_RESULT
    elif ";" in str(raw_label or ""):
        if species_name:
            kind = TAXON_KIND_SPECIES
        elif genus_name:
            kind = TAXON_KIND_GENUS
        elif family_name:
            kind = TAXON_KIND_FAMILY
        elif order_name:
            kind = TAXON_KIND_ORDER
        elif class_name:
            kind = TAXON_KIND_CLASS
        else:
            kind = TAXON_KIND_BROAD
    elif folded in BROAD_NAMES:
        kind = TAXON_KIND_BROAD
    else:
        # Preserve historical/simple reviewed labels without pretending to know
        # a taxonomic rank that the source does not provide.
        kind = TAXON_KIND_OTHER

    is_filter_visible = kind in {
        TAXON_KIND_SPECIES,
        TAXON_KIND_GENUS,
        TAXON_KIND_FAMILY,
        TAXON_KIND_ORDER,
        TAXON_KIND_CLASS,
        TAXON_KIND_OTHER,
    }

    return {
        "kind": kind,
        "is_filter_visible": is_filter_visible,
        "is_human": is_human,
        "is_blank": is_blank,
        "is_vehicle": is_vehicle,
    }


def parse_taxon_label(raw_label):
    raw_label = str(raw_label or "").strip()
    if not raw_label:
        return None

    parts = [part.strip() for part in raw_label.split(";")]
    common_name = next((part for part in reversed(parts) if part), raw_label)

    # SpeciesNet labels in the supplied data use:
    # identifier;class;order;family;genus;species;common-name
    padded = parts + [""] * max(0, 7 - len(parts))
    identifier, class_name, order_name, family_name, genus_name, species_name = padded[:6]

    values = {
        "taxon_identifier": identifier if ";" in raw_label else "",
        "class_name": class_name if ";" in raw_label else "",
        "order_name": order_name if ";" in raw_label else "",
        "family_name": family_name if ";" in raw_label else "",
        "genus_name": genus_name if ";" in raw_label else "",
        "species_name": species_name if ";" in raw_label else "",
        "common_name": common_name,
        "raw_label": raw_label,
    }
    values.update(
        classify_taxon(
            common_name=values["common_name"],
            raw_label=values["raw_label"],
            class_name=values["class_name"],
            order_name=values["order_name"],
            family_name=values["family_name"],
            genus_name=values["genus_name"],
            species_name=values["species_name"],
        )
    )
    return values


def parse_ocr_metadata(ocr_texts):
    temperature_f = None
    capture_date = None
    capture_time = None

    for raw_text in ocr_texts or []:
        if not isinstance(raw_text, str):
            continue
        text = raw_text.strip()
        if not text:
            continue

        if temperature_f is None:
            match = TEMPERATURE_F_PATTERN.search(text)
            if match:
                try:
                    temperature_f = float(match.group(1))
                except ValueError:
                    pass

        if capture_date is None:
            match = DATE_PATTERN.search(text)
            if match:
                try:
                    month, day, year = map(int, match.groups())
                    capture_date = datetime(year, month, day).date()
                except ValueError:
                    pass

        if capture_time is None:
            match = TIME_PATTERN.search(text)
            if match:
                try:
                    hour, minute, second = map(int, match.groups())
                    capture_time = datetime(2000, 1, 1, hour, minute, second).time()
                except ValueError:
                    pass

    return {
        "temperature_f": temperature_f,
        "capture_date": capture_date,
        "capture_time": capture_time,
    }
