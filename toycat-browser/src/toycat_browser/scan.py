"""Input folder discovery and validation (spec 6, 9, 49).

The user drops photos straight from a phone into ``products-input/``. No
renaming, no folders, no SKUs. This module turns that pile into a validated,
hashed, metadata-rich manifest that the grouping engine can reason about.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .config import InputConfig, Settings
from .errors import InputError
from .hashing import sha256_file, sha256_of
from .images import (
    FORMAT_BY_EXTENSION,
    HEIF_EXTENSIONS,
    heic_support,
    normalize,
    open_image,
    read_exif,
    write_working_copy,
)
from .logging_setup import catalog_log
from .paths import AppPaths
from .states import USABLE_IMAGE_STATUSES, ImageStatus, TimestampSource

MANIFEST_VERSION = 1


@dataclass
class ImageRecord:
    """One discovered photograph and everything known about it."""

    path: Path
    filename: str
    relative_path: str
    status: ImageStatus
    size_bytes: int
    sha256: str | None = None
    image_format: str | None = None
    width: int | None = None
    height: int | None = None
    raw_width: int | None = None
    raw_height: int | None = None
    exif_orientation: int = 1
    captured_at: datetime | None = None
    timestamp_source: TimestampSource = TimestampSource.NONE
    camera_make: str | None = None
    camera_model: str | None = None
    has_gps: bool = False
    filename_hint: str = ""
    duplicate_of: str | None = None
    normalized_path: Path | None = None
    issues: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """True when this image may be used as a product reference (spec 9)."""
        return self.status in USABLE_IMAGE_STATUSES

    @property
    def megapixels(self) -> float:
        if not self.width or not self.height:
            return 0.0
        return (self.width * self.height) / 1_000_000

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "filename": self.filename,
            "relative_path": self.relative_path,
            "status": str(self.status),
            "usable": self.usable,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "format": self.image_format,
            "width": self.width,
            "height": self.height,
            "raw_width": self.raw_width,
            "raw_height": self.raw_height,
            "megapixels": round(self.megapixels, 2),
            "exif_orientation": self.exif_orientation,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "timestamp_source": str(self.timestamp_source),
            "camera_make": self.camera_make,
            "camera_model": self.camera_model,
            "has_gps": self.has_gps,
            "filename_hint": self.filename_hint,
            "duplicate_of": self.duplicate_of,
            "normalized_path": str(self.normalized_path) if self.normalized_path else None,
            "issues": list(self.issues),
        }


@dataclass
class ScanReport:
    """The result of scanning one input folder."""

    input_dir: Path
    scanned_at: datetime
    records: list[ImageRecord] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    heic_decoder: str | None = None

    @property
    def usable(self) -> list[ImageRecord]:
        return [record for record in self.records if record.usable]

    @property
    def unusable(self) -> list[ImageRecord]:
        return [record for record in self.records if not record.usable]

    @property
    def unique(self) -> list[ImageRecord]:
        """Usable records with byte-identical copies collapsed to the first seen."""
        return [record for record in self.usable if record.duplicate_of is None]

    @property
    def fingerprint(self) -> str:
        """Stable digest of the usable input set, for idempotency (spec 49)."""
        return sha256_of(sorted(r.sha256 for r in self.usable if r.sha256))

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self.records:
            key = str(record.status)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest_version": MANIFEST_VERSION,
            "input_dir": str(self.input_dir),
            "scanned_at": self.scanned_at.isoformat(),
            "heic_decoder": self.heic_decoder,
            "fingerprint": self.fingerprint,
            "totals": {
                "discovered": len(self.records),
                "usable": len(self.usable),
                "unique": len(self.unique),
                "unusable": len(self.unusable),
                "skipped": len(self.skipped),
            },
            "status_counts": self.counts(),
            "images": [record.to_dict() for record in self.records],
            "skipped": list(self.skipped),
        }


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------


def _is_hidden(path: Path, root: Path) -> bool:
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def discover_files(input_dir: Path, config: InputConfig) -> tuple[list[Path], list[dict[str, str]]]:
    """List candidate image files, and record what was skipped and why."""
    if not input_dir.is_dir():
        raise InputError(f"input folder not found: {input_dir}")

    found: list[Path] = []
    skipped: list[dict[str, str]] = []
    ignore = {name.lower() for name in config.ignore_filenames}
    pattern = "**/*" if config.recursive else "*"

    for path in sorted(input_dir.glob(pattern)):
        if path.is_dir():
            continue
        if path.is_symlink() and not config.follow_symlinks:
            skipped.append({"path": str(path), "reason": "symlink"})
            continue
        if not path.is_file():
            continue
        if path.name.lower() in ignore:
            skipped.append({"path": str(path), "reason": "ignored filename"})
            continue
        if config.ignore_hidden and _is_hidden(path, input_dir):
            skipped.append({"path": str(path), "reason": "hidden file"})
            continue
        if path.suffix.lower() not in config.extensions:
            skipped.append({"path": str(path), "reason": f"unsupported extension {path.suffix or '(none)'}"})
            continue
        found.append(path)

    return found, skipped


def _filename_hint(path: Path) -> str:
    """A loose grouping hint from the filename (spec 7). Never authoritative."""
    stem = path.stem.lower()
    cleaned = "".join(char if char.isalnum() else "-" for char in stem)
    parts = [part for part in cleaned.split("-") if part and not part.isdigit()]
    return "-".join(parts)


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def inspect_image(path: Path, input_dir: Path, config: InputConfig) -> ImageRecord:
    """Validate one file and collect its metadata. Never raises (spec 43)."""
    try:
        size_bytes = path.stat().st_size
    except OSError as exc:
        return ImageRecord(
            path=path, filename=path.name, relative_path=path.name,
            status=ImageStatus.UNREADABLE, size_bytes=0,
            issues=[f"cannot stat file: {exc}"],
        )

    record = ImageRecord(
        path=path,
        filename=path.name,
        relative_path=str(path.relative_to(input_dir)),
        status=ImageStatus.OK,
        size_bytes=size_bytes,
        filename_hint=_filename_hint(path),
    )

    if size_bytes == 0:
        record.status = ImageStatus.CORRUPT
        record.issues.append("file is empty")
        return record

    if size_bytes > config.max_file_size_bytes:
        record.status = ImageStatus.TOO_LARGE
        record.issues.append(
            f"{size_bytes / 1_048_576:.0f} MB exceeds the "
            f"{config.max_file_size_bytes / 1_048_576:.0f} MB limit"
        )
        return record

    suffix = path.suffix.lower()
    if suffix in HEIF_EXTENSIONS and not heic_support().available:
        record.status = ImageStatus.DECODER_MISSING
        record.issues.append(heic_support().remediation.replace("\n", " "))
        return record

    try:
        record.sha256 = sha256_file(path)
    except OSError as exc:
        record.status = ImageStatus.UNREADABLE
        record.issues.append(f"cannot read file: {exc}")
        return record

    # Structural check first. verify() consumes the file object, so the real
    # decode below reopens it.
    if suffix not in HEIF_EXTENSIONS:
        try:
            with Image.open(path) as probe:
                probe.verify()
        except UnidentifiedImageError:
            record.status = ImageStatus.UNSUPPORTED_FORMAT
            record.issues.append("not a recognised image format")
            return record
        except Exception as exc:  # noqa: BLE001 - any verify failure means unusable
            record.status = ImageStatus.CORRUPT
            record.issues.append(f"failed structural check: {exc}")
            return record

    # Full decode. This is what catches truncation that verify() lets through.
    try:
        image = open_image(path)
    except UnidentifiedImageError:
        record.status = ImageStatus.UNSUPPORTED_FORMAT
        record.issues.append("not a recognised image format")
        return record
    except Exception as exc:  # noqa: BLE001
        record.status = ImageStatus.CORRUPT
        record.issues.append(f"failed to decode: {exc}")
        return record

    try:
        record.image_format = image.format or FORMAT_BY_EXTENSION.get(suffix)
        record.raw_width, record.raw_height = image.size

        exif = read_exif(image)
        record.exif_orientation = exif.orientation
        record.captured_at = exif.captured_at
        record.timestamp_source = exif.timestamp_source
        record.camera_make = exif.camera_make
        record.camera_model = exif.camera_model
        record.has_gps = exif.has_gps

        # Dimensions are reported after orientation, so every later stage can
        # treat width and height literally (spec 9).
        oriented = normalize(image)
        record.width, record.height = oriented.size
    finally:
        image.close()

    if record.captured_at is None:
        try:
            record.captured_at = datetime.fromtimestamp(path.stat().st_mtime)
            record.timestamp_source = TimestampSource.FILE_MTIME
            record.issues.append("no EXIF capture time; using file modification time")
        except OSError:
            pass

    min_edge = config.min_edge_pixels
    if min(record.width, record.height) < min_edge:
        record.status = ImageStatus.TOO_SMALL
        record.issues.append(
            f"{record.width}x{record.height} is below the {min_edge}px minimum edge"
        )
        return record

    if record.megapixels < config.min_megapixels:
        record.status = ImageStatus.TOO_SMALL
        record.issues.append(
            f"{record.megapixels:.2f} MP is below the {config.min_megapixels} MP minimum"
        )
        return record

    return record


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------


def scan_folder(
    input_dir: Path,
    settings: Settings,
    *,
    paths: AppPaths | None = None,
    normalize_copies: bool = False,
) -> ScanReport:
    """Discover, validate and describe every image in ``input_dir``."""
    config = settings.catalog.input
    input_dir = input_dir.expanduser().resolve()
    log = catalog_log()

    files, skipped = discover_files(input_dir, config)
    support = heic_support()
    report = ScanReport(
        input_dir=input_dir,
        scanned_at=datetime.now(UTC),
        skipped=skipped,
        heic_decoder=support.decoder,
    )

    seen: dict[str, str] = {}
    for path in files:
        record = inspect_image(path, input_dir, config)

        if record.sha256 and record.usable:
            first = seen.get(record.sha256)
            if first is not None:
                record.duplicate_of = first
                record.status = ImageStatus.DUPLICATE
                record.issues.append(f"byte-identical to {first}")
            else:
                seen[record.sha256] = record.relative_path

        report.records.append(record)
        log.info(
            "scan %s status=%s %sx%s format=%s",
            record.relative_path, record.status, record.width, record.height,
            record.image_format,
        )

    if normalize_copies and paths is not None:
        _write_working_copies(report, settings, paths)

    log.info(
        "scan complete dir=%s discovered=%d usable=%d unique=%d unusable=%d",
        input_dir, len(report.records), len(report.usable),
        len(report.unique), len(report.unusable),
    )
    return report


def _write_working_copies(report: ScanReport, settings: Settings, paths: AppPaths) -> None:
    """Materialise normalized copies. Originals are never modified (spec 9)."""
    config = settings.catalog.input.working_copy
    target_dir = paths.normalized_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[config.format.upper()]

    for record in report.unique:
        assert record.sha256 is not None
        destination = target_dir / f"{record.sha256[:12]}-{record.path.stem}{extension}"
        try:
            record.normalized_path = write_working_copy(record.path, destination, config)
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the scan
            record.issues.append(f"could not write working copy: {exc}")
            catalog_log().warning("working copy failed for %s: %s", record.filename, exc)


def write_manifest(report: ScanReport, destination: Path) -> Path:
    """Persist the scan manifest for the grouping stage to consume."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination


def read_manifest(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise InputError(f"no scan manifest at {path}; run `toycat scan` first")
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("manifest_version")
    if version != MANIFEST_VERSION:
        raise InputError(
            f"scan manifest at {path} is version {version}, expected {MANIFEST_VERSION}; "
            "re-run `toycat scan`"
        )
    return data


__all__ = [
    "ImageRecord",
    "MANIFEST_VERSION",
    "ScanReport",
    "discover_files",
    "inspect_image",
    "read_manifest",
    "scan_folder",
    "write_manifest",
]
