"""Run-scoped logging and secret redaction (spec 47, 61)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from toycat_browser.logging_setup import (
    BROWSER_LOG,
    CATALOG_LOG,
    QC_LOG,
    REDACTED,
    browser_log,
    catalog_log,
    configure_logging,
    new_run_id,
    qc_log,
)


def test_run_id_shape() -> None:
    run_id = new_run_id("product-001")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z_product-001", run_id)


def test_run_ids_are_filesystem_safe() -> None:
    assert "/" not in new_run_id("products-input/../etc")
    assert " " not in new_run_id("some scope")


def test_three_channels_write_three_files(tmp_path: Path) -> None:
    run_id = configure_logging(tmp_path, new_run_id("test"))
    catalog_log().info("grouping decision recorded")
    browser_log().info("generation request sent")
    qc_log().info("watermark verified")
    logging.shutdown()

    for name, needle in (
        (CATALOG_LOG, "grouping decision"),
        (BROWSER_LOG, "generation request"),
        (QC_LOG, "watermark verified"),
    ):
        text = (tmp_path / name).read_text(encoding="utf-8")
        assert needle in text
        assert run_id in text


@pytest.mark.parametrize(
    "message",
    [
        "Cookie: __Secure-next-auth.session-token=abc123def456",
        "authorization: Bearer sk-proj-0123456789abcdefghij",
        "api_key=sk-abcdefghijklmnopqrstuvwxyz012345",
        "password: hunter2correct",
        "token eyJhbGciOiJIUzI1NiIs.eyJzdWIiOiIxMjM0NTY.SflKxwRJSMeKKF2QT4",
    ],
)
def test_secrets_never_reach_disk(tmp_path: Path, message: str) -> None:
    configure_logging(tmp_path, new_run_id("secrets"))
    browser_log().info("browser step: %s", message)
    logging.shutdown()

    text = (tmp_path / BROWSER_LOG).read_text(encoding="utf-8")
    assert REDACTED in text
    for fragment in ("abc123def456", "hunter2correct", "sk-proj-0123456789abcdefghij",
                     "sk-abcdefghijklmnopqrstuvwxyz012345", "SflKxwRJSMeKKF2QT4"):
        assert fragment not in text


def test_ordinary_messages_are_not_mangled(tmp_path: Path) -> None:
    configure_logging(tmp_path, new_run_id("plain"))
    catalog_log().info("downloaded 04-detail.webp for product-001 (attempt 2)")
    logging.shutdown()

    text = (tmp_path / CATALOG_LOG).read_text(encoding="utf-8")
    assert "downloaded 04-detail.webp for product-001 (attempt 2)" in text
    assert REDACTED not in text


def test_reconfiguring_does_not_duplicate_handlers(tmp_path: Path) -> None:
    configure_logging(tmp_path, new_run_id("a"))
    configure_logging(tmp_path, new_run_id("b"))
    handlers = [h for h in catalog_log().handlers if hasattr(h, "_toycat_tag")]
    assert len(handlers) == 1
