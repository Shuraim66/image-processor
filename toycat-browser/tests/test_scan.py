"""Folder discovery, validation and the scan manifest (spec 6, 9, 43, 49)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from toycat_browser.config import Settings
from toycat_browser.errors import InputError
from toycat_browser.paths import AppPaths
from toycat_browser.scan import (
    MANIFEST_VERSION,
    discover_files,
    inspect_image,
    read_manifest,
    scan_folder,
    write_manifest,
)
from toycat_browser.states import ImageStatus, TimestampSource


def _photo(path: Path, size=(1200, 900), fmt: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size)
    for x in range(0, size[0], 7):
        for y in range(0, size[1], 7):
            image.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
    image.save(path, fmt)
    return path


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    folder = tmp_path / "products-input"
    folder.mkdir()
    return folder


# --- discovery ------------------------------------------------------------


def test_finds_supported_formats(inbox: Path, settings: Settings) -> None:
    for name, fmt in (("a.jpg", "JPEG"), ("b.png", "PNG"), ("c.webp", "WEBP")):
        _photo(inbox / name, fmt=fmt)
    found, _ = discover_files(inbox, settings.catalog.input)
    assert {p.name for p in found} == {"a.jpg", "b.png", "c.webp"}


def test_uppercase_extensions_are_found(inbox: Path, settings: Settings) -> None:
    _photo(inbox / "IMG_1001.JPG", fmt="JPEG")
    found, _ = discover_files(inbox, settings.catalog.input)
    assert len(found) == 1


def test_skips_ds_store_and_hidden_files(inbox: Path, settings: Settings) -> None:
    _photo(inbox / "good.jpg", fmt="JPEG")
    (inbox / ".DS_Store").write_bytes(b"junk")
    _photo(inbox / ".hidden.jpg", fmt="JPEG")

    found, skipped = discover_files(inbox, settings.catalog.input)
    assert [p.name for p in found] == ["good.jpg"]
    reasons = {entry["reason"] for entry in skipped}
    assert "ignored filename" in reasons
    assert "hidden file" in reasons


def test_skips_unsupported_extensions(inbox: Path, settings: Settings) -> None:
    _photo(inbox / "good.jpg", fmt="JPEG")
    (inbox / "notes.txt").write_text("hello")
    (inbox / "clip.mov").write_bytes(b"\x00" * 64)

    found, skipped = discover_files(inbox, settings.catalog.input)
    assert [p.name for p in found] == ["good.jpg"]
    assert len(skipped) == 2


def test_recurses_into_subfolders(inbox: Path, settings: Settings) -> None:
    """The user may drop a folder straight from a phone; it must still work."""
    _photo(inbox / "top.jpg", fmt="JPEG")
    _photo(inbox / "sub" / "nested.jpg", fmt="JPEG")
    found, _ = discover_files(inbox, settings.catalog.input)
    assert len(found) == 2


def test_recursion_can_be_disabled(inbox: Path, settings: Settings) -> None:
    _photo(inbox / "top.jpg", fmt="JPEG")
    _photo(inbox / "sub" / "nested.jpg", fmt="JPEG")
    config = settings.catalog.input.model_copy(update={"recursive": False})
    found, _ = discover_files(inbox, config)
    assert [p.name for p in found] == ["top.jpg"]


def test_missing_input_folder_is_a_clear_error(tmp_path: Path, settings: Settings) -> None:
    with pytest.raises(InputError, match="input folder not found"):
        discover_files(tmp_path / "nope", settings.catalog.input)


# --- validation -----------------------------------------------------------


def test_valid_photo_is_ok(inbox: Path, settings: Settings) -> None:
    path = _photo(inbox / "toy.jpg", fmt="JPEG")
    record = inspect_image(path, inbox, settings.catalog.input)
    assert record.status is ImageStatus.OK
    assert record.usable
    assert (record.width, record.height) == (1200, 900)
    assert record.image_format == "JPEG"
    assert len(record.sha256) == 64


def test_empty_file_is_corrupt(inbox: Path, settings: Settings) -> None:
    path = inbox / "empty.jpg"
    path.write_bytes(b"")
    record = inspect_image(path, inbox, settings.catalog.input)
    assert record.status is ImageStatus.CORRUPT
    assert not record.usable


def test_garbage_with_an_image_extension_is_rejected(inbox: Path, settings: Settings) -> None:
    path = inbox / "fake.png"
    path.write_bytes(b"this is not a png" * 100)
    record = inspect_image(path, inbox, settings.catalog.input)
    assert record.status is ImageStatus.UNSUPPORTED_FORMAT
    assert not record.usable


def test_truncated_photo_is_rejected(inbox: Path, settings: Settings) -> None:
    """A half-transferred AirDrop must never reach an upload (spec 9)."""
    path = _photo(inbox / "cut.jpg", fmt="JPEG")
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])

    record = inspect_image(path, inbox, settings.catalog.input)
    assert record.status is ImageStatus.CORRUPT
    assert not record.usable


def test_tiny_image_is_too_small(inbox: Path, settings: Settings) -> None:
    path = _photo(inbox / "thumb.jpg", size=(200, 150), fmt="JPEG")
    record = inspect_image(path, inbox, settings.catalog.input)
    assert record.status is ImageStatus.TOO_SMALL
    assert "below the 640px minimum edge" in " ".join(record.issues)


def test_oversized_file_is_rejected(inbox: Path, settings: Settings) -> None:
    path = _photo(inbox / "huge.png", fmt="PNG")
    config = settings.catalog.input.model_copy(update={"max_file_size_bytes": 128})
    record = inspect_image(path, inbox, config)
    assert record.status is ImageStatus.TOO_LARGE


def test_dimensions_are_reported_after_orientation(inbox: Path, settings: Settings) -> None:
    """A rotated phone photo must report its displayed size, not its stored size."""
    path = inbox / "rot.jpg"
    image = Image.new("RGB", (1200, 900), "white")
    exif = image.getexif()
    exif[0x0112] = 6
    image.save(path, "JPEG", exif=exif.tobytes())

    record = inspect_image(path, inbox, settings.catalog.input)
    assert (record.raw_width, record.raw_height) == (1200, 900)
    assert (record.width, record.height) == (900, 1200)
    assert record.exif_orientation == 6


def test_missing_capture_time_falls_back_to_mtime(inbox: Path, settings: Settings) -> None:
    path = _photo(inbox / "plain.png", fmt="PNG")
    record = inspect_image(path, inbox, settings.catalog.input)
    assert record.timestamp_source is TimestampSource.FILE_MTIME
    assert record.captured_at is not None
    assert "no EXIF capture time" in " ".join(record.issues)


def test_heic_without_a_decoder_says_how_to_fix_it(inbox: Path, settings: Settings, monkeypatch) -> None:
    from toycat_browser import images, scan
    from toycat_browser.images import HeicSupport

    missing = HeicSupport(False, None, "no decoder", "run: pip install 'toycat-browser[heic]'")
    monkeypatch.setattr(scan, "heic_support", lambda: missing)
    monkeypatch.setattr(images, "heic_support", lambda: missing)

    path = inbox / "IMG_1001.heic"
    path.write_bytes(b"\x00" * 4096)
    record = inspect_image(path, inbox, settings.catalog.input)

    assert record.status is ImageStatus.DECODER_MISSING
    assert "pip install" in " ".join(record.issues)
    assert not record.usable


def test_filename_hint_ignores_numbering(inbox: Path, settings: Settings) -> None:
    path = _photo(inbox / "blue-dumpling-02.jpg", fmt="JPEG")
    record = inspect_image(path, inbox, settings.catalog.input)
    assert record.filename_hint == "blue-dumpling"


# --- whole-folder scan ----------------------------------------------------


def test_scan_separates_usable_from_broken(inbox: Path, settings: Settings) -> None:
    _photo(inbox / "a.jpg", fmt="JPEG")
    _photo(inbox / "b.jpg", fmt="JPEG")
    (inbox / "broken.jpg").write_bytes(b"nope")

    report = scan_folder(inbox, settings)
    assert len(report.records) == 3
    assert len(report.usable) == 2
    assert len(report.unusable) == 1


def test_one_broken_file_does_not_stop_the_scan(inbox: Path, settings: Settings) -> None:
    """Spec 43: continue processing when one item fails."""
    (inbox / "broken.jpg").write_bytes(b"nope")
    for index in range(3):
        _photo(inbox / f"good{index}.jpg", fmt="JPEG")

    report = scan_folder(inbox, settings)
    assert len(report.usable) == 3


def test_byte_identical_copies_are_marked_duplicate(inbox: Path, settings: Settings) -> None:
    original = _photo(inbox / "front.jpg", fmt="JPEG")
    shutil.copy(original, inbox / "front copy.jpg")

    report = scan_folder(inbox, settings)
    duplicates = [r for r in report.records if r.status is ImageStatus.DUPLICATE]
    assert len(duplicates) == 1
    assert len(report.unique) == 1
    # The duplicate points at the one copy that was kept, whichever sorted first.
    assert duplicates[0].duplicate_of == report.unique[0].relative_path
    assert duplicates[0].duplicate_of != duplicates[0].relative_path
    # A duplicate is still a real photograph, so it stays usable.
    assert duplicates[0].usable
    # And the choice must be stable, or idempotency breaks.
    assert scan_folder(inbox, settings).unique[0].relative_path == report.unique[0].relative_path


def test_scan_never_writes_into_the_input_folder(inbox: Path, settings: Settings, paths: AppPaths) -> None:
    """Spec 9: originals are untouched and no new files appear beside them."""
    _photo(inbox / "a.jpg", fmt="JPEG")
    before = {p.name: p.read_bytes() for p in inbox.iterdir()}

    scan_folder(inbox, settings, paths=paths)
    after = {p.name: p.read_bytes() for p in inbox.iterdir()}
    assert before == after


def test_normalized_copies_land_outside_the_input(tmp_path: Path, inbox: Path, settings: Settings) -> None:
    _photo(inbox / "a.jpg", fmt="JPEG")
    app_paths = AppPaths(root=tmp_path / "app")

    report = scan_folder(inbox, settings, paths=app_paths, normalize_copies=True)
    record = report.unique[0]
    assert record.normalized_path is not None
    assert record.normalized_path.is_file()
    assert app_paths.working in record.normalized_path.parents
    assert inbox not in record.normalized_path.parents


def test_duplicates_do_not_get_their_own_working_copy(tmp_path: Path, inbox: Path, settings: Settings) -> None:
    original = _photo(inbox / "front.jpg", fmt="JPEG")
    shutil.copy(original, inbox / "again.jpg")
    app_paths = AppPaths(root=tmp_path / "app")

    scan_folder(inbox, settings, paths=app_paths, normalize_copies=True)
    assert len(list(app_paths.normalized_dir.iterdir())) == 1


# --- idempotency ----------------------------------------------------------


def test_fingerprint_is_stable_across_runs(inbox: Path, settings: Settings) -> None:
    """Spec 49: unchanged inputs must produce an unchanged fingerprint."""
    _photo(inbox / "a.jpg", fmt="JPEG")
    _photo(inbox / "b.jpg", fmt="JPEG")

    first = scan_folder(inbox, settings).fingerprint
    second = scan_folder(inbox, settings).fingerprint
    assert first == second and len(first) == 64


def test_fingerprint_ignores_discovery_order(inbox: Path, settings: Settings, monkeypatch) -> None:
    _photo(inbox / "a.jpg", fmt="JPEG")
    _photo(inbox / "b.jpg", fmt="JPEG")
    baseline = scan_folder(inbox, settings).fingerprint

    from toycat_browser import scan as scan_module

    original = scan_module.discover_files
    monkeypatch.setattr(
        scan_module, "discover_files",
        lambda d, c: (list(reversed(original(d, c)[0])), original(d, c)[1]),
    )
    assert scan_folder(inbox, settings).fingerprint == baseline


def test_fingerprint_changes_when_a_photo_is_added(inbox: Path, settings: Settings) -> None:
    _photo(inbox / "a.jpg", fmt="JPEG")
    before = scan_folder(inbox, settings).fingerprint

    _photo(inbox / "b.jpg", fmt="JPEG")
    assert scan_folder(inbox, settings).fingerprint != before


def test_broken_files_do_not_affect_the_fingerprint(inbox: Path, settings: Settings) -> None:
    _photo(inbox / "a.jpg", fmt="JPEG")
    before = scan_folder(inbox, settings).fingerprint

    (inbox / "broken.jpg").write_bytes(b"nope")
    assert scan_folder(inbox, settings).fingerprint == before


# --- manifest -------------------------------------------------------------


def test_manifest_round_trip(tmp_path: Path, inbox: Path, settings: Settings) -> None:
    _photo(inbox / "a.jpg", fmt="JPEG")
    report = scan_folder(inbox, settings)

    destination = write_manifest(report, tmp_path / "scan.json")
    data = read_manifest(destination)

    assert data["manifest_version"] == MANIFEST_VERSION
    assert data["totals"]["usable"] == 1
    assert data["fingerprint"] == report.fingerprint
    assert data["images"][0]["filename"] == "a.jpg"


def test_manifest_is_json_serialisable(tmp_path: Path, inbox: Path, settings: Settings) -> None:
    _photo(inbox / "a.jpg", fmt="JPEG")
    report = scan_folder(inbox, settings)
    json.dumps(report.to_dict())


def test_manifest_records_every_grouping_signal(tmp_path: Path, dumpling_fixture: Path, settings: Settings) -> None:
    """Phase 3 needs hashes, capture times and hints to exist in the manifest."""
    report = scan_folder(dumpling_fixture, settings)
    entry = report.to_dict()["images"][0]
    for key in ("sha256", "captured_at", "timestamp_source", "filename_hint",
                "width", "height", "camera_model"):
        assert entry[key] is not None, f"missing grouping signal: {key}"


def test_stale_manifest_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "scan.json"
    path.write_text(json.dumps({"manifest_version": 0}), encoding="utf-8")
    with pytest.raises(InputError, match="re-run `toycat scan`"):
        read_manifest(path)


def test_missing_manifest_says_what_to_run(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="run `toycat scan` first"):
        read_manifest(tmp_path / "absent.json")


# --- the real fixture -----------------------------------------------------


def test_dumpling_fixture_scans_clean(dumpling_fixture: Path, settings: Settings) -> None:
    report = scan_folder(dumpling_fixture, settings)
    assert len(report.usable) == 6
    assert len(report.unique) == 6
    assert not report.unusable
    assert all(r.timestamp_source is TimestampSource.EXIF_ORIGINAL for r in report.usable)
    assert all(r.has_gps for r in report.usable)


def test_dumpling_manifest_json_is_ignored_by_the_scanner(dumpling_fixture: Path, settings: Settings) -> None:
    """manifest.json sits next to the photos and must not be treated as one."""
    report = scan_folder(dumpling_fixture, settings)
    assert "manifest.json" not in {r.filename for r in report.records}
    assert any(e["path"].endswith("manifest.json") for e in report.skipped)
