"""Brand-mark rules: the asset is locked, and each slot's logo state is deliberate."""

import os

import pytest

import quality
import slots


def test_logo_asset_matches_the_pinned_hash():
    """The logo is a locked master. A re-export or a swap changes the bytes, and
    a whole batch would otherwise ship with the wrong mark before anyone looked."""
    result = quality.check_watermark_asset()
    assert result["status"] == "pass", result["detail"]


def test_missing_logo_is_a_brand_asset_failure(monkeypatch):
    monkeypatch.setattr(quality, "LOGO_PATH", "no-such-logo.png")
    result = quality.check_watermark_asset()
    assert result["status"] == "fail"
    assert "FAIL_BRAND_ASSET" in result["detail"]


def test_altered_logo_is_rejected(monkeypatch):
    monkeypatch.setattr(quality, "EXPECTED_LOGO_SHA256", "0" * 64)
    assert quality.check_watermark_asset()["status"] == "fail"


@pytest.mark.slow
def test_branded_slots_carry_the_mark_and_clean_slots_do_not(gallery_images):
    checked = 0
    for sku, slot, path in gallery_images:
        result = quality.check_watermark(path, slot)
        if result is None:
            continue
        checked += 1
        assert result["status"] == "pass", f"{sku}/{slot}: {result['detail']}"
    assert checked, "no slots were checked"


@pytest.mark.slow
def test_marketplace_images_are_clean(gallery_images):
    """Stated separately from the sweep above: a logo creeping onto the
    white-background image costs the whole Google feed, not one picture."""
    seen = 0
    for sku, slot, path in gallery_images:
        if slot not in slots.CLEAN_SLOTS:
            continue
        seen += 1
        assert quality.logo_residual(path) > quality.LOGO_RESIDUAL_MAX, \
            f"{sku}/{slot} appears to carry the brand mark"
    assert seen, "no clean slots found to check"


@pytest.mark.slow
def test_detector_separates_present_from_absent(gallery_images):
    """The threshold is only meaningful if the two populations stay far apart."""
    present, absent = [], []
    for _, slot, path in gallery_images:
        r = quality.logo_residual(path)
        (present if slot in slots.BRANDED_SLOTS else absent).append(r)
    if not present or not absent:
        pytest.skip("need both branded and clean slots")
    assert max(present) < min(absent) / 2, \
        f"weak margin: branded max {max(present):.0f} vs clean min {min(absent):.0f}"
