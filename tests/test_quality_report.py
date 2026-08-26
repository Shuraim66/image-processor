"""The quality report's shape, and the failure modes it must not swallow."""

import json
import os

import pytest

import quality


def test_vlm_check_fails_loudly_on_a_missing_image(tmp_path):
    """The semantic check is opt-in. Reporting 'skipped' when it could not run
    makes a broken check indistinguishable from a passing product, which is
    exactly how it sat broken behind a renamed file."""
    real = "logo.png"
    result = quality.vlm_check(real, str(tmp_path / "nope.webp"))
    assert result["status"] == "fail"
    assert "not found" in result["reason"]


def test_vlm_check_reports_a_missing_reference_too(tmp_path):
    result = quality.vlm_check(str(tmp_path / "gone.jpg"), "logo.png")
    assert result["status"] == "fail"
    assert "reference" in result["reason"]


def test_vlm_check_always_reports_which_model_it_used(tmp_path):
    result = quality.vlm_check("logo.png", str(tmp_path / "nope.webp"))
    assert "model" in result


@pytest.mark.slow
def test_report_schema(built_skus):
    for sku in built_skus:
        p = os.path.join("output", sku, "quality-report.json")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            r = json.load(fh)
        assert r["sku"] == sku
        assert r["status"] in ("pass", "review", "fail")
        assert isinstance(r["images"], list) and r["images"]
        for entry in r["images"]:
            assert "image" in entry
            for c in entry["checks"]:
                assert set(c) >= {"check", "status", "detail"}
                assert c["status"] in ("pass", "warn", "fail")
