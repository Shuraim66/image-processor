"""Prompt templates (spec 13, 45).

Templates live in prompts/*.txt so they can be tuned without touching code.
Placeholders are ``{{TOKEN}}``; rendering is explicit token substitution so
literal braces in a prompt are never misread as format fields.

Every generation prompt must carry PRODUCT_LOCK. render() enforces that rather
than trusting the template author to remember.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError
from .states import ImageSlot

PRODUCT_LOCK_FILE = "product-lock.txt"
PRODUCT_LOCK_TOKEN = "PRODUCT_LOCK"

TEMPLATE_FILES: dict[ImageSlot, str] = {
    ImageSlot.CATALOG_HERO: "catalog-hero.txt",
    ImageSlot.WHITE_BACKGROUND: "white-background.txt",
    ImageSlot.PACKSHOT: "packshot.txt",
    ImageSlot.DETAIL: "detail.txt",
    ImageSlot.LIFESTYLE: "lifestyle.txt",
    ImageSlot.FEATURE_CARD: "feature-card.txt",
}

_TOKEN_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")

#: A short, stable phrase that must survive into every rendered prompt.
_LOCK_SENTINEL = "PRODUCT IDENTITY IS LOCKED."


@dataclass(frozen=True)
class PromptLibrary:
    """Loaded prompt templates for one run."""

    product_lock: str
    templates: dict[ImageSlot, str]

    def tokens_for(self, slot: ImageSlot) -> set[str]:
        """Placeholders a slot's template needs, excluding PRODUCT_LOCK."""
        found = set(_TOKEN_RE.findall(self.templates[slot]))
        found.discard(PRODUCT_LOCK_TOKEN)
        return found

    def render(self, slot: ImageSlot, values: dict[str, object]) -> str:
        """Render a slot's prompt. Raises if a token is unresolved.

        An unresolved token would otherwise be sent verbatim to the image
        generator, which is a silent quality failure.
        """
        if slot not in self.templates:
            raise ConfigError(f"no prompt template registered for slot {slot}")

        substitutions = {PRODUCT_LOCK_TOKEN: self.product_lock}
        for key, value in values.items():
            substitutions[key] = _stringify(value)

        missing: set[str] = set()

        def replace(match: re.Match[str]) -> str:
            token = match.group(1)
            if token not in substitutions:
                missing.add(token)
                return match.group(0)
            return substitutions[token]

        rendered = _TOKEN_RE.sub(replace, self.templates[slot])

        if missing:
            raise ConfigError(
                f"prompt {TEMPLATE_FILES[slot]} has unresolved placeholders: "
                + ", ".join(sorted(missing))
            )
        if _LOCK_SENTINEL not in rendered:
            raise ConfigError(
                f"rendered prompt for {slot} does not contain the product lock "
                "(spec 13: the lock is mandatory on every generation request)"
            )
        return rendered


def _stringify(value: object) -> str:
    if value is None:
        return "not specified"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple, set)):
        items = [_stringify(item) for item in value]
        return ", ".join(items) if items else "none"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def load_prompts(prompts_dir: Path) -> PromptLibrary:
    """Read every template from disk, failing loudly on a missing file."""
    lock_path = prompts_dir / PRODUCT_LOCK_FILE
    if not lock_path.is_file():
        raise ConfigError(f"missing mandatory prompt: {lock_path}")
    product_lock = lock_path.read_text(encoding="utf-8").strip()
    if _LOCK_SENTINEL not in product_lock:
        raise ConfigError(
            f"{lock_path} does not contain {_LOCK_SENTINEL!r}; the product lock "
            "has been altered or truncated"
        )

    templates: dict[ImageSlot, str] = {}
    for slot, filename in TEMPLATE_FILES.items():
        path = prompts_dir / filename
        if not path.is_file():
            raise ConfigError(f"missing prompt template for {slot}: {path}")
        text = path.read_text(encoding="utf-8")
        if f"{{{{{PRODUCT_LOCK_TOKEN}}}}}" not in text:
            raise ConfigError(
                f"{path} does not include {{{{{PRODUCT_LOCK_TOKEN}}}}}; "
                "spec 13 requires the lock in every generation request"
            )
        templates[slot] = text

    return PromptLibrary(product_lock=product_lock, templates=templates)
