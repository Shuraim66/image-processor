"""The ``toycat`` command line (spec 41, 42).

Phase 1 ships the skeleton: environment preflight, configuration inspection and
the command surface. Pipeline commands that have not been built yet exit with a
clear message naming the phase that implements them — they never pretend to
succeed (spec 68).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .config import Settings, load_settings
from .environment import CheckStatus, EnvironmentReport, run_preflight
from .errors import InputError, NotImplementedYetError, ToycatError
from .logging_setup import catalog_log, configure_logging, new_run_id
from .paths import AppPaths, get_paths
from .prompts import load_prompts
from .providers import base as provider_base
from .scan import scan_folder, write_manifest
from .states import CATALOG_SLOT_ORDER, CANONICAL_FILENAMES, ImageStatus

BANNER_TITLE = "THE TOY GIFT SHOP"
BANNER_SUBTITLE = "LOCAL PRODUCT CATALOG GENERATOR"

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=f"{BANNER_TITLE} — {BANNER_SUBTITLE.lower()}.",
    rich_markup_mode="rich",
)

InputArg = Annotated[
    Optional[Path],
    typer.Argument(
        metavar="INPUT_DIR",
        help="Folder of raw product photos. Defaults to products-input/.",
    ),
]

_STATUS_STYLE = {
    CheckStatus.OK: "green",
    CheckStatus.WARN: "yellow",
    CheckStatus.FAIL: "red",
}
_STATUS_GLYPH = {CheckStatus.OK: "✓", CheckStatus.WARN: "!", CheckStatus.FAIL: "✗"}


def _banner() -> None:
    console.print(
        Panel(
            Text(BANNER_TITLE, style="bold") + Text(f"\n{BANNER_SUBTITLE}", style="dim"),
            expand=False,
            border_style="cyan",
        )
    )


def _resolve_input(paths: AppPaths, value: Path | None) -> Path:
    return (value or paths.default_input).expanduser().resolve()


def _load(paths: AppPaths) -> Settings:
    return load_settings(paths)


def _not_built(command: str, phase: str, builds_on: str) -> None:
    raise NotImplementedYetError(
        f"`toycat {command}` is not implemented yet — it lands in {phase} ({builds_on}).\n"
        "Phase 1 is the scaffold: run `toycat doctor` to verify the environment and "
        "`toycat config` to inspect the validated settings."
    )


# --------------------------------------------------------------------------
# working commands
# --------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Print the application version."""
    console.print(f"toycat-browser {__version__}")


@app.command()
def doctor(
    input_dir: InputArg = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit the report as JSON.")] = False,
    offline: Annotated[bool, typer.Option("--offline", help="Skip Ollama network checks.")] = False,
) -> None:
    """Verify Python, Ollama, the vision model, browser control and permissions."""
    paths = get_paths()
    target = _resolve_input(paths, input_dir)
    report = run_preflight(paths, input_dir=target, check_network=not offline)

    if json_output:
        console.print_json(json.dumps(report.to_dict()))
    else:
        _banner()
        _render_report(report, paths, target)

    if not report.ok:
        raise typer.Exit(code=4)


def _render_report(report: EnvironmentReport, paths: AppPaths, input_dir: Path) -> None:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("", width=1)
    table.add_column("check", style="bold")
    table.add_column("detail", overflow="fold")

    for check in report.checks:
        style = _STATUS_STYLE[check.status]
        table.add_row(
            Text(_STATUS_GLYPH[check.status], style=style),
            check.name,
            Text(check.detail, style="" if check.status is CheckStatus.OK else style),
        )
    console.print(table)

    remediations = [c for c in report.checks if c.remediation and c.status is not CheckStatus.OK]
    if remediations:
        console.print()
        console.print("[bold]What to do[/bold]")
        for check in remediations:
            console.print(f"  [{_STATUS_STYLE[check.status]}]{check.name}[/]: {check.remediation}")

    console.print()
    console.print(f"[dim]app root  [/dim] {paths.root}")
    console.print(f"[dim]input     [/dim] {input_dir}")
    console.print(f"[dim]output    [/dim] {paths.default_output}")
    console.print(f"[dim]logs      [/dim] {paths.logs}")
    console.print()
    if report.ok:
        console.print("[green]environment OK[/green]" + (
            f" [yellow]({len(report.warnings)} warning(s))[/yellow]" if report.warnings else ""
        ))
    else:
        console.print(f"[red]{len(report.failures)} check(s) failed[/red]")


@app.command(name="config")
def show_config(
    section: Annotated[Optional[str], typer.Argument(help="catalog | watermark | grouping | qc | scenes")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit raw JSON.")] = False,
) -> None:
    """Show the validated configuration."""
    paths = get_paths()
    settings = _load(paths)

    if section:
        if not hasattr(settings, section):
            raise ToycatError(
                f"unknown config section {section!r}; expected one of: "
                "catalog, watermark, grouping, qc, scenes"
            )
        payload = getattr(settings, section).model_dump(mode="json")
    else:
        payload = settings.model_dump(mode="json")

    if json_output or section:
        console.print_json(json.dumps(payload))
        return

    catalog = settings.catalog
    table = Table(box=None, show_header=False, pad_edge=False)
    table.add_column(style="dim")
    table.add_column()
    table.add_row("preset", catalog.preset)
    table.add_row("brand", catalog.brand_name)
    table.add_row("sku prefix", catalog.sku_prefix)
    table.add_row("canvas", f"{catalog.canvas.width}x{catalog.canvas.height} "
                            f"{catalog.canvas.aspect_ratio} {catalog.canvas.color_profile} "
                            f"{catalog.canvas.output_format}")
    table.add_row("provider", catalog.generation.provider)
    table.add_row("vision model", catalog.analysis.vision_model)
    table.add_row("placement", f"anchor={catalog.placement.anchor} "
                               f"width={catalog.placement.target_width_ratio} "
                               f"margin={catalog.placement.min_margin}")
    table.add_row("watermark", f"{settings.watermark.asset} @ "
                               f"{settings.watermark.opacity:.0%} opacity, "
                               f"{settings.watermark.width_ratio:.0%} width, "
                               f"{settings.watermark.position}")
    table.add_row("grouping", f"auto>={settings.grouping.auto_group_threshold} "
                              f"ambiguous {settings.grouping.ambiguous_low}-{settings.grouping.ambiguous_high} "
                              f"different<{settings.grouping.different_product_threshold}")
    table.add_row("retry", f"max {settings.qc.retry.max_attempts} attempts, then "
                           f"{settings.qc.retry.on_exhausted_status}")
    console.print(table)

    console.print()
    slots = Table(title="catalog set", box=None, header_style="bold")
    slots.add_column("#")
    slots.add_column("slot")
    slots.add_column("output file")
    slots.add_column("required")
    for entry in catalog.ordered_images:
        slots.add_row(str(entry.index), str(entry.slot), entry.filename,
                      "yes" if entry.required else "no")
    console.print(slots)


@app.command()
def prompts(
    slot: Annotated[Optional[str], typer.Argument(help="Show one slot's template.")] = None,
) -> None:
    """List prompt templates and the placeholders they expect."""
    paths = get_paths()
    library = load_prompts(paths.prompts)

    if slot:
        matches = [s for s in CATALOG_SLOT_ORDER if str(s) == slot]
        if not matches:
            raise ToycatError(
                f"unknown slot {slot!r}; expected one of: "
                + ", ".join(str(s) for s in CATALOG_SLOT_ORDER)
            )
        console.print(library.templates[matches[0]])
        return

    table = Table(box=None, header_style="bold")
    table.add_column("slot")
    table.add_column("file")
    table.add_column("output")
    table.add_column("placeholders", overflow="fold")
    from .prompts import TEMPLATE_FILES

    for entry in CATALOG_SLOT_ORDER:
        table.add_row(
            str(entry),
            TEMPLATE_FILES[entry],
            CANONICAL_FILENAMES[entry],
            ", ".join(sorted(library.tokens_for(entry))) or "—",
        )
    console.print(table)
    console.print()
    console.print("[dim]PRODUCT_LOCK is injected into every template automatically.[/dim]")


@app.command()
def providers() -> None:
    """List registered image-generation providers and their availability."""
    names = provider_base.registered_provider_names()
    settings = _load(get_paths())
    configured = settings.catalog.generation.provider

    table = Table(box=None, header_style="bold")
    table.add_column("provider")
    table.add_column("configured")
    table.add_column("status", overflow="fold")
    if not names:
        table.add_row(configured, "yes", "not registered yet — Phase 6 (browser controller)")
    else:
        for name in names:
            availability = provider_base.get_provider(name).availability()
            table.add_row(
                name,
                "yes" if name == configured else "",
                availability.detail,
            )
    console.print(table)


# --------------------------------------------------------------------------
# pipeline commands — declared now, built in later phases
# --------------------------------------------------------------------------


@app.command()
def scan(
    input_dir: InputArg = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit the manifest as JSON.")] = False,
    normalize: Annotated[bool, typer.Option("--normalize", help="Also write EXIF-corrected, metadata-stripped working copies.")] = False,
    show_all: Annotated[bool, typer.Option("--all", help="List every image, not just problems.")] = False,
) -> None:
    """Discover and validate images in the input folder."""
    paths = get_paths()
    settings = _load(paths)
    target = _resolve_input(paths, input_dir)

    report = scan_folder(target, settings, paths=paths, normalize_copies=normalize)
    manifest = write_manifest(report, paths.scan_manifest)

    if json_output:
        console.print_json(json.dumps(report.to_dict()))
    else:
        _banner()
        _render_scan(report, manifest, show_all=show_all)

    if not report.usable:
        raise InputError(
            f"no usable images found in {target}. Drop product photos "
            "(JPG, PNG, WEBP, HEIC) into that folder and run scan again."
        )


def _render_scan(report, manifest: Path, *, show_all: bool) -> None:
    console.print(f"Scanning {report.input_dir}...")
    console.print()

    if not report.records:
        console.print("[yellow]no images found[/yellow]")
    else:
        console.print(f"[bold]{len(report.records)}[/bold] images found")

    problems = report.unusable
    listed = report.records if show_all else problems
    if listed:
        table = Table(box=None, header_style="bold", pad_edge=False)
        table.add_column("file", overflow="fold")
        table.add_column("format")
        table.add_column("dimensions")
        table.add_column("captured")
        table.add_column("status")
        table.add_column("note", overflow="fold")
        for record in listed:
            style = "" if record.usable else "yellow"
            dimensions = f"{record.width}x{record.height}" if record.width else "—"
            captured = record.captured_at.strftime("%Y-%m-%d %H:%M:%S") if record.captured_at else "—"
            table.add_row(
                record.relative_path,
                record.image_format or "—",
                dimensions,
                captured,
                Text(str(record.status), style=style),
                "; ".join(record.issues) or "",
            )
        console.print()
        console.print(table)

    console.print()
    summary = Table(box=None, show_header=False, pad_edge=False)
    summary.add_column(style="dim")
    summary.add_column()
    summary.add_row("usable", str(len(report.usable)))
    summary.add_row("unique", str(len(report.unique)))
    if report.unusable:
        summary.add_row("unusable", f"[yellow]{len(report.unusable)}[/yellow]")
    if report.skipped:
        summary.add_row("skipped", str(len(report.skipped)))
    if report.heic_decoder:
        summary.add_row("heic decoder", report.heic_decoder)
    gps = sum(1 for r in report.records if r.has_gps)
    if gps:
        summary.add_row("with GPS", f"{gps} (stripped from working copies)")
    normalized = [r for r in report.records if r.normalized_path]
    if normalized:
        summary.add_row("working copies", str(len(normalized)))
    summary.add_row("fingerprint", report.fingerprint[:16])
    summary.add_row("manifest", str(manifest))
    console.print(summary)

    counts = report.counts()
    unresolved = {k: v for k, v in counts.items() if k not in {str(ImageStatus.OK), str(ImageStatus.DUPLICATE)}}
    console.print()
    if unresolved:
        console.print("[yellow]needs attention[/yellow]: " + ", ".join(
            f"{count} {status}" for status, count in sorted(unresolved.items())
        ))
    else:
        console.print("[green]all images usable[/green]")


@app.command()
def group(input_dir: InputArg = None) -> None:
    """Group photos that show the same physical product."""
    _not_built("group", "Phase 3", "visual grouping, duplicate detection, verification")


@app.command()
def analyze(input_dir: InputArg = None) -> None:
    """Build a Product Reference Profile for every detected product."""
    _not_built("analyze", "Phase 4", "Ollama + Qwen3-VL multi-image analysis")


@app.command()
def generate(input_dir: InputArg = None) -> None:
    """Generate the six catalog images through the browser provider."""
    _not_built("generate", "Phase 6-7", "browser controller and the six catalog slots")


@app.command()
def validate(input_dir: InputArg = None) -> None:
    """Run deterministic and product-fidelity QC over existing outputs."""
    _not_built("validate", "Phase 9-10", "deterministic QC then semantic QC")


@app.command()
def run(input_dir: InputArg = None) -> None:
    """Run the whole pipeline for one input folder."""
    _not_built("run", "Phase 11", "end-to-end orchestration")


@app.command()
def batch(input_dir: InputArg = None) -> None:
    """Process every detected product in the input folder."""
    _not_built("batch", "Phase 11", "batch mode, resume and retry")


@app.command()
def retry(
    product_dir: Annotated[Path, typer.Argument(help="e.g. products-output/product-001/")],
    image: Annotated[Optional[str], typer.Option("--image", help="Regenerate just this slot.")] = None,
) -> None:
    """Regenerate a single failed image for one product."""
    _not_built("retry", "Phase 11", "batch mode, resume and retry")


@app.command()
def cleanup(
    product_dir: Annotated[Optional[Path], typer.Argument()] = None,
) -> None:
    """Remove working/ temporary files. Never touches reference photographs."""
    _not_built("cleanup", "Phase 11", "working-directory lifecycle")


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


@app.callback()
def _root(
    ctx: typer.Context,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Echo logs to stderr.")] = False,
) -> None:
    paths = get_paths()
    run_id = new_run_id(ctx.invoked_subcommand or "cli")
    configure_logging(paths.logs, run_id, console=verbose)
    catalog_log().info("command=%s args=%s", ctx.invoked_subcommand, sys.argv[1:])
    ctx.obj = {"run_id": run_id, "paths": paths}


def main() -> None:
    """Console-script entry point with typed error handling."""
    try:
        app()
    except ToycatError as exc:
        err_console.print(f"[red]error[/red] {exc}")
        catalog_log().error("%s: %s", type(exc).__name__, exc)
        raise SystemExit(exc.exit_code) from exc


if __name__ == "__main__":
    main()
