"""The mandatory blue Dumpling/Squishy regression case (spec 64).

This fixture exists because a previous generation pipeline changed the
product's size, proportions and appearance. Phase 1 can only assert that the
fixture is intact and that its ground truth is internally consistent; the
fidelity assertions themselves arrive with the phases that can produce images.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from toycat_browser.config import Settings

pytestmark = pytest.mark.regression

EXPECTED_PHOTOS = 6


@pytest.fixture(scope="module")
def manifest(dumpling_fixture: Path) -> dict:
    return json.loads((dumpling_fixture / "manifest.json").read_text(encoding="utf-8"))


def test_fixture_photographs_are_present(dumpling_fixture: Path, manifest: dict) -> None:
    photos = sorted(dumpling_fixture.glob("*.jpg"))
    assert len(photos) == EXPECTED_PHOTOS
    assert {p.name for p in photos} == set(manifest["reference_images"])


def test_fixture_photographs_are_readable(dumpling_fixture: Path, manifest: dict) -> None:
    for name in manifest["reference_images"]:
        with Image.open(dumpling_fixture / name) as image:
            image.verify()


def test_fixture_photographs_are_high_resolution(dumpling_fixture: Path, manifest: dict) -> None:
    """References must comfortably exceed the 2048px output canvas."""
    for name in manifest["reference_images"]:
        with Image.open(dumpling_fixture / name) as image:
            assert min(image.size) >= 2048, f"{name} is too small to be a reference"


def test_ground_truth_records_two_components(manifest: dict) -> None:
    truth = manifest["ground_truth"]
    assert truth["component_count"] == 2
    assert len(truth["components"]) == 2
    names = {component["name"] for component in truth["components"]}
    assert names == {"squishy ball", "steamer basket container"}


def test_every_ground_truth_component_is_verified_from_photos(manifest: dict) -> None:
    """Spec 11: a fixture may not assert anything it cannot see."""
    for component in manifest["ground_truth"]["components"]:
        assert component["provenance"] == "VERIFIED_FROM_PHOTOS"


def test_unknowns_stay_unknown(manifest: dict) -> None:
    unknown = set(manifest["ground_truth"]["unknown_facts"])
    assert {"brand", "materials", "dimensions", "age_range"} <= unknown
    assert manifest["ground_truth"]["visible_branding"] == []
    assert manifest["ground_truth"]["visible_text"] == []


def test_no_retail_packaging_is_claimed(manifest: dict) -> None:
    """Spec 20: packaging is never invented, so packshot must be unavailable."""
    assert manifest["ground_truth"]["packaging_present"] is False


def test_scene_requirements_are_expressible_in_config(manifest: dict, settings: Settings) -> None:
    requirements = manifest["scene_requirements"]
    assert requirements["size_class"] in settings.scenes.size_classes
    known_environments = {
        env
        for requirement in settings.scenes.category_requirements.values()
        for env in requirement.environment
    }
    assert set(requirements["environment"]) <= known_environments


def test_squishy_category_is_configured(settings: Settings) -> None:
    squishy = settings.scenes.category_requirements.get("squishy")
    assert squishy is not None, "the fixture's category must exist in scenes.json"
    assert squishy.environment == ["indoor"]
    assert squishy.water_related is False


def test_regression_invariants_are_documented(manifest: dict) -> None:
    invariants = " ".join(manifest["must_not_regress"]).lower()
    for concern in ("component_count", "proportions", "uniform scaling", "invented"):
        assert concern in invariants


@pytest.mark.skip(reason="Phase 3: grouping engine not built yet")
def test_six_photos_group_into_one_product() -> None:
    """All six references must land in a single group with nothing unassigned."""


@pytest.mark.skip(reason="Phase 4: Qwen3-VL profile not built yet")
def test_profile_reports_two_components_and_no_branding() -> None:
    """The profile must see the ball and the basket, and claim no brand."""


@pytest.mark.skip(reason="Phase 10: semantic QC not built yet")
def test_generated_images_preserve_product_geometry() -> None:
    """Shape, colors, proportions and component count must survive generation."""
