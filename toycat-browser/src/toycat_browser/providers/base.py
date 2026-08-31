"""The provider interface (spec 60).

Only the contract lives here. The ChatGPT browser provider is Phase 6; a future
local generator or API provider must satisfy this same interface without the
core pipeline changing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..errors import ToycatError
from ..states import ImageSlot


@dataclass(frozen=True)
class ProviderAvailability:
    """Whether a provider can actually run right now (spec 4, 43)."""

    available: bool
    detail: str
    remediation: str = ""


@dataclass(frozen=True)
class GenerationRequest:
    """One image request. One request produces exactly one image (spec 17)."""

    product_id: str
    slot: ImageSlot
    prompt: str
    reference_images: tuple[Path, ...]
    attempt: int = 1
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationResult:
    """The outcome of one image request.

    ``downloaded_path`` must point at a file that exists locally. A provider may
    never report success without one (spec 43, 68).
    """

    request: GenerationRequest
    downloaded_path: Path | None
    succeeded: bool
    detail: str
    provider_name: str

    def __post_init__(self) -> None:
        if self.succeeded and (
            self.downloaded_path is None or not self.downloaded_path.is_file()
        ):
            raise ProviderError(
                f"{self.provider_name} reported success for "
                f"{self.request.product_id}/{self.request.slot} without a downloaded "
                "file on disk (spec 43: no silent success)"
            )


class ProviderError(ToycatError):
    """A provider could not complete a request."""

    exit_code = 6


@runtime_checkable
class ImageProvider(Protocol):
    """What every image generator must offer the pipeline."""

    name: str

    def availability(self) -> ProviderAvailability:
        """Report whether generation can run, without starting any work."""
        ...

    def open_product_session(
        self, product_id: str, reference_images: tuple[Path, ...]
    ) -> None:
        """Begin one session per product and upload the references once (spec 16)."""
        ...

    def generate(self, request: GenerationRequest, destination: Path) -> GenerationResult:
        """Produce exactly one image and save it to ``destination``."""
        ...

    def close_product_session(self, product_id: str) -> None:
        """Release any session resources for the product."""
        ...


_REGISTRY: dict[str, ImageProvider] = {}


def register_provider(provider: ImageProvider) -> None:
    _REGISTRY[provider.name] = provider


def get_provider(name: str) -> ImageProvider:
    if name not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY)) or "none registered"
        raise ProviderError(f"unknown image provider {name!r} (known: {known})")
    return _REGISTRY[name]


def registered_provider_names() -> list[str]:
    return sorted(_REGISTRY)
