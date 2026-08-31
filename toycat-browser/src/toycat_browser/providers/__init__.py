"""Image-generation providers (spec 60). The default is ``chatgpt_browser``."""

from .base import (
    GenerationRequest,
    GenerationResult,
    ImageProvider,
    ProviderAvailability,
    get_provider,
    register_provider,
)

__all__ = [
    "GenerationRequest",
    "GenerationResult",
    "ImageProvider",
    "ProviderAvailability",
    "get_provider",
    "register_provider",
]
