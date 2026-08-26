"""Product discovery and the profile schema everything downstream reads."""

import json
import os

import pytest
from pydantic import ValidationError

import analyzer
import process_products as pp


def test_discovery_finds_the_product_folders():
    skus = pp.find_sku_folders("input")
    assert skus == sorted(skus), "discovery order must be stable"
    assert all(os.path.isdir(os.path.join("input", s)) for s in skus)


def test_discovery_raises_on_a_missing_root():
    with pytest.raises(FileNotFoundError):
        pp.find_sku_folders("no-such-input-dir")


def test_profile_round_trips():
    p = analyzer.ProductProfile(
        sku="TTGS-TEST-1", source="test", name="TEST", title="Test Toy",
        tagline_top="A", tagline_sub="B", description="C",
        bullet_points=["b"], features=[analyzer.Feature(icon="shield", label="X\nY")],
        whats_included=["one"], seo_title="s", meta_description="m",
        tags=["t"], alt_text="a", info_title="i", ribbon="r", callout="c",
        detail_caption="d", scene_prompts=["p1", "p2"])
    again = analyzer.ProductProfile.model_validate_json(p.model_dump_json())
    assert again == p


def test_profile_requires_its_copy_fields():
    with pytest.raises(ValidationError):
        analyzer.ProductProfile(sku="X")


def test_optional_fields_default_empty():
    """review_flags and packaging_photos are added by later stages, so a profile
    written before those stages ran must still load."""
    p = analyzer.ProductProfile(
        name="N", title="T", tagline_top="a", tagline_sub="b", description="c",
        bullet_points=[], features=[], whats_included=[], seo_title="s",
        meta_description="m", tags=[], alt_text="a", info_title="i",
        ribbon="r", callout="c", detail_caption="d", scene_prompts=[])
    assert p.review_flags == [] and p.packaging_photos == [] and p.theme == {}


@pytest.mark.slow
def test_every_built_product_has_a_valid_profile(built_skus):
    for sku in built_skus:
        path = os.path.join("output", sku, "product.json")
        if not os.path.exists(path):
            continue
        prof = analyzer.ProductProfile.model_validate_json(
            open(path, encoding="utf-8").read())
        assert prof.title.strip(), f"{sku} has no title"
        assert prof.source, f"{sku} does not record which model wrote it"


@pytest.mark.slow
def test_no_product_ships_placeholder_copy(built_skus):
    """Fallback copy is deterministic filler, not a description of the product.
    It is allowed through only behind --allow-fallback, and never silently."""
    for sku in built_skus:
        path = os.path.join("output", sku, "product.json")
        if not os.path.exists(path):
            continue
        prof = analyzer.ProductProfile.model_validate_json(
            open(path, encoding="utf-8").read())
        if prof.source.startswith("fallback"):
            report = os.path.join("output", sku, "quality-report.json")
            with open(report, encoding="utf-8") as fh:
                assert json.load(fh)["status"] == "review", \
                    f"{sku} has placeholder copy but is not flagged"
