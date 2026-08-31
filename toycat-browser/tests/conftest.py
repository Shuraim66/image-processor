"""Shared fixtures. Tests read the real config/prompts/assets shipped with the app."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from toycat_browser.config import Settings, load_settings
from toycat_browser.paths import AppPaths, find_app_root

CONFIG_NAMES = ("catalog", "watermark", "grouping", "qc", "scenes")


@pytest.fixture(scope="session")
def app_root() -> Path:
    return find_app_root()


@pytest.fixture(scope="session")
def paths(app_root: Path) -> AppPaths:
    return AppPaths(root=app_root)


@pytest.fixture(scope="session")
def settings(paths: AppPaths) -> Settings:
    return load_settings(paths)


@pytest.fixture
def app_copy(tmp_path: Path, app_root: Path) -> AppPaths:
    """A throwaway copy of config/, prompts/ and assets/ that a test may mutate."""
    root = tmp_path / "app"
    for name in ("config", "prompts"):
        shutil.copytree(app_root / name, root / name)
    shutil.copytree(app_root / "assets", root / "assets")
    return AppPaths(root=root)


@pytest.fixture
def write_config(app_copy: AppPaths):
    """Patch one key inside one config file of the throwaway app copy."""

    def _write(name: str, mutate) -> AppPaths:
        path = app_copy.config / f"{name}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        mutate(data)
        path.write_text(json.dumps(data), encoding="utf-8")
        return app_copy

    return _write


@pytest.fixture(scope="session")
def dumpling_fixture() -> Path:
    """The mandatory blue Dumpling/Squishy regression fixture (spec 64)."""
    return Path(__file__).parent / "fixtures" / "dumpling"
