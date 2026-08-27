"""Grouping an unsorted shoot into per-product folders."""

import datetime
import os

import pytest
from PIL import Image

import intake


def _shots(*offsets):
    """Fake shot list at the given second offsets from a fixed start."""
    t0 = datetime.datetime(2026, 8, 25, 22, 0, 0)
    return [(t0 + datetime.timedelta(seconds=s), f"p{i}.jpg") for i, s in enumerate(offsets)]


def test_cluster_splits_on_a_long_pause():
    groups = intake.cluster(_shots(0, 5, 10, 200, 205), gap=60)
    assert [len(g) for g in groups] == [3, 2]


def test_cluster_keeps_a_tight_burst_together():
    assert len(intake.cluster(_shots(0, 5, 10, 40, 55), gap=60)) == 1


def test_cluster_of_one_photo():
    assert [len(g) for g in intake.cluster(_shots(0), gap=60)] == [1]


def test_gap_is_exclusive_at_the_boundary():
    """Exactly `gap` stays together; one second more splits."""
    assert len(intake.cluster(_shots(0, 60), gap=60)) == 1
    assert len(intake.cluster(_shots(0, 61), gap=60)) == 2


def test_merge_folds_into_the_lower_group():
    groups = intake.cluster(_shots(0, 200, 400), gap=60)
    assert len(groups) == 3
    merged = intake.merge(groups, [(1, 2)])
    assert [len(g) for g in merged] == [2, 1]


def test_merge_rejects_a_group_that_does_not_exist():
    groups = intake.cluster(_shots(0, 200), gap=60)
    with pytest.raises(ValueError, match="there are 2"):
        intake.merge(groups, [(1, 5)])


def test_filename_timestamp_is_read_when_exif_is_missing(tmp_path):
    """WhatsApp and other re-encoders strip EXIF but keep the name."""
    p = tmp_path / "IMG_20260825_223945.jpg"
    Image.new("RGB", (8, 8), "white").save(p)
    assert intake.photo_time(str(p)) == datetime.datetime(2026, 8, 25, 22, 39, 45)


def test_unparseable_name_falls_back_to_mtime(tmp_path):
    p = tmp_path / "photo.jpg"
    Image.new("RGB", (8, 8), "white").save(p)
    assert isinstance(intake.photo_time(str(p)), datetime.datetime)


def test_apply_names_the_first_photo_front(tmp_path):
    src = tmp_path / "shoot"; src.mkdir()
    for n in ("IMG_20260825_220000.jpg", "IMG_20260825_220005.jpg"):
        Image.new("RGB", (8, 8), "white").save(src / n)
    groups = intake.cluster(intake.discover(str(src)))
    dest = tmp_path / "input"
    intake.apply(groups, {1: "TEST-SKU"}, str(dest))
    assert sorted(os.listdir(dest / "TEST-SKU")) == ["angle2.jpg", "front.jpg"]


def test_apply_copies_so_the_shoot_folder_survives(tmp_path):
    src = tmp_path / "shoot"; src.mkdir()
    Image.new("RGB", (8, 8), "white").save(src / "IMG_20260825_220000.jpg")
    groups = intake.cluster(intake.discover(str(src)))
    intake.apply(groups, {1: "TEST-SKU"}, str(tmp_path / "input"))
    assert (src / "IMG_20260825_220000.jpg").exists()


def test_apply_refuses_to_clobber_an_existing_product(tmp_path):
    """A wrong --name must not silently replace a product's real photos."""
    src = tmp_path / "shoot"; src.mkdir()
    Image.new("RGB", (8, 8), "white").save(src / "IMG_20260825_220000.jpg")
    dest = tmp_path / "input"; (dest / "TAKEN").mkdir(parents=True)
    Image.new("RGB", (8, 8), "black").save(dest / "TAKEN" / "front.jpg")
    groups = intake.cluster(intake.discover(str(src)))
    with pytest.raises(FileExistsError, match="--overwrite"):
        intake.apply(groups, {1: "TAKEN"}, str(dest))
    intake.apply(groups, {1: "TAKEN"}, str(dest), overwrite=True)   # allowed explicitly


def test_unnamed_groups_get_an_obvious_placeholder(tmp_path):
    src = tmp_path / "shoot"; src.mkdir()
    Image.new("RGB", (8, 8), "white").save(src / "IMG_20260825_220000.jpg")
    groups = intake.cluster(intake.discover(str(src)))
    written = intake.apply(groups, {}, str(tmp_path / "input"))
    assert written[0][0].startswith("UNNAMED-")


@pytest.mark.slow
def test_the_real_shoot_groups_as_it_was_sorted_by_hand():
    """raw_footages/ is a 28-photo shoot of six products, grouped by hand and
    verified against the images. Time alone over-splits it by exactly one — the
    packaging shots sit two minutes before the product shots — which is why the
    stage proposes rather than applies."""
    if not os.path.isdir("raw_footages"):
        pytest.skip("no raw_footages/ to check against")
    shots = intake.discover("raw_footages")
    if len(shots) != 28:
        pytest.skip("raw_footages/ is not the reference shoot")
    groups = intake.cluster(shots)
    assert len(groups) == 7, "the reference shoot over-splits into exactly 7"
    assert [len(g) for g in intake.merge(groups, [(4, 5)])] == [4, 3, 4, 6, 5, 6]
