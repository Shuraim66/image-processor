"""The controlled vocabularies (spec 11, 44, 54, 68)."""

from __future__ import annotations

import pytest

from toycat_browser.states import (
    CANONICAL_FILENAMES,
    CATALOG_SLOT_ORDER,
    SUCCESS_IMAGE_STATES,
    TERMINAL_IMAGE_STATES,
    ImageSlot,
    ImageState,
    ProductState,
    Provenance,
)


def test_image_states_match_spec_68() -> None:
    assert {str(s) for s in ImageState} == {
        "QUEUED", "PROCESSING", "DOWNLOADING", "POST_PROCESSING",
        "VALIDATING", "PASS", "REVIEW_REQUIRED", "FAILED",
    }


def test_product_states_match_spec_68() -> None:
    assert {str(s) for s in ProductState} == {"COMPLETED", "REVIEW_REQUIRED", "FAILED"}


def test_only_pass_counts_as_success() -> None:
    assert SUCCESS_IMAGE_STATES == {ImageState.PASS}
    assert ImageState.REVIEW_REQUIRED not in SUCCESS_IMAGE_STATES
    assert ImageState.REVIEW_REQUIRED in TERMINAL_IMAGE_STATES


def test_provenance_has_no_ai_guess() -> None:
    """Spec 11: an inference the model cannot see is UNKNOWN, never a fact."""
    values = {str(p) for p in Provenance}
    assert values == {"VERIFIED_FROM_PHOTOS", "USER_PROVIDED", "UNKNOWN"}
    assert not any("GUESS" in v for v in values)


def test_catalog_is_the_six_image_standard_without_gifthero() -> None:
    assert len(CATALOG_SLOT_ORDER) == 6
    assert "gift_hero" not in {str(s) for s in ImageSlot}


def test_every_slot_has_one_canonical_filename() -> None:
    assert set(CANONICAL_FILENAMES) == set(ImageSlot)
    names = list(CANONICAL_FILENAMES.values())
    assert len(set(names)) == 6
    assert all(name.endswith(".webp") for name in names)


@pytest.mark.parametrize(
    ("slot", "expected"),
    [
        (ImageSlot.CATALOG_HERO, "01-catalog-hero.webp"),
        (ImageSlot.WHITE_BACKGROUND, "02-white-background.webp"),
        (ImageSlot.PACKSHOT, "03-packshot.webp"),
        (ImageSlot.DETAIL, "04-detail.webp"),
        (ImageSlot.LIFESTYLE, "05-lifestyle.webp"),
        (ImageSlot.FEATURE_CARD, "06-feature-card.webp"),
    ],
)
def test_output_filenames_are_fixed(slot: ImageSlot, expected: str) -> None:
    """Spec 44: never depend on ChatGPT's generated filename."""
    assert CANONICAL_FILENAMES[slot] == expected
