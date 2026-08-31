"""Typed, validated configuration (spec 46).

Every threshold in this application comes from config/*.json. Nothing that a
user might reasonably want to tune is hard-coded in Python.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import ConfigError
from .paths import AppPaths, get_paths
from .states import CANONICAL_FILENAMES, ImageSlot

Ratio = Annotated[float, Field(ge=0.0, le=1.0)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------
# catalog.json
# --------------------------------------------------------------------------


class WorkingCopyConfig(_Strict):
    max_edge_pixels: int = Field(gt=0)
    format: str
    jpeg_quality: int = Field(ge=1, le=100)
    strip_metadata: bool

    @model_validator(mode="after")
    def _privacy(self) -> "WorkingCopyConfig":
        if not self.strip_metadata:
            raise ValueError(
                "strip_metadata must be true: working copies are uploaded to an "
                "external service and source photos carry GPS coordinates"
            )
        return self


class InputConfig(_Strict):
    supported_extensions: list[str] = Field(min_length=1)
    recursive: bool
    follow_symlinks: bool
    ignore_filenames: list[str]
    ignore_hidden: bool
    min_edge_pixels: int = Field(ge=0)
    min_megapixels: float = Field(ge=0)
    max_file_size_bytes: int = Field(gt=0)
    working_copy: WorkingCopyConfig

    @model_validator(mode="after")
    def _extensions_are_normalised(self) -> "InputConfig":
        for extension in self.supported_extensions:
            if not extension.startswith(".") or extension != extension.lower():
                raise ValueError(
                    f"supported_extensions entries must be lowercase and dotted, got {extension!r}"
                )
        return self

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset(self.supported_extensions)


class CanvasConfig(_Strict):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    aspect_ratio: str
    color_profile: str
    output_format: str
    webp_quality: int = Field(ge=1, le=100)


class ImageSlotConfig(_Strict):
    slot: ImageSlot
    index: int = Field(ge=1)
    filename: str
    prompt: str
    required: bool

    @model_validator(mode="after")
    def _filename_is_canonical(self) -> "ImageSlotConfig":
        expected = CANONICAL_FILENAMES[self.slot]
        if self.filename != expected:
            raise ValueError(
                f"slot {self.slot} must be written as {expected!r}, not {self.filename!r} "
                "(spec 44: output filenames are owned by Python)"
            )
        return self


class PlacementConfig(_Strict):
    anchor: str
    target_width_ratio: Ratio
    min_margin: Ratio
    uniform_scale_only: bool

    @model_validator(mode="after")
    def _no_distortion(self) -> "PlacementConfig":
        if not self.uniform_scale_only:
            raise ValueError(
                "uniform_scale_only must be true; spec 27 forbids stretching, "
                "squashing, warping or liquifying the product"
            )
        if self.target_width_ratio + 2 * self.min_margin > 1.0:
            raise ValueError(
                "target_width_ratio + 2 * min_margin exceeds the frame width"
            )
        return self


class GenerationConfig(_Strict):
    provider: str
    one_image_per_request: bool
    one_conversation_per_product: bool
    max_attempts_per_image: int = Field(ge=1, le=10)
    generation_timeout_seconds: int = Field(gt=0)
    download_timeout_seconds: int = Field(gt=0)
    backoff_seconds: list[float]

    @model_validator(mode="after")
    def _one_at_a_time(self) -> "GenerationConfig":
        if not self.one_image_per_request:
            raise ValueError(
                "one_image_per_request must be true; spec 17 forbids asking for "
                "all six catalog images as a single sheet"
            )
        return self


class AnalysisConfig(_Strict):
    ollama_host: str
    vision_model: str
    num_ctx: int = Field(gt=0)
    request_timeout_seconds: int = Field(gt=0)
    release_model_between_stages: bool


class CatalogConfig(_Strict):
    preset: str
    brand_name: str
    sku_prefix: str
    input: InputConfig
    canvas: CanvasConfig
    images: list[ImageSlotConfig]
    placement: PlacementConfig
    generation: GenerationConfig
    analysis: AnalysisConfig

    @model_validator(mode="after")
    def _six_image_standard(self) -> "CatalogConfig":
        slots = [entry.slot for entry in self.images]
        if len(set(slots)) != len(slots):
            raise ValueError("duplicate image slots in catalog.json")
        missing = set(ImageSlot) - set(slots)
        if missing:
            raise ValueError(
                "catalog preset is missing required slots: "
                + ", ".join(sorted(missing))
            )
        indices = sorted(entry.index for entry in self.images)
        if indices != list(range(1, len(self.images) + 1)):
            raise ValueError("image indices must be a contiguous 1..N sequence")
        return self

    def slot(self, slot: ImageSlot) -> ImageSlotConfig:
        for entry in self.images:
            if entry.slot == slot:
                return entry
        raise ConfigError(f"slot {slot} is not configured")

    @property
    def ordered_images(self) -> list[ImageSlotConfig]:
        return sorted(self.images, key=lambda entry: entry.index)


# --------------------------------------------------------------------------
# watermark.json
# --------------------------------------------------------------------------


class WatermarkVerification(_Strict):
    mode: str
    position_tolerance_px: int = Field(ge=0)
    size_tolerance_px: int = Field(ge=0)
    min_alpha_correlation: Ratio


class WatermarkConfig(_Strict):
    enabled: bool
    mandatory: bool
    asset: str
    asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verify_asset_hash: bool
    width_ratio: Ratio
    width_ratio_accepted_range: tuple[Ratio, Ratio]
    opacity: Ratio
    opacity_accepted_range: tuple[Ratio, Ratio]
    position: str
    margin_ratio: Ratio
    verification: WatermarkVerification

    @model_validator(mode="after")
    def _within_accepted_ranges(self) -> "WatermarkConfig":
        lo, hi = self.width_ratio_accepted_range
        if not lo <= self.width_ratio <= hi:
            raise ValueError(f"width_ratio {self.width_ratio} outside [{lo}, {hi}]")
        lo, hi = self.opacity_accepted_range
        if not lo <= self.opacity <= hi:
            raise ValueError(f"opacity {self.opacity} outside [{lo}, {hi}]")
        if self.enabled and not self.mandatory:
            raise ValueError(
                "spec 30: the watermark is mandatory on every final image"
            )
        return self

    def asset_path(self, paths: AppPaths) -> Path:
        return paths.root / self.asset


# --------------------------------------------------------------------------
# grouping.json
# --------------------------------------------------------------------------


class GroupingConfig(_Strict):
    auto_group_threshold: Ratio
    ambiguous_low: Ratio
    ambiguous_high: Ratio
    different_product_threshold: Ratio
    duplicate_threshold: Ratio
    near_duplicate_threshold: Ratio
    ambiguity_margin: Ratio
    timestamp_proximity_seconds: int = Field(ge=0)
    timestamp_weight: Ratio
    embedding_weight: Ratio
    use_filename_hints: bool
    min_images_per_group: int = Field(ge=1)
    max_images_per_group: int = Field(ge=1)
    verify_groups_with_vision_model: bool
    verification_min_confidence: Ratio

    @model_validator(mode="after")
    def _bands_are_ordered(self) -> "GroupingConfig":
        if not (
            self.different_product_threshold
            <= self.ambiguous_low
            <= self.ambiguous_high
            < self.auto_group_threshold
            <= self.near_duplicate_threshold
            <= self.duplicate_threshold
        ):
            raise ValueError(
                "grouping thresholds must satisfy: different_product <= ambiguous_low "
                "<= ambiguous_high < auto_group <= near_duplicate <= duplicate"
            )
        total = self.timestamp_weight + self.embedding_weight
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"signal weights must sum to 1.0 (got {total})")
        if self.min_images_per_group > self.max_images_per_group:
            raise ValueError("min_images_per_group exceeds max_images_per_group")
        return self


# --------------------------------------------------------------------------
# qc.json
# --------------------------------------------------------------------------


class DeterministicQCConfig(_Strict):
    expected_width: int = Field(gt=0)
    expected_height: int = Field(gt=0)
    expected_aspect_ratio: float = Field(gt=0)
    aspect_ratio_tolerance: float = Field(ge=0)
    expected_format: str
    expected_color_profile: str
    max_file_size_bytes: int = Field(gt=0)
    min_file_size_bytes: int = Field(ge=0)
    allow_transparency: bool
    require_watermark: bool
    min_product_bbox_ratio: Ratio
    max_product_bbox_ratio: Ratio
    safe_bounds_margin: Ratio

    @model_validator(mode="after")
    def _sane(self) -> "DeterministicQCConfig":
        if self.min_file_size_bytes >= self.max_file_size_bytes:
            raise ValueError("min_file_size_bytes must be below max_file_size_bytes")
        if self.min_product_bbox_ratio >= self.max_product_bbox_ratio:
            raise ValueError("min_product_bbox_ratio must be below max")
        return self


class FidelityQCConfig(_Strict):
    critical_properties: list[str] = Field(min_length=1)
    review_properties: list[str]
    vision_model_can_override_deterministic: bool

    @model_validator(mode="after")
    def _qc_is_final_authority(self) -> "FidelityQCConfig":
        if self.vision_model_can_override_deterministic:
            raise ValueError(
                "spec 35: a vision model may never override a deterministic failure"
            )
        return self


class RetryConfig(_Strict):
    max_attempts: int = Field(ge=1, le=10)
    on_exhausted_status: str


class QCConfig(_Strict):
    deterministic: DeterministicQCConfig
    fidelity: FidelityQCConfig
    retry: RetryConfig


# --------------------------------------------------------------------------
# scenes.json
# --------------------------------------------------------------------------


class SceneStyle(_Strict):
    description: str
    forbid_noisy_backgrounds: bool


class SceneAsset(_Strict):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str = ""
    scene_type: str = ""
    environment: str
    surface: list[str] = Field(default_factory=list)
    size_limit: str = ""
    allowed_categories: list[str] = Field(default_factory=list)
    forbidden_categories: list[str] = Field(default_factory=list)
    file: str | None = None


class CategoryRequirement(_Strict):
    environment: list[str] = Field(min_length=1)
    surface: list[str] = Field(min_length=1)
    size_class: str
    water_related: bool = False


class ScenesConfig(_Strict):
    style: SceneStyle
    asset_dirs: list[str]
    fallback_status: str
    size_classes: list[str] = Field(min_length=1)
    scenes: list[SceneAsset]
    category_requirements: dict[str, CategoryRequirement]
    forbidden_contexts_by_size_class: dict[str, list[str]]

    @model_validator(mode="after")
    def _known_size_classes(self) -> "ScenesConfig":
        for category, req in self.category_requirements.items():
            if req.size_class not in self.size_classes:
                raise ValueError(
                    f"category {category!r} uses unknown size_class {req.size_class!r}"
                )
        for size_class in self.forbidden_contexts_by_size_class:
            if size_class not in self.size_classes:
                raise ValueError(f"unknown size_class {size_class!r}")
        ids = [scene.id for scene in self.scenes]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate scene ids")
        return self


# --------------------------------------------------------------------------
# loader
# --------------------------------------------------------------------------


class Settings(_Strict):
    """The whole validated configuration set."""

    catalog: CatalogConfig
    watermark: WatermarkConfig
    grouping: GroupingConfig
    qc: QCConfig
    scenes: ScenesConfig

    @model_validator(mode="after")
    def _cross_file_consistency(self) -> "Settings":
        canvas = self.catalog.canvas
        det = self.qc.deterministic
        if (canvas.width, canvas.height) != (det.expected_width, det.expected_height):
            raise ValueError(
                "catalog.json canvas size and qc.json expected size disagree: "
                f"{canvas.width}x{canvas.height} vs {det.expected_width}x{det.expected_height}"
            )
        if canvas.output_format.upper() != det.expected_format.upper():
            raise ValueError("catalog output_format and qc expected_format disagree")
        if canvas.color_profile.lower() != det.expected_color_profile.lower():
            raise ValueError("catalog color_profile and qc expected_color_profile disagree")
        if self.qc.retry.max_attempts != self.catalog.generation.max_attempts_per_image:
            raise ValueError(
                "qc.json retry.max_attempts and catalog.json max_attempts_per_image disagree"
            )
        return self


_FILES: dict[str, type[BaseModel]] = {
    "catalog": CatalogConfig,
    "watermark": WatermarkConfig,
    "grouping": GroupingConfig,
    "qc": QCConfig,
    "scenes": ScenesConfig,
}


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise ConfigError(f"missing config file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc


def load_settings(paths: AppPaths | None = None) -> Settings:
    """Load and validate config/*.json. Raises ConfigError with a readable report."""
    paths = paths or get_paths()
    sections: dict[str, Any] = {}
    for name, model in _FILES.items():
        raw = _read_json(paths.config / f"{name}.json")
        try:
            sections[name] = model.model_validate(raw)
        except ValidationError as exc:
            raise ConfigError(f"config/{name}.json is invalid:\n{exc}") from exc
    try:
        return Settings(**sections)
    except ValidationError as exc:
        raise ConfigError(f"configuration is internally inconsistent:\n{exc}") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
