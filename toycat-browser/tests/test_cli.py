"""The command surface (spec 41). Unbuilt commands must fail loudly."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from toycat_browser.cli import app
from toycat_browser.errors import NotImplementedYetError

runner = CliRunner()

REQUIRED_COMMANDS = ["scan", "group", "analyze", "generate", "validate", "run", "batch", "retry"]
BUILT = {"scan"}
NOT_BUILT_YET = [c for c in REQUIRED_COMMANDS if c not in BUILT] + ["cleanup"]


def test_help_lists_every_required_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in REQUIRED_COMMANDS:
        assert command in result.output


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "toycat-browser" in result.output


def test_config_renders(monkeypatch) -> None:
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0, result.output
    assert "toy_catalog" in result.output
    assert "01-catalog-hero.webp" in result.output


def test_config_json_is_machine_readable() -> None:
    result = runner.invoke(app, ["config", "watermark"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["position"] == "bottom_right"
    assert payload["mandatory"] is True


def test_unknown_config_section_is_rejected() -> None:
    result = runner.invoke(app, ["config", "nonsense"])
    assert result.exit_code != 0


def test_prompts_lists_slots_and_placeholders() -> None:
    result = runner.invoke(app, ["prompts"])
    assert result.exit_code == 0, result.output
    assert "catalog_hero" in result.output
    assert "PRODUCT_LOCK" in result.output


def test_prompts_can_print_one_template() -> None:
    result = runner.invoke(app, ["prompts", "lifestyle"])
    assert result.exit_code == 0
    assert "TASK: Lifestyle" in result.output


def test_doctor_json_reports_every_check() -> None:
    result = runner.invoke(app, ["doctor", "--json", "--offline"])
    payload = json.loads(result.output)
    names = {check["name"] for check in payload["checks"]}
    assert {"python", "platform", "config", "prompts", "brand_asset",
            "filesystem", "chrome", "browser_operator"} <= names


@pytest.mark.parametrize("command", NOT_BUILT_YET)
def test_unbuilt_commands_refuse_rather_than_pretend(command: str) -> None:
    """Spec 68: nothing may report success it did not achieve."""
    args = [command]
    if command == "retry":
        args.append("products-output/product-001")
    result = runner.invoke(app, args)
    assert result.exit_code != 0
    assert isinstance(result.exception, (NotImplementedYetError, SystemExit))
    if isinstance(result.exception, NotImplementedYetError):
        assert "Phase" in str(result.exception)


def test_scan_reports_a_real_folder(dumpling_fixture) -> None:
    result = runner.invoke(app, ["scan", str(dumpling_fixture), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["usable"] == 6
    assert payload["manifest_version"] == 1


def test_scan_renders_a_summary(dumpling_fixture) -> None:
    result = runner.invoke(app, ["scan", str(dumpling_fixture)])
    assert result.exit_code == 0, result.output
    assert "6" in result.output
    assert "all images usable" in result.output


def test_scan_on_an_empty_folder_fails_with_guidance(tmp_path) -> None:
    """An empty inbox is a user error, not a silent success (spec 68)."""
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(app, ["scan", str(empty)])
    assert result.exit_code != 0
    assert "no usable images found" in str(result.exception)


def test_scan_on_a_missing_folder_fails(tmp_path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path / "nope")])
    assert result.exit_code != 0
    assert "input folder not found" in str(result.exception)


def test_batch_is_available_as_a_command() -> None:
    result = runner.invoke(app, ["batch", "--help"])
    assert result.exit_code == 0
    assert "INPUT_DIR" in result.output
