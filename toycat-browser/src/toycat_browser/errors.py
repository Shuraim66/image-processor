"""Typed errors. Every failure mode the pipeline can hit has a name."""

from __future__ import annotations


class ToycatError(Exception):
    """Base class for every error this application raises deliberately."""

    exit_code = 1


class ConfigError(ToycatError):
    """A config file is missing, malformed, or internally inconsistent."""

    exit_code = 2


class BrandAssetError(ToycatError):
    """The locked TTGS brand asset is missing or does not match its hash."""

    exit_code = 3


class EnvironmentError_(ToycatError):
    """A required external dependency (Ollama, model, browser) is unusable."""

    exit_code = 4


class InputError(ToycatError):
    """The input folder or one of its images cannot be used."""

    exit_code = 5


class NotImplementedYetError(ToycatError):
    """A pipeline phase that has not been built yet was invoked.

    This exists so that an unbuilt stage fails loudly instead of silently
    reporting success (spec 68: no silent success).
    """

    exit_code = 10
