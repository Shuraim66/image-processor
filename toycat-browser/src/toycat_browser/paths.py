"""Filesystem layout for the application (spec 37, 45, 46, 47, 50).

The application root is the directory that owns config/, prompts/ and assets/.
Resolution order:
  1. $TOYCAT_HOME
  2. the directory the installed package was checked out into (editable install)
  3. the current working directory
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError

_MARKERS = ("config", "prompts", "assets")


def _looks_like_app_root(path: Path) -> bool:
    return all((path / marker).is_dir() for marker in _MARKERS)


def find_app_root() -> Path:
    """Locate the application root, or raise ConfigError with what was tried."""
    tried: list[Path] = []

    env = os.environ.get("TOYCAT_HOME")
    if env:
        candidate = Path(env).expanduser().resolve()
        if _looks_like_app_root(candidate):
            return candidate
        tried.append(candidate)

    # src/toycat_browser/paths.py -> src/toycat_browser -> src -> <app root>
    packaged = Path(__file__).resolve().parents[2]
    if _looks_like_app_root(packaged):
        return packaged
    tried.append(packaged)

    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if _looks_like_app_root(candidate):
            return candidate
    tried.append(cwd)

    raise ConfigError(
        "Could not locate the toycat application root (a directory containing "
        f"{', '.join(_MARKERS)}). Tried: "
        + "; ".join(str(p) for p in tried)
        + ". Set TOYCAT_HOME to the toycat-browser directory."
    )


@dataclass(frozen=True)
class AppPaths:
    """Every directory the application reads or writes."""

    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def prompts(self) -> Path:
        return self.root / "prompts"

    @property
    def assets(self) -> Path:
        return self.root / "assets"

    @property
    def brand(self) -> Path:
        return self.assets / "brand"

    @property
    def backgrounds(self) -> Path:
        return self.assets / "backgrounds"

    @property
    def scenes(self) -> Path:
        return self.assets / "scenes"

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def working(self) -> Path:
        """Scratch space for the whole app; safe to delete (spec 50)."""
        return self.root / "working"

    @property
    def scan_dir(self) -> Path:
        return self.working / "scan"

    @property
    def scan_manifest(self) -> Path:
        return self.scan_dir / "scan.json"

    @property
    def normalized_dir(self) -> Path:
        """EXIF-corrected, metadata-stripped working copies of input photos."""
        return self.scan_dir / "normalized"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def sku_registry(self) -> Path:
        return self.data / "sku-registry.json"

    @property
    def default_input(self) -> Path:
        return self.root / "products-input"

    @property
    def default_output(self) -> Path:
        return self.root / "products-output"

    def product_dir(self, output_root: Path, product_id: str) -> Path:
        return output_root / product_id

    def ensure_writable_dirs(self) -> None:
        """Create the directories the application owns. Never touches inputs."""
        for path in (self.data, self.logs, self.default_output):
            path.mkdir(parents=True, exist_ok=True)


def product_layout(product_dir: Path) -> dict[str, Path]:
    """The per-product folder structure from spec 37."""
    working = product_dir / "working"
    return {
        "root": product_dir,
        "input_reference": product_dir / "input-reference",
        "working": working,
        "grouping": working / "grouping.json",
        "profile": working / "product-profile.json",
        "state": working / "state.json",
        "prompts": working / "prompts",
        "downloaded": working / "downloaded",
        "qc": working / "qc",
        "output": product_dir / "output",
    }


def get_paths() -> AppPaths:
    return AppPaths(root=find_app_root())
