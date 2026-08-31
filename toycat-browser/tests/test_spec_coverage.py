"""Spec 63 test checklist, made visible.

Each required test area is either exercised by a real test module or explicitly
skipped with the phase that will build it. This keeps the gap between "required"
and "covered" in the test output instead of in someone's head.
"""

from __future__ import annotations

import pytest

COVERED_NOW = {
    "file discovery": "test_scan.py",
    "input validation": "test_scan.py, test_images.py",
    "heic support": "test_images.py",
    "exif orientation": "test_images.py",
    "product profile schema": "partially — provenance vocabulary in test_states.py",
    "prompt rendering": "test_prompts.py",
    "watermark asset hash": "test_brand_asset.py",
    "output filenames": "test_states.py, test_config.py",
    "qc status": "test_states.py (vocabulary), test_config.py (authority rules)",
}

PENDING = {
    "grouping": "Phase 3",
    "duplicate detection (perceptual)": "Phase 3",
    "content schema": "Phase 5",
    "scene compatibility": "Phase 7",
    "image dimensions": "Phase 8",
    "aspect-ratio preservation": "Phase 8",
    "watermark presence": "Phase 8",
    "retry behavior": "Phase 11",
    "resumability": "Phase 11",
    "idempotency": "Phase 11",
    "shopify csv generation": "Phase 12",
}


@pytest.mark.parametrize("area", sorted(COVERED_NOW), ids=lambda a: a.replace(" ", "-"))
def test_area_is_covered(area: str) -> None:
    assert COVERED_NOW[area]


@pytest.mark.parametrize("area", sorted(PENDING), ids=lambda a: a.replace(" ", "-"))
def test_area_is_pending(area: str) -> None:
    pytest.skip(f"{area}: lands in {PENDING[area]}")


def test_sku_uniqueness_is_not_yet_testable() -> None:
    pytest.skip("SKU registry lands in Phase 5")
