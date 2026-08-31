"""config/*.json must be valid, tunable, and refuse spec-violating values (spec 46)."""

from __future__ import annotations

import pytest

from toycat_browser.config import Settings, load_settings
from toycat_browser.errors import ConfigError
from toycat_browser.states import CANONICAL_FILENAMES, ImageSlot


def test_shipped_config_loads(settings: Settings) -> None:
    assert settings.catalog.preset == "toy_catalog"
    assert settings.catalog.sku_prefix == "TTGS"


def test_canvas_is_2048_square_srgb_webp(settings: Settings) -> None:
    canvas = settings.catalog.canvas
    assert (canvas.width, canvas.height) == (2048, 2048)
    assert canvas.aspect_ratio == "1:1"
    assert canvas.color_profile == "sRGB"
    assert canvas.output_format == "WEBP"


def test_catalog_declares_exactly_the_six_standard_slots(settings: Settings) -> None:
    slots = [entry.slot for entry in settings.catalog.ordered_images]
    assert slots == [
        ImageSlot.CATALOG_HERO,
        ImageSlot.WHITE_BACKGROUND,
        ImageSlot.PACKSHOT,
        ImageSlot.DETAIL,
        ImageSlot.LIFESTYLE,
        ImageSlot.FEATURE_CARD,
    ]


def test_output_filenames_are_canonical(settings: Settings) -> None:
    for entry in settings.catalog.images:
        assert entry.filename == CANONICAL_FILENAMES[entry.slot]


def test_grouping_thresholds_match_spec_defaults(settings: Settings) -> None:
    grouping = settings.grouping
    assert grouping.auto_group_threshold == 0.85
    assert (grouping.ambiguous_low, grouping.ambiguous_high) == (0.60, 0.84)
    assert grouping.different_product_threshold == 0.60


def test_watermark_defaults_within_spec_ranges(settings: Settings) -> None:
    watermark = settings.watermark
    assert 0.08 <= watermark.width_ratio <= 0.12
    assert 0.20 <= watermark.opacity <= 0.30
    assert watermark.position == "bottom_right"
    assert watermark.mandatory is True


def test_retry_cap_is_three(settings: Settings) -> None:
    assert settings.qc.retry.max_attempts == 3
    assert settings.qc.retry.on_exhausted_status == "REVIEW_REQUIRED"
    assert settings.catalog.generation.max_attempts_per_image == 3


# --- rejections -----------------------------------------------------------


def test_rejects_non_uniform_scaling(write_config) -> None:
    def mutate(data):
        data["placement"]["uniform_scale_only"] = False

    with pytest.raises(ConfigError, match="uniform_scale_only"):
        load_settings(write_config("catalog", mutate))


def test_rejects_batched_image_sheet(write_config) -> None:
    def mutate(data):
        data["generation"]["one_image_per_request"] = False

    with pytest.raises(ConfigError, match="one_image_per_request"):
        load_settings(write_config("catalog", mutate))


def test_rejects_renamed_output_file(write_config) -> None:
    def mutate(data):
        data["images"][0]["filename"] = "hero.png"

    with pytest.raises(ConfigError, match="owned by Python"):
        load_settings(write_config("catalog", mutate))


def test_rejects_dropping_a_standard_slot(write_config) -> None:
    def mutate(data):
        data["images"] = [i for i in data["images"] if i["slot"] != "packshot"]
        for index, entry in enumerate(data["images"], start=1):
            entry["index"] = index

    with pytest.raises(ConfigError, match="missing required slots"):
        load_settings(write_config("catalog", mutate))


def test_rejects_optional_watermark(write_config) -> None:
    def mutate(data):
        data["mandatory"] = False

    with pytest.raises(ConfigError, match="mandatory"):
        load_settings(write_config("watermark", mutate))


def test_rejects_watermark_outside_accepted_range(write_config) -> None:
    def mutate(data):
        data["opacity"] = 0.9

    with pytest.raises(ConfigError, match="opacity"):
        load_settings(write_config("watermark", mutate))


def test_rejects_out_of_order_grouping_bands(write_config) -> None:
    def mutate(data):
        data["auto_group_threshold"] = 0.50

    with pytest.raises(ConfigError, match="thresholds"):
        load_settings(write_config("grouping", mutate))


def test_rejects_vision_model_overriding_deterministic_qc(write_config) -> None:
    def mutate(data):
        data["fidelity"]["vision_model_can_override_deterministic"] = True

    with pytest.raises(ConfigError, match="never override"):
        load_settings(write_config("qc", mutate))


def test_rejects_canvas_qc_size_disagreement(write_config) -> None:
    def mutate(data):
        data["deterministic"]["expected_width"] = 1024

    with pytest.raises(ConfigError, match="disagree"):
        load_settings(write_config("qc", mutate))


def test_rejects_malformed_json(app_copy) -> None:
    (app_copy.config / "qc.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_settings(app_copy)


def test_rejects_missing_config_file(app_copy) -> None:
    (app_copy.config / "scenes.json").unlink()
    with pytest.raises(ConfigError, match="missing config file"):
        load_settings(app_copy)


def test_thresholds_are_tunable(write_config) -> None:
    """A legitimate retune must be accepted; only spec violations are refused."""

    def mutate(data):
        data["auto_group_threshold"] = 0.90
        data["ambiguous_high"] = 0.89

    settings = load_settings(write_config("grouping", mutate))
    assert settings.grouping.auto_group_threshold == 0.90
