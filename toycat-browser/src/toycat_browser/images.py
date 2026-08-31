"""Decoding, EXIF handling and working-copy normalization (spec 9, 32).

Two rules govern this module:

* Original photographs are never written to. Every transformation produces a
  new file somewhere under ``working/``.
* A file that cannot be decoded cleanly is never passed downstream. A corrupt
  image must not reach an upload.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError
from PIL.ExifTags import Base as ExifTag

from .config import WorkingCopyConfig
from .errors import InputError
from .states import TimestampSource

#: Extension -> the PIL format name we expect to see.
FORMAT_BY_EXTENSION: dict[str, str] = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".heic": "HEIF",
    ".heif": "HEIF",
}

HEIF_EXTENSIONS = frozenset({".heic", ".heif"})

_EXIF_DATETIME_FORMATS = ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------
# HEIC / HEIF support
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HeicSupport:
    """How (or whether) this machine can decode HEIC (spec 9)."""

    available: bool
    decoder: str | None
    detail: str
    remediation: str = ""


@lru_cache(maxsize=1)
def heic_support() -> HeicSupport:
    """Detect a HEIC decoder once, preferring in-process decoding."""
    try:
        import pillow_heif  # type: ignore

        pillow_heif.register_heif_opener()
        return HeicSupport(
            available=True,
            decoder="pillow-heif",
            detail=f"pillow-heif {getattr(pillow_heif, '__version__', 'unknown')}",
        )
    except ImportError:
        pass

    sips = shutil.which("sips")
    if sips:
        return HeicSupport(
            available=True,
            decoder="sips",
            detail="macOS sips (out-of-process conversion to PNG)",
            remediation="for faster decoding: pip install 'toycat-browser[heic]'",
        )

    return HeicSupport(
        available=False,
        decoder=None,
        detail="no HEIC/HEIF decoder found",
        remediation=(
            "run: pip install 'toycat-browser[heic]'\n"
            "or convert the photos to JPEG before dropping them into products-input/"
        ),
    )


def _decode_heic_via_sips(path: Path) -> Image.Image:
    """Convert HEIC to PNG with macOS `sips`, then load the PNG into memory."""
    with tempfile.TemporaryDirectory(prefix="toycat-heic-") as tmp:
        target = Path(tmp) / f"{path.stem}.png"
        result = subprocess.run(
            ["sips", "-s", "format", "png", str(path), "--out", str(target)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0 or not target.is_file():
            raise InputError(
                f"sips could not decode {path.name}: "
                f"{result.stderr.strip() or 'unknown error'}"
            )
        with Image.open(target) as converted:
            return converted.copy()


def open_image(path: Path) -> Image.Image:
    """Open any supported image, routing HEIC through whichever decoder exists.

    The returned image is fully loaded, so the file handle is already closed.
    """
    suffix = path.suffix.lower()
    if suffix in HEIF_EXTENSIONS:
        support = heic_support()
        if not support.available:
            raise InputError(f"{path.name}: {support.detail}. {support.remediation}")
        if support.decoder == "sips":
            return _decode_heic_via_sips(path)

    with Image.open(path) as image:
        image.load()
        return image.copy()


# --------------------------------------------------------------------------
# EXIF
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExifFacts:
    """The handful of EXIF values the pipeline actually uses.

    GPS is deliberately absent: it is never read, never logged and never
    carried into a working copy that gets uploaded.
    """

    orientation: int
    captured_at: datetime | None
    timestamp_source: TimestampSource
    camera_make: str | None
    camera_model: str | None
    has_gps: bool


def _parse_exif_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip().rstrip("\x00")
    for fmt in _EXIF_DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def read_exif(image: Image.Image) -> ExifFacts:
    """Extract orientation, capture time and camera. Never raises."""
    try:
        exif = image.getexif()
    except Exception:  # noqa: BLE001 - a malformed EXIF block must not stop a scan
        exif = None

    if not exif:
        return ExifFacts(1, None, TimestampSource.NONE, None, None, False)

    orientation = exif.get(ExifTag.Orientation.value, 1)
    if not isinstance(orientation, int) or not 1 <= orientation <= 8:
        orientation = 1

    def _clean(tag: int) -> str | None:
        value = exif.get(tag)
        if isinstance(value, bytes):
            value = value.decode("utf-8", "replace")
        if isinstance(value, str):
            value = value.strip().rstrip("\x00")
            return value or None
        return None

    try:
        sub_ifd = exif.get_ifd(ExifTag.ExifOffset.value)
    except Exception:  # noqa: BLE001
        sub_ifd = {}

    captured_at: datetime | None = None
    source = TimestampSource.NONE
    for tag, tag_source, table in (
        (ExifTag.DateTimeOriginal.value, TimestampSource.EXIF_ORIGINAL, sub_ifd),
        (ExifTag.DateTimeDigitized.value, TimestampSource.EXIF_DIGITIZED, sub_ifd),
        (ExifTag.DateTime.value, TimestampSource.EXIF_MODIFIED, exif),
    ):
        captured_at = _parse_exif_datetime(table.get(tag))
        if captured_at is not None:
            source = tag_source
            break

    has_gps = bool(exif.get(ExifTag.GPSInfo.value))

    return ExifFacts(
        orientation=orientation,
        captured_at=captured_at,
        timestamp_source=source,
        camera_make=_clean(ExifTag.Make.value),
        camera_model=_clean(ExifTag.Model.value),
        has_gps=has_gps,
    )


# --------------------------------------------------------------------------
# normalization
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _srgb_profile() -> Any:
    return ImageCms.createProfile("sRGB")


def to_srgb(image: Image.Image) -> Image.Image:
    """Convert to sRGB, honouring an embedded ICC profile when there is one."""
    profile = image.info.get("icc_profile")
    if profile:
        try:
            source = ImageCms.getOpenProfile(io.BytesIO(profile))
            converted = ImageCms.profileToProfile(
                image, source, _srgb_profile(), outputMode="RGB"
            )
            if converted is not None:
                return converted
        except Exception:  # noqa: BLE001 - a broken profile falls back to a plain convert
            pass
    return image.convert("RGB") if image.mode != "RGB" else image


def normalize(image: Image.Image) -> Image.Image:
    """Apply EXIF orientation and land in sRGB RGB (spec 9, 32).

    Orientation is baked into the pixels, so every downstream stage can treat
    width/height literally.
    """
    return to_srgb(ImageOps.exif_transpose(image) or image)


def fit_within(image: Image.Image, max_edge: int) -> Image.Image:
    """Downscale uniformly to fit a box. Never upscales, never distorts (spec 27)."""
    if max_edge <= 0 or max(image.size) <= max_edge:
        return image
    scale = max_edge / max(image.size)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def write_working_copy(
    source: Path, destination: Path, config: WorkingCopyConfig
) -> Path:
    """Write a normalized, metadata-free copy of a source photograph.

    The source is only ever read. All EXIF — including GPS — is dropped, because
    working copies are uploaded to an external service.
    """
    if destination.resolve() == source.resolve():
        raise InputError(
            f"refusing to overwrite the original photograph at {source} (spec 9)"
        )

    image = normalize(open_image(source))
    image = fit_within(image, config.max_edge_pixels)

    if config.strip_metadata:
        # A fresh canvas carries no `info` dict, so EXIF and ICC are gone.
        clean = Image.new(image.mode, image.size)
        clean.paste(image)
        image = clean

    destination.parent.mkdir(parents=True, exist_ok=True)
    fmt = config.format.upper()
    if fmt == "JPEG":
        image.save(destination, "JPEG", quality=config.jpeg_quality, subsampling=0,
                   optimize=True)
    elif fmt == "PNG":
        image.save(destination, "PNG", optimize=True)
    elif fmt == "WEBP":
        image.save(destination, "WEBP", quality=config.jpeg_quality, method=6)
    else:
        raise InputError(f"unsupported working-copy format: {config.format}")
    return destination


__all__ = [
    "ExifFacts",
    "FORMAT_BY_EXTENSION",
    "HEIF_EXTENSIONS",
    "HeicSupport",
    "UnidentifiedImageError",
    "fit_within",
    "heic_support",
    "normalize",
    "open_image",
    "read_exif",
    "to_srgb",
    "write_working_copy",
]
