"""Prompt rendering and the mandatory product lock (spec 13, 45)."""

from __future__ import annotations

import pytest

from toycat_browser.errors import ConfigError
from toycat_browser.paths import AppPaths
from toycat_browser.prompts import TEMPLATE_FILES, load_prompts
from toycat_browser.states import CATALOG_SLOT_ORDER, ImageSlot

LOCK_PHRASES = (
    "PRODUCT IDENTITY IS LOCKED.",
    "exact silhouette",
    "exact proportions",
    "exact colors",
    "exact components",
    "exact accessories",
    "exact packaging",
    "exact visible branding",
    "exact visible text",
    "redesign the product",
    "stretch or squash the product",
    "invent packaging",
    "invent branding",
)


def _values_for(slot: ImageSlot, library) -> dict[str, object]:
    return {token: f"<{token.lower()}>" for token in library.tokens_for(slot)}


def test_every_slot_has_a_template(paths: AppPaths) -> None:
    library = load_prompts(paths.prompts)
    assert set(library.templates) == set(CATALOG_SLOT_ORDER)
    assert len(TEMPLATE_FILES) == 6


def test_product_lock_contains_every_required_clause(paths: AppPaths) -> None:
    library = load_prompts(paths.prompts)
    for phrase in LOCK_PHRASES:
        assert phrase in library.product_lock, f"product lock is missing: {phrase}"


@pytest.mark.parametrize("slot", CATALOG_SLOT_ORDER, ids=lambda s: str(s))
def test_rendered_prompt_always_carries_the_lock(paths: AppPaths, slot: ImageSlot) -> None:
    library = load_prompts(paths.prompts)
    rendered = library.render(slot, _values_for(slot, library))
    assert "PRODUCT IDENTITY IS LOCKED." in rendered
    assert "exact silhouette" in rendered


@pytest.mark.parametrize("slot", CATALOG_SLOT_ORDER, ids=lambda s: str(s))
def test_rendered_prompt_has_no_leftover_placeholders(paths: AppPaths, slot: ImageSlot) -> None:
    library = load_prompts(paths.prompts)
    rendered = library.render(slot, _values_for(slot, library))
    assert "{{" not in rendered and "}}" not in rendered


@pytest.mark.parametrize("slot", CATALOG_SLOT_ORDER, ids=lambda s: str(s))
def test_every_prompt_requests_exactly_one_image(paths: AppPaths, slot: ImageSlot) -> None:
    library = load_prompts(paths.prompts)
    rendered = library.render(slot, _values_for(slot, library))
    assert "Generate ONE image only." in rendered


@pytest.mark.parametrize("slot", CATALOG_SLOT_ORDER, ids=lambda s: str(s))
def test_no_prompt_asks_for_a_generated_logo(paths: AppPaths, slot: ImageSlot) -> None:
    """The TTGS logo is applied locally and never generated (spec 29, 67)."""
    library = load_prompts(paths.prompts)
    rendered = library.render(slot, _values_for(slot, library)).lower()
    assert "no generated logo" in rendered


def test_missing_placeholder_is_an_error_not_a_literal(paths: AppPaths) -> None:
    library = load_prompts(paths.prompts)
    with pytest.raises(ConfigError, match="unresolved placeholders"):
        library.render(ImageSlot.LIFESTYLE, {})


def test_feature_card_forbids_generated_text(paths: AppPaths) -> None:
    """Text is rendered locally by Pillow, never by the image model (spec 26)."""
    library = load_prompts(paths.prompts)
    text = library.templates[ImageSlot.FEATURE_CARD]
    assert "No generated text." in text
    assert "rendered locally" in text


def test_packshot_forbids_recreating_packaging(paths: AppPaths) -> None:
    library = load_prompts(paths.prompts)
    text = library.templates[ImageSlot.PACKSHOT]
    assert "NEVER recreate packaging artwork from scratch." in text


def test_detail_forbids_synthesising_components(paths: AppPaths) -> None:
    library = load_prompts(paths.prompts)
    assert "Do not synthesize a component" in library.templates[ImageSlot.DETAIL]


def test_lifestyle_pins_a_prevalidated_scene(paths: AppPaths) -> None:
    """The scene is chosen locally; the model may not pick its own (spec 23)."""
    library = load_prompts(paths.prompts)
    tokens = library.tokens_for(ImageSlot.LIFESTYLE)
    assert {"SCENE_NAME", "SCENE_ENVIRONMENT", "SCENE_SURFACE", "FORBIDDEN_CONTEXTS"} <= tokens
    assert "Do NOT substitute a different environment." in library.templates[ImageSlot.LIFESTYLE]


def test_placement_constraints_reach_the_model(paths: AppPaths) -> None:
    """Scale and anchor are never left to the model's discretion (spec 27)."""
    library = load_prompts(paths.prompts)
    for slot in (ImageSlot.CATALOG_HERO, ImageSlot.WHITE_BACKGROUND,
                 ImageSlot.LIFESTYLE, ImageSlot.FEATURE_CARD):
        tokens = library.tokens_for(slot)
        assert "PLACEMENT_ANCHOR" in tokens
        assert "TARGET_WIDTH_RATIO" in tokens
        assert "uniform scaling only" in library.templates[slot]


def test_altered_product_lock_is_rejected(app_copy: AppPaths) -> None:
    (app_copy.prompts / "product-lock.txt").write_text("be nice to the toy", encoding="utf-8")
    with pytest.raises(ConfigError, match="altered or truncated"):
        load_prompts(app_copy.prompts)


def test_template_without_the_lock_token_is_rejected(app_copy: AppPaths) -> None:
    path = app_copy.prompts / "catalog-hero.txt"
    path.write_text("make a nice picture of the toy", encoding="utf-8")
    with pytest.raises(ConfigError, match="PRODUCT_LOCK"):
        load_prompts(app_copy.prompts)


def test_missing_template_is_rejected(app_copy: AppPaths) -> None:
    (app_copy.prompts / "lifestyle.txt").unlink()
    with pytest.raises(ConfigError, match="missing prompt template"):
        load_prompts(app_copy.prompts)
