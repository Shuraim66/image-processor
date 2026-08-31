"""The TTGS logo is a locked asset (spec 29, 31, 67)."""

from __future__ import annotations

from PIL import Image

from toycat_browser.brand import sha256_file, verify_brand_asset
from toycat_browser.config import Settings, load_settings
from toycat_browser.paths import AppPaths
from toycat_browser.states import BrandingStatus


def test_shipped_logo_matches_its_pinned_hash(paths: AppPaths, settings: Settings) -> None:
    result = verify_brand_asset(paths, settings.watermark)
    assert result.ok, result.detail
    assert result.actual_sha256 == settings.watermark.asset_sha256


def test_logo_has_an_alpha_channel(paths: AppPaths, settings: Settings) -> None:
    """Watermark verification relies on the logo's own alpha (spec 31)."""
    with Image.open(settings.watermark.asset_path(paths)) as image:
        assert image.mode in {"RGBA", "LA", "P"}
        assert "transparency" in image.info or image.mode in {"RGBA", "LA"}


def test_changed_logo_fails_brand_asset(app_copy: AppPaths) -> None:
    settings = load_settings(app_copy)
    asset = settings.watermark.asset_path(app_copy)
    asset.write_bytes(asset.read_bytes() + b"tampered")

    result = verify_brand_asset(app_copy, settings.watermark)
    assert not result.ok
    assert result.status is BrandingStatus.FAIL_BRAND_ASSET
    assert "changed unexpectedly" in result.detail


def test_missing_logo_fails_brand_asset(app_copy: AppPaths) -> None:
    settings = load_settings(app_copy)
    settings.watermark.asset_path(app_copy).unlink()

    result = verify_brand_asset(app_copy, settings.watermark)
    assert not result.ok
    assert result.status is BrandingStatus.FAIL_BRAND_ASSET
    assert "not found" in result.detail


def test_hash_helper_is_stable(tmp_path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(b"toy gift shop")
    assert sha256_file(path) == sha256_file(path)
    assert len(sha256_file(path)) == 64
