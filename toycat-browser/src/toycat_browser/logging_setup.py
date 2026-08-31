"""Run-scoped logging (spec 47, 61).

Three log files, one run_id per run, and a redaction filter so that a cookie,
token or password can never reach disk.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

CATALOG_LOG: Final = "catalog.log"
BROWSER_LOG: Final = "browser.log"
QC_LOG: Final = "qc.log"

_CHANNELS: Final[dict[str, str]] = {
    "toycat.catalog": CATALOG_LOG,
    "toycat.browser": BROWSER_LOG,
    "toycat.qc": QC_LOG,
}

_FORMAT = "%(asctime)s %(levelname)-8s [%(run_id)s] %(name)s: %(message)s"

#: Patterns whose *values* must never be written to a log file (spec 61).
_SECRET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i)\b(cookie|set-cookie|authorization|session[_-]?token|csrf)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|bearer)\b\s*[:=]?\s*\S+"),
    re.compile(r"(?i)\bpassw(or)?d\b\s*[:=]\s*\S+"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+"),
    re.compile(r"(?i)\b(sk|pk)-[A-Za-z0-9_\-]{16,}"),
)

REDACTED = "[REDACTED]"


class SecretRedactingFilter(logging.Filter):
    """Rewrite any record whose rendered message looks like it carries a secret."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        redacted = message
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub(REDACTED, redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


class RunIdFilter(logging.Filter):
    """Stamp every record with the current run_id."""

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "run_id"):
            record.run_id = self.run_id
        return True


def _is_closed(handler: logging.Handler) -> bool:
    """True when a handler's stream was closed out from under us."""
    stream = getattr(handler, "stream", None)
    return stream is None or getattr(stream, "closed", False)


def new_run_id(scope: str = "run") -> str:
    """A unique run id, e.g. ``2026-08-28T04-21-15Z_product-001`` (spec 47)."""
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", scope).strip("-") or "run"
    return f"{stamp}_{safe}"


def configure_logging(
    log_dir: Path,
    run_id: str,
    *,
    level: int = logging.INFO,
    console: bool = False,
) -> str:
    """Attach file handlers for the three channels. Idempotent per run_id."""
    log_dir = log_dir.resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(_FORMAT)
    redactor = SecretRedactingFilter()
    run_filter = RunIdFilter(run_id)

    for logger_name, filename in _CHANNELS.items():
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
        logger.propagate = False
        # The tag includes the directory: the same run_id writing to a different
        # log_dir is a different handler, not a reusable one.
        tag = f"toycat:{log_dir}:{filename}:{run_id}"
        if any(
            getattr(h, "_toycat_tag", None) == tag and not _is_closed(h)
            for h in logger.handlers
        ):
            continue
        for stale in [h for h in logger.handlers if getattr(h, "_toycat_tag", "").startswith("toycat:")]:
            logger.removeHandler(stale)
            stale.close()
        handler = logging.FileHandler(log_dir / filename, encoding="utf-8")
        handler.setFormatter(formatter)
        handler.addFilter(redactor)
        handler.addFilter(run_filter)
        handler._toycat_tag = tag  # type: ignore[attr-defined]
        logger.addHandler(handler)

        if console:
            stream = logging.StreamHandler()
            stream.setFormatter(formatter)
            stream.addFilter(redactor)
            stream.addFilter(run_filter)
            stream._toycat_tag = tag + ":console"  # type: ignore[attr-defined]
            logger.addHandler(stream)

    return run_id


def catalog_log() -> logging.Logger:
    return logging.getLogger("toycat.catalog")


def browser_log() -> logging.Logger:
    return logging.getLogger("toycat.browser")


def qc_log() -> logging.Logger:
    return logging.getLogger("toycat.qc")
