"""The provider contract (spec 43, 60, 68)."""

from __future__ import annotations

from pathlib import Path

import pytest

from toycat_browser.providers.base import (
    GenerationRequest,
    GenerationResult,
    ImageProvider,
    ProviderAvailability,
    ProviderError,
    get_provider,
    register_provider,
    registered_provider_names,
)
from toycat_browser.states import ImageSlot


class _Stub:
    name = "stub"

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(available=True, detail="stub")

    def open_product_session(self, product_id: str, reference_images: tuple[Path, ...]) -> None:
        pass

    def generate(self, request: GenerationRequest, destination: Path) -> GenerationResult:
        raise NotImplementedError

    def close_product_session(self, product_id: str) -> None:
        pass


def _request(tmp_path: Path) -> GenerationRequest:
    return GenerationRequest(
        product_id="product-001",
        slot=ImageSlot.DETAIL,
        prompt="PRODUCT IDENTITY IS LOCKED.",
        reference_images=(tmp_path / "front.jpg",),
    )


def test_stub_satisfies_the_protocol() -> None:
    assert isinstance(_Stub(), ImageProvider)


def test_success_without_a_downloaded_file_is_rejected(tmp_path: Path) -> None:
    """Spec 43: never mark a task complete unless the image exists locally."""
    with pytest.raises(ProviderError, match="no silent success"):
        GenerationResult(
            request=_request(tmp_path),
            downloaded_path=None,
            succeeded=True,
            detail="looks good to me",
            provider_name="stub",
        )


def test_success_with_a_missing_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProviderError):
        GenerationResult(
            request=_request(tmp_path),
            downloaded_path=tmp_path / "never-written.webp",
            succeeded=True,
            detail="",
            provider_name="stub",
        )


def test_success_with_a_real_file_is_accepted(tmp_path: Path) -> None:
    downloaded = tmp_path / "raw.png"
    downloaded.write_bytes(b"\x89PNG")
    result = GenerationResult(
        request=_request(tmp_path),
        downloaded_path=downloaded,
        succeeded=True,
        detail="downloaded",
        provider_name="stub",
    )
    assert result.succeeded


def test_failure_needs_no_file(tmp_path: Path) -> None:
    result = GenerationResult(
        request=_request(tmp_path),
        downloaded_path=None,
        succeeded=False,
        detail="generation timed out",
        provider_name="stub",
    )
    assert not result.succeeded


def test_one_request_carries_one_slot(tmp_path: Path) -> None:
    """Spec 17: six separate images, never one sheet."""
    request = _request(tmp_path)
    assert isinstance(request.slot, ImageSlot)


def test_registry_round_trip() -> None:
    register_provider(_Stub())
    try:
        assert "stub" in registered_provider_names()
        assert get_provider("stub").name == "stub"
    finally:
        from toycat_browser.providers import base

        base._REGISTRY.pop("stub", None)


def test_unknown_provider_is_an_error() -> None:
    with pytest.raises(ProviderError, match="unknown image provider"):
        get_provider("midjourney")
