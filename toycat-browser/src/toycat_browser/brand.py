"""The locked TTGS brand asset (spec 29, 31, 67).

The logo is never generated, never reconstructed, never approximated. It is a
file on disk with a known SHA-256.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import WatermarkConfig
from .hashing import sha256_file
from .paths import AppPaths
from .states import BrandingStatus

__all__ = ["BrandAssetCheck", "sha256_file", "verify_brand_asset"]


@dataclass(frozen=True)
class BrandAssetCheck:
    path: Path
    exists: bool
    actual_sha256: str | None
    expected_sha256: str
    status: BrandingStatus | None
    detail: str

    @property
    def ok(self) -> bool:
        return self.status is None


def verify_brand_asset(paths: AppPaths, watermark: WatermarkConfig) -> BrandAssetCheck:
    """Confirm the configured logo exists and still hashes to the pinned value."""
    asset = watermark.asset_path(paths)

    if not asset.is_file():
        return BrandAssetCheck(
            path=asset,
            exists=False,
            actual_sha256=None,
            expected_sha256=watermark.asset_sha256,
            status=BrandingStatus.FAIL_BRAND_ASSET,
            detail=(
                f"brand asset not found at {asset}. Place the official THE TOY GIFT "
                "SHOP logo there and update config/watermark.json:asset_sha256."
            ),
        )

    actual = sha256_file(asset)
    if watermark.verify_asset_hash and actual != watermark.asset_sha256:
        return BrandAssetCheck(
            path=asset,
            exists=True,
            actual_sha256=actual,
            expected_sha256=watermark.asset_sha256,
            status=BrandingStatus.FAIL_BRAND_ASSET,
            detail=(
                f"brand asset changed unexpectedly. expected {watermark.asset_sha256}, "
                f"found {actual}. If the new logo is intentional, update "
                "config/watermark.json:asset_sha256."
            ),
        )

    return BrandAssetCheck(
        path=asset,
        exists=True,
        actual_sha256=actual,
        expected_sha256=watermark.asset_sha256,
        status=None,
        detail=f"{asset.name} matches the pinned hash",
    )
