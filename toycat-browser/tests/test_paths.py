"""Application layout (spec 37, 50)."""

from __future__ import annotations

from pathlib import Path

import pytest

from toycat_browser.errors import ConfigError
from toycat_browser.paths import AppPaths, find_app_root, product_layout


def test_app_root_owns_config_prompts_assets(paths: AppPaths) -> None:
    for directory in (paths.config, paths.prompts, paths.assets, paths.brand):
        assert directory.is_dir()


def test_toycat_home_overrides_discovery(monkeypatch, app_copy: AppPaths) -> None:
    monkeypatch.setenv("TOYCAT_HOME", str(app_copy.root))
    assert find_app_root() == app_copy.root.resolve()


def test_unusable_toycat_home_falls_back_rather_than_crashing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TOYCAT_HOME", str(tmp_path / "nope"))
    assert find_app_root().is_dir()


def test_missing_root_is_a_readable_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TOYCAT_HOME", str(tmp_path))
    monkeypatch.setattr("toycat_browser.paths._looks_like_app_root", lambda _p: False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="TOYCAT_HOME"):
        find_app_root()


def test_product_layout_matches_spec_37(tmp_path: Path) -> None:
    layout = product_layout(tmp_path / "product-001")
    assert layout["input_reference"].name == "input-reference"
    assert layout["grouping"].relative_to(tmp_path).as_posix() == "product-001/working/grouping.json"
    assert layout["profile"].name == "product-profile.json"
    assert layout["state"].name == "state.json"
    assert layout["downloaded"].name == "downloaded"
    assert layout["qc"].name == "qc"
    assert layout["output"].name == "output"


def test_ensure_writable_dirs_never_touches_input(tmp_path: Path) -> None:
    root = tmp_path / "app"
    for name in ("config", "prompts", "assets"):
        (root / name).mkdir(parents=True)
    paths = AppPaths(root=root)
    paths.ensure_writable_dirs()

    assert paths.logs.is_dir() and paths.data.is_dir() and paths.default_output.is_dir()
    assert not paths.default_input.exists()
