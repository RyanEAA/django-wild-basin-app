from django.db import models
from django.utils import timezone


class CameraPath(models.Model):
    path = models.TextField(unique=True)

    class Meta:
        ordering = ["path"]

    def __str__(self):
        return self.path


class SpeciesTaxon(models.Model):
    """Normalized SpeciesNet taxonomy/classification label.

    ``raw_label`` preserves the full semicolon-delimited SpeciesNet class
    string. ``taxon_identifier`` stores the leading SpeciesNet UUID-like token
    as text so imports remain robust even if a future model emits a non-UUID
    identifier.
    """

    taxon_identifier = models.CharField(max_length=64, blank=True, db_index=True)
    class_name = models.CharField(max_length=128, blank=True)
    order_name = models.CharField(max_length=128, blank=True)
    family_name = models.CharField(max_length=128, blank=True)
    genus_name = models.CharField(max_length=128, blank=True)
    species_name = models.CharField(max_length=128, blank=True)
    common_name = models.CharField(max_length=255, db_index=True)
    raw_label = models.TextField(unique=True)
    kind = models.CharField(max_length=24, default="other", db_index=True)
    is_filter_visible = models.BooleanField(default=True, db_index=True)

    is_human = models.BooleanField(default=False, db_index=True)
    is_blank = models.BooleanField(default=False, db_index=True)
    is_vehicle = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["common_name", "id"]
        indexes = [
            models.Index(fields=["common_name", "id"], name="pg_taxon_name_idx"),
            models.Index(fields=["is_filter_visible", "common_name"], name="pg_taxon_visible_name_idx"),
        ]

    def __str__(self):
        return self.common_name or self.raw_label


class ImageRecord(models.Model):
    file_id = models.CharField(max_length=64, unique=True)
    file_name = models.CharField(max_length=255, blank=True)
    camera_path = models.ForeignKey(
        CameraPath,
        on_delete=models.PROTECT,
        related_name="images",
        null=True,
        blank=True,
    )

    file_url = models.URLField(max_length=500, blank=True)
    direct_download_url = models.URLField(max_length=500, blank=True)
    preview_url = models.URLField(max_length=500, blank=True)

    cached_image = models.ImageField(
        upload_to="cached_box_images/",
        blank=True,
        null=True,
    )
    cache_last_accessed = models.DateTimeField(null=True, blank=True)

    # Frequently filtered OCR-derived metadata is denormalized onto the image.
    capture_date = models.DateField(null=True, blank=True, db_index=True)
    capture_time = models.TimeField(null=True, blank=True)
    temperature_f = models.FloatField(null=True, blank=True)

    # Frequently filtered SpeciesNet-derived facts.
    contains_human = models.BooleanField(default=False, db_index=True)
    has_detection = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["camera_path", "id"], name="pg_img_path_id_idx"),
            models.Index(fields=["capture_date", "id"], name="pg_img_date_id_idx"),
            models.Index(fields=["contains_human", "id"], name="pg_img_human_id_idx"),
        ]

    def touch_cache(self):
        self.cache_last_accessed = timezone.now()
        self.save(update_fields=["cache_last_accessed"])

    @property
    def path(self):
        """Compatibility accessor for existing templates during cutover."""
        return self.camera_path.path if self.camera_path_id else ""

    def __str__(self):
        return f"{self.file_name} ({self.file_id})"


class SpeciesNetResult(models.Model):
    image = models.OneToOneField(
        ImageRecord,
        on_delete=models.CASCADE,
        related_name="species_result",
    )
    status = models.CharField(max_length=50, blank=True)

    top_taxon = models.ForeignKey(
        SpeciesTaxon,
        on_delete=models.SET_NULL,
        related_name="top_results",
        null=True,
        blank=True,
    )
    raw_prediction = models.TextField(blank=True)
    prediction_score = models.FloatField(null=True, blank=True, db_index=True)
    prediction_source = models.CharField(max_length=64, blank=True)
    model_version = models.CharField(max_length=100, blank=True)

    # Preserve the complete original JSONL row for auditability/round-tripping.
    raw_data = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["top_taxon", "image"], name="pg_result_taxon_img_idx"),
        ]

    @property
    def prediction(self):
        """Compatibility accessor matching the current ImageRecord UI."""
        return self.raw_prediction

    @property
    def display_prediction(self):
        if self.top_taxon_id:
            return self.top_taxon.common_name
        if not self.raw_prediction:
            return ""
        return self.raw_prediction.split(";")[-1].strip()

    def __str__(self):
        return f"SpeciesNetResult(image={self.image.file_id}, status={self.status})"


class SpeciesClassification(models.Model):
    species_result = models.ForeignKey(
        SpeciesNetResult,
        on_delete=models.CASCADE,
        related_name="classifications",
    )
    taxon = models.ForeignKey(
        SpeciesTaxon,
        on_delete=models.PROTECT,
        related_name="classifications",
    )
    score = models.FloatField()
    rank = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["rank"]
        constraints = [
            models.UniqueConstraint(
                fields=["species_result", "rank"],
                name="pg_unique_classification_rank",
            ),
        ]
        indexes = [
            models.Index(fields=["taxon", "species_result"], name="pg_class_taxon_res_idx"),
            models.Index(fields=["species_result", "rank"], name="pg_class_res_rank_idx"),
        ]

    def __str__(self):
        return f"{self.rank}. {self.taxon} ({self.score:.3f})"


class SpeciesDetection(models.Model):
    species_result = models.ForeignKey(
        SpeciesNetResult,
        on_delete=models.CASCADE,
        related_name="detections",
    )
    detection_index = models.PositiveSmallIntegerField()

    # Preserve both fields from SpeciesNet. category is typically "1"/"2"/"3";
    # label is the human-readable detector class animal/human/vehicle.
    category = models.CharField(max_length=16, blank=True)
    label = models.CharField(max_length=32, blank=True, db_index=True)
    confidence = models.FloatField(null=True, blank=True, db_index=True)

    # Optional Wild Basin researcher annotation. Raw SpeciesNet detections do
    # not carry species identity; these fields are populated only when an
    # edited/round-tripped record explicitly supplies per-box review metadata.
    reviewed_taxon = models.ForeignKey(
        SpeciesTaxon,
        on_delete=models.SET_NULL,
        related_name="reviewed_detections",
        null=True,
        blank=True,
    )
    reviewed_score = models.FloatField(null=True, blank=True)
    reviewed_source = models.CharField(max_length=64, blank=True)

    bbox_x = models.FloatField(null=True, blank=True)
    bbox_y = models.FloatField(null=True, blank=True)
    bbox_width = models.FloatField(null=True, blank=True)
    bbox_height = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["detection_index", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["species_result", "detection_index"],
                name="pg_unique_detection_index",
            ),
        ]
        indexes = [
            models.Index(fields=["species_result", "label"], name="pg_detect_res_label_idx"),
        ]

    def __str__(self):
        return f"{self.label or self.category} ({self.confidence})"


class OCRResult(models.Model):
    image = models.OneToOneField(
        ImageRecord,
        on_delete=models.CASCADE,
        related_name="ocr_result",
    )
    status = models.CharField(max_length=50, blank=True)
    ocr_texts = models.JSONField(default=list, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"OCRResult(image={self.image.file_id}, status={self.status})"
