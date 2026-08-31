"""Environment preflight (spec 4, 43, 70, 71).

Nothing here assumes a dependency exists. Every check reports what it actually
observed and, on failure, exactly what the user should do about it.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .brand import verify_brand_asset
from .config import Settings, load_settings
from .errors import ConfigError
from .paths import AppPaths, get_paths
from .prompts import load_prompts

MIN_PYTHON = (3, 12)


class CheckStatus(StrEnum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    detail: str
    remediation: str = ""
    data: dict[str, object] = field(default_factory=dict)


@dataclass
class EnvironmentReport:
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> CheckResult:
        self.checks.append(result)
        return result

    def get(self, name: str) -> CheckResult | None:
        return next((c for c in self.checks if c.name == name), None)

    @property
    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status is CheckStatus.FAIL]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status is CheckStatus.WARN]

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checks": [
                {
                    "name": c.name,
                    "status": str(c.status),
                    "detail": c.detail,
                    "remediation": c.remediation,
                    "data": c.data,
                }
                for c in self.checks
            ],
        }


# --------------------------------------------------------------------------
# individual checks
# --------------------------------------------------------------------------


def check_python() -> CheckResult:
    version = sys.version_info
    text = f"{version.major}.{version.minor}.{version.micro} ({sys.executable})"
    if (version.major, version.minor) < MIN_PYTHON:
        return CheckResult(
            "python",
            CheckStatus.FAIL,
            text,
            f"this application requires Python >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}",
            {"version": platform.python_version(), "executable": sys.executable},
        )
    return CheckResult(
        "python", CheckStatus.OK, text,
        data={"version": platform.python_version(), "executable": sys.executable},
    )


def check_platform() -> CheckResult:
    system = platform.system()
    machine = platform.machine()
    release = platform.mac_ver()[0] or platform.release()
    detail = f"{system} {release} ({machine})"
    data = {"system": system, "release": release, "machine": machine}

    if system != "Darwin":
        return CheckResult(
            "platform", CheckStatus.WARN, detail,
            "this tool targets macOS on Apple silicon; HEIC decoding and browser "
            "control were only validated there",
            data,
        )
    if machine != "arm64":
        return CheckResult(
            "platform", CheckStatus.WARN, detail,
            "target hardware is Apple silicon (M3 Pro); performance tuning assumes it",
            data,
        )
    return CheckResult("platform", CheckStatus.OK, detail, data=data)


def check_memory(settings: Settings | None = None) -> CheckResult:
    """Report unified memory (spec 3: never run heavyweight models concurrently)."""
    total_bytes: int | None = None
    try:
        raw = subprocess.run(
            ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5
        )
        if raw.returncode == 0:
            total_bytes = int(raw.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        total_bytes = None

    if total_bytes is None:
        return CheckResult(
            "memory", CheckStatus.WARN, "unified memory size unknown",
            "could not read hw.memsize; heavy-model scheduling will use conservative defaults",
        )

    gib = total_bytes / (1024**3)
    detail = f"{gib:.0f} GiB unified memory"
    data = {"total_bytes": total_bytes, "gib": round(gib, 1)}
    if gib < 16:
        return CheckResult(
            "memory", CheckStatus.WARN, detail,
            "under 16 GiB: run only one heavyweight model at a time and expect swapping",
            data,
        )
    return CheckResult(
        "memory", CheckStatus.OK,
        detail + " — heavy local workloads are scheduled sequentially",
        data=data,
    )


def _http_json(url: str, timeout: float) -> object:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def check_ollama(settings: Settings, timeout: float = 5.0) -> CheckResult:
    host = settings.catalog.analysis.ollama_host.rstrip("/")
    binary = shutil.which("ollama")
    try:
        payload = _http_json(f"{host}/api/version", timeout)
        version = payload.get("version", "unknown") if isinstance(payload, dict) else "unknown"
        return CheckResult(
            "ollama", CheckStatus.OK, f"reachable at {host} (version {version})",
            data={"host": host, "version": version, "binary": binary},
        )
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as exc:
        remediation = (
            "start the Ollama server with `ollama serve` (or open the Ollama app)"
            if binary
            else "install Ollama from https://ollama.com/download, then run `ollama serve`"
        )
        return CheckResult(
            "ollama", CheckStatus.FAIL, f"not reachable at {host}: {exc}",
            remediation, {"host": host, "binary": binary},
        )


def check_vision_model(settings: Settings, timeout: float = 10.0) -> CheckResult:
    host = settings.catalog.analysis.ollama_host.rstrip("/")
    wanted = settings.catalog.analysis.vision_model
    try:
        payload = _http_json(f"{host}/api/tags", timeout)
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as exc:
        return CheckResult(
            "vision_model", CheckStatus.FAIL, f"could not list models: {exc}",
            f"start Ollama, then run `ollama pull {wanted}`", {"model": wanted},
        )

    models = payload.get("models", []) if isinstance(payload, dict) else []
    names = [m.get("name", "") for m in models if isinstance(m, dict)]
    if wanted in names:
        entry = next(m for m in models if m.get("name") == wanted)
        size_gb = round(entry.get("size", 0) / (1024**3), 1)
        return CheckResult(
            "vision_model", CheckStatus.OK, f"{wanted} present ({size_gb} GB)",
            data={"model": wanted, "size_gb": size_gb, "available": names},
        )
    return CheckResult(
        "vision_model", CheckStatus.FAIL,
        f"{wanted} not installed. available: {', '.join(names) or 'none'}",
        f"run `ollama pull {wanted}`", {"model": wanted, "available": names},
    )


def check_heic_support() -> CheckResult:
    """HEIC/HEIF decoding, native first, macOS `sips` as the documented fallback."""
    from .images import heic_support

    support = heic_support()
    data = {"decoder": support.decoder}
    if not support.available:
        return CheckResult("heic", CheckStatus.FAIL, support.detail, support.remediation, data)
    if support.decoder == "sips":
        return CheckResult("heic", CheckStatus.WARN, support.detail, support.remediation, data)
    return CheckResult("heic", CheckStatus.OK, support.detail, data=data)


def check_pillow() -> CheckResult:
    try:
        from PIL import Image, features  # type: ignore

        webp = features.check("webp")
        detail = f"Pillow {Image.__version__} (webp: {'yes' if webp else 'no'})"
        if not webp:
            return CheckResult(
                "pillow", CheckStatus.FAIL, detail,
                "this Pillow build cannot write WebP; reinstall Pillow from a wheel",
                {"version": Image.__version__, "webp": False},
            )
        return CheckResult(
            "pillow", CheckStatus.OK, detail,
            data={"version": Image.__version__, "webp": True},
        )
    except ImportError as exc:
        return CheckResult(
            "pillow", CheckStatus.FAIL, f"Pillow not importable: {exc}",
            "run: pip install -e '.[dev]' inside the toycat-browser virtualenv",
        )


_CHROME_APPS = (
    "/Applications/Google Chrome.app",
    "/Applications/Google Chrome Canary.app",
    "/Applications/Chromium.app",
)


def check_chrome() -> CheckResult:
    found = [path for path in _CHROME_APPS if Path(path).is_dir()]
    if not found:
        return CheckResult(
            "chrome", CheckStatus.FAIL, "no Chrome/Chromium install found",
            "install Google Chrome — the ChatGPT image generation step is driven "
            "through a Chrome browser session",
        )
    return CheckResult(
        "chrome", CheckStatus.OK, ", ".join(Path(p).name for p in found),
        data={"apps": found},
    )


def _chrome_extension_names() -> list[str]:
    """Best-effort scan of installed Chrome extension manifests."""
    base = Path.home() / "Library/Application Support/Google/Chrome"
    names: list[str] = []
    if not base.is_dir():
        return names
    for manifest in base.glob("*/Extensions/*/*/manifest.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        name = str(data.get("name", ""))
        if name:
            names.append(name)
    return names


def check_browser_operator() -> CheckResult:
    """Report whether the browser-control operator looks available (spec 4, 15).

    This process cannot itself drive Chrome. Generation is performed by the
    Claude operator (Claude in Chrome / Claude Desktop browser control) calling
    into this application. All that can be verified locally is whether the
    required pieces are installed, so that is all this reports.
    """
    claude_app = Path("/Applications/Claude.app").is_dir()
    chrome = any(Path(p).is_dir() for p in _CHROME_APPS)
    extensions = _chrome_extension_names()
    claude_ext = [n for n in extensions if "claude" in n.lower()]

    data: dict[str, object] = {
        "claude_desktop_installed": claude_app,
        "chrome_installed": chrome,
        "claude_chrome_extension_names": claude_ext,
        "verified_by": "local install inspection only",
    }

    if not chrome:
        return CheckResult(
            "browser_operator", CheckStatus.FAIL,
            "Chrome is not installed; browser-driven generation is unavailable",
            "install Google Chrome and the Claude in Chrome extension", data,
        )
    if not claude_app and not claude_ext:
        return CheckResult(
            "browser_operator", CheckStatus.WARN,
            "Chrome found, but neither Claude Desktop nor a Claude Chrome extension "
            "was detected. Local analysis, watermarking and QC still work; image "
            "generation cannot run.",
            "install Claude Desktop and the Claude in Chrome extension, grant it "
            "access to chatgpt.com, and sign in to ChatGPT in that browser profile",
            data,
        )
    if claude_ext:
        return CheckResult(
            "browser_operator", CheckStatus.OK,
            "Chrome + Claude browser extension detected "
            f"({', '.join(sorted(set(claude_ext)))}). Runtime availability is still "
            "confirmed at generation time.",
            data=data,
        )
    return CheckResult(
        "browser_operator", CheckStatus.WARN,
        "Chrome and Claude Desktop found, but no Claude Chrome extension was "
        "detected in the default Chrome profile.",
        "install the Claude in Chrome extension and grant it access to chatgpt.com",
        data,
    )


def check_filesystem(paths: AppPaths, input_dir: Path | None = None) -> CheckResult:
    """Confirm the directories the tool must write to are actually writable."""
    problems: list[str] = []
    data: dict[str, object] = {}

    for label, path in (
        ("logs", paths.logs),
        ("data", paths.data),
        ("products-output", paths.default_output),
    ):
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".toycat-write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            data[label] = f"{path} (writable)"
        except OSError as exc:
            problems.append(f"{label}: {path} is not writable ({exc})")
            data[label] = f"{path} (NOT writable)"

    for label, path in (("config", paths.config), ("prompts", paths.prompts), ("assets", paths.assets)):
        readable = path.is_dir() and os.access(path, os.R_OK)
        data[label] = f"{path} ({'readable' if readable else 'NOT readable'})"
        if not readable:
            problems.append(f"{label}: {path} is not readable")

    if input_dir is not None:
        readable = input_dir.is_dir() and os.access(input_dir, os.R_OK)
        data["input"] = f"{input_dir} ({'readable' if readable else 'NOT readable'})"
        if not readable:
            problems.append(f"input: {input_dir} is not a readable directory")

    if problems:
        return CheckResult(
            "filesystem", CheckStatus.FAIL, "; ".join(problems),
            "grant Terminal full disk access, or move the project out of a "
            "protected location (Desktop/Documents may require permission on macOS)",
            data,
        )
    return CheckResult("filesystem", CheckStatus.OK, "all required paths readable/writable", data=data)


def check_config(paths: AppPaths) -> tuple[CheckResult, Settings | None]:
    try:
        settings = load_settings(paths)
    except ConfigError as exc:
        return (
            CheckResult(
                "config", CheckStatus.FAIL, str(exc).splitlines()[0],
                "fix the reported file under config/", {"error": str(exc)},
            ),
            None,
        )
    return (
        CheckResult(
            "config", CheckStatus.OK,
            f"5 config files valid; preset={settings.catalog.preset}, "
            f"canvas={settings.catalog.canvas.width}x{settings.catalog.canvas.height}",
        ),
        settings,
    )


def check_prompts(paths: AppPaths) -> CheckResult:
    try:
        library = load_prompts(paths.prompts)
    except ConfigError as exc:
        return CheckResult(
            "prompts", CheckStatus.FAIL, str(exc),
            "restore the missing or altered template under prompts/",
        )
    return CheckResult(
        "prompts", CheckStatus.OK,
        f"product lock + {len(library.templates)} slot templates loaded",
        data={"slots": sorted(str(s) for s in library.templates)},
    )


def check_brand(paths: AppPaths, settings: Settings) -> CheckResult:
    result = verify_brand_asset(paths, settings.watermark)
    if result.ok:
        return CheckResult(
            "brand_asset", CheckStatus.OK, result.detail,
            data={"path": str(result.path), "sha256": result.actual_sha256},
        )
    return CheckResult(
        "brand_asset", CheckStatus.FAIL, result.detail, str(result.status),
        data={"path": str(result.path), "expected_sha256": result.expected_sha256,
              "actual_sha256": result.actual_sha256},
    )


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------


def run_preflight(
    paths: AppPaths | None = None,
    *,
    input_dir: Path | None = None,
    check_network: bool = True,
) -> EnvironmentReport:
    """Run every environment check. Never raises; every problem is a CheckResult."""
    paths = paths or get_paths()
    report = EnvironmentReport()

    report.add(check_python())
    report.add(check_platform())
    report.add(check_memory())
    report.add(check_filesystem(paths, input_dir))

    config_result, settings = check_config(paths)
    report.add(config_result)
    report.add(check_prompts(paths))

    if settings is not None:
        report.add(check_brand(paths, settings))
        if check_network:
            ollama = report.add(check_ollama(settings))
            if ollama.status is CheckStatus.OK:
                report.add(check_vision_model(settings))
            else:
                report.add(
                    CheckResult(
                        "vision_model", CheckStatus.FAIL,
                        "skipped: Ollama is not reachable",
                        f"start Ollama, then run `ollama pull "
                        f"{settings.catalog.analysis.vision_model}`",
                    )
                )

    report.add(check_pillow())
    report.add(check_heic_support())
    report.add(check_chrome())
    report.add(check_browser_operator())
    return report
