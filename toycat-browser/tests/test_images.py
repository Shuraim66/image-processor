"""Decoding, EXIF handling and working-copy normalization (spec 9, 32)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from toycat_browser.config import WorkingCopyConfig
from toycat_browser.errors import InputError
from toycat_browser.images import (
    fit_within,
    heic_support,
    normalize,
    open_image,
    read_exif,
    write_working_copy,
)
from toycat_browser.states import TimestampSource

WORKING_COPY = WorkingCopyConfig(
    max_edge_pixels=2048, format="JPEG", jpeg_quality=95, strip_metadata=True
)


def _gradient(width: int, height: int) -> Image.Image:
    """A non-uniform image, so that a wrong rotation is actually detectable."""
    image = Image.new("RGB", (width, height), "white")
    for x in range(width):
        for y in range(height):
            image.putpixel((x, y), (x * 255 // max(1, width - 1), y * 255 // max(1, height - 1), 40))
    return image


def _jpeg_with_orientation(path: Path, orientation: int, size=(120, 60)) -> Path:
    image = _gradient(*size)
    exif = image.getexif()
    exif[0x0112] = orientation  # Orientation
    image.save(path, "JPEG", exif=exif.tobytes(), quality=95)
    return path


# --- decoding -------------------------------------------------------------


@pytest.mark.parametrize("fmt,suffix", [("JPEG", ".jpg"), ("PNG", ".png"), ("WEBP", ".webp")])
def test_opens_every_required_format(tmp_path: Path, fmt: str, suffix: str) -> None:
    path = tmp_path / f"toy{suffix}"
    _gradient(64, 48).save(path, fmt)
    image = open_image(path)
    assert image.size == (64, 48)


def test_open_image_closes_the_source_file(tmp_path: Path) -> None:
    """The returned image must survive the file handle being gone."""
    path = tmp_path / "toy.png"
    _gradient(32, 32).save(path)
    image = open_image(path)
    path.unlink()
    assert image.getpixel((0, 0)) is not None


# --- EXIF orientation -----------------------------------------------------


def test_orientation_tag_is_read(tmp_path: Path) -> None:
    path = _jpeg_with_orientation(tmp_path / "rot.jpg", 6)
    facts = read_exif(open_image(path))
    assert facts.orientation == 6


@pytest.mark.parametrize("orientation", [5, 6, 7, 8])
def test_normalize_swaps_axes_for_rotated_originals(tmp_path: Path, orientation: int) -> None:
    """Orientations 5-8 are 90-degree turns, so a landscape file becomes portrait."""
    path = _jpeg_with_orientation(tmp_path / f"rot{orientation}.jpg", orientation, (120, 60))
    normalized = normalize(open_image(path))
    assert normalized.size == (60, 120)


@pytest.mark.parametrize("orientation", [1, 2, 3, 4])
def test_normalize_keeps_axes_for_upright_originals(tmp_path: Path, orientation: int) -> None:
    path = _jpeg_with_orientation(tmp_path / f"rot{orientation}.jpg", orientation, (120, 60))
    assert normalize(open_image(path)).size == (120, 60)


def test_normalize_drops_the_orientation_tag(tmp_path: Path) -> None:
    """Orientation is baked into pixels, so it must not be applied twice."""
    path = _jpeg_with_orientation(tmp_path / "rot.jpg", 6)
    normalized = normalize(open_image(path))
    assert normalized.getexif().get(0x0112, 1) == 1


def test_missing_exif_is_not_an_error(tmp_path: Path) -> None:
    path = tmp_path / "plain.png"
    _gradient(32, 32).save(path)
    facts = read_exif(open_image(path))
    assert facts.orientation == 1
    assert facts.captured_at is None
    assert facts.timestamp_source is TimestampSource.NONE


# --- real fixture EXIF ----------------------------------------------------


def test_real_photo_exif(dumpling_fixture: Path) -> None:
    facts = read_exif(open_image(dumpling_fixture / "angle2.jpg"))
    assert facts.timestamp_source is TimestampSource.EXIF_ORIGINAL
    assert facts.captured_at is not None
    assert facts.camera_make == "vivo"
    assert facts.camera_model == "vivo Y100"


def test_real_photos_are_seconds_apart(dumpling_fixture: Path) -> None:
    """Capture-time proximity is a grouping signal, so it must survive parsing."""
    times = [
        read_exif(open_image(dumpling_fixture / name)).captured_at
        for name in ("angle2.jpg", "angle3.jpg")
    ]
    assert all(t is not None for t in times)
    assert abs((times[1] - times[0]).total_seconds()) < 60


def test_real_photos_carry_gps(dumpling_fixture: Path) -> None:
    """These photos have GPS, which is exactly why working copies are stripped."""
    assert read_exif(open_image(dumpling_fixture / "angle2.jpg")).has_gps is True


# --- scaling --------------------------------------------------------------


def test_fit_within_preserves_aspect_ratio() -> None:
    resized = fit_within(_gradient(4000, 2000), 2048)
    assert resized.size == (2048, 1024)


def test_fit_within_never_upscales() -> None:
    small = _gradient(100, 80)
    assert fit_within(small, 2048).size == (100, 80)


def test_fit_within_is_uniform_on_portrait() -> None:
    resized = fit_within(_gradient(2296, 4080), 2048)
    assert resized.size == (1153, 2048)
    assert abs(resized.width / resized.height - 2296 / 4080) < 0.001


# --- working copies -------------------------------------------------------


def test_working_copy_never_touches_the_original(tmp_path: Path) -> None:
    source = tmp_path / "original.jpg"
    _jpeg_with_orientation(source, 6)
    before = source.read_bytes()

    write_working_copy(source, tmp_path / "copy.jpg", WORKING_COPY)
    assert source.read_bytes() == before


def test_working_copy_refuses_to_overwrite_the_source(tmp_path: Path) -> None:
    source = tmp_path / "original.jpg"
    _gradient(64, 64).save(source, "JPEG")
    with pytest.raises(InputError, match="refusing to overwrite"):
        write_working_copy(source, source, WORKING_COPY)


def test_working_copy_bakes_in_orientation(tmp_path: Path) -> None:
    source = _jpeg_with_orientation(tmp_path / "rot.jpg", 6, (120, 60))
    copy = write_working_copy(source, tmp_path / "copy.jpg", WORKING_COPY)
    with Image.open(copy) as image:
        assert image.size == (60, 120)
        assert image.getexif().get(0x0112, 1) == 1


def test_working_copy_strips_gps(tmp_path: Path, dumpling_fixture: Path) -> None:
    """Working copies are uploaded to an external service (spec 61)."""
    copy = write_working_copy(
        dumpling_fixture / "angle2.jpg", tmp_path / "copy.jpg", WORKING_COPY
    )
    with Image.open(copy) as image:
        assert not image.getexif()
        assert "icc_profile" not in image.info


def test_working_copy_is_bounded(tmp_path: Path, dumpling_fixture: Path) -> None:
    copy = write_working_copy(
        dumpling_fixture / "front.jpg", tmp_path / "copy.jpg", WORKING_COPY
    )
    with Image.open(copy) as image:
        assert max(image.size) == 2048
        assert abs(image.width / image.height - 2296 / 4080) < 0.01


def test_working_copy_is_srgb_rgb(tmp_path: Path) -> None:
    source = tmp_path / "cmyk.jpg"
    Image.new("CMYK", (64, 64), (0, 0, 0, 0)).save(source, "JPEG")
    copy = write_working_copy(source, tmp_path / "copy.jpg", WORKING_COPY)
    with Image.open(copy) as image:
        assert image.mode == "RGB"


def test_working_copy_rejects_unknown_format(tmp_path: Path) -> None:
    source = tmp_path / "toy.png"
    _gradient(32, 32).save(source)
    config = WORKING_COPY.model_copy(update={"format": "TIFF"})
    with pytest.raises(InputError, match="unsupported working-copy format"):
        write_working_copy(source, tmp_path / "copy.tiff", config)


def test_strip_metadata_cannot_be_disabled() -> None:
    """Config validation, not politeness, is what protects the GPS data."""
    with pytest.raises(Exception, match="strip_metadata"):
        WorkingCopyConfig(max_edge_pixels=2048, format="JPEG", jpeg_quality=95,
                          strip_metadata=False)


# --- HEIC -----------------------------------------------------------------


def test_heic_support_is_reported_honestly() -> None:
    support = heic_support()
    assert support.available is (support.decoder is not None)
    if not support.available:
        assert "pip install" in support.remediation


@pytest.mark.skipif(heic_support().decoder != "pillow-heif", reason="pillow-heif not installed")
def test_heic_round_trip(tmp_path: Path) -> None:
    import pillow_heif  # type: ignore

    path = tmp_path / "toy.heic"
    pillow_heif.from_pillow(_gradient(200, 120)).save(str(path), quality=90)

    image = open_image(path)
    assert image.size == (200, 120)
    assert normalize(image).size == (200, 120)


@pytest.mark.skipif(heic_support().decoder != "pillow-heif", reason="pillow-heif not installed")
def test_heic_becomes_a_jpeg_working_copy(tmp_path: Path) -> None:
    import pillow_heif  # type: ignore

    source = tmp_path / "toy.heic"
    pillow_heif.from_pillow(_gradient(300, 200)).save(str(source), quality=90)

    copy = write_working_copy(source, tmp_path / "copy.jpg", WORKING_COPY)
    with Image.open(copy) as image:
        assert image.format == "JPEG"
        assert image.size == (300, 200)
    assert source.suffix == ".heic"
