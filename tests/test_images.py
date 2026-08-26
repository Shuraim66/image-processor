"""What actually ships: the rendered images and the cutouts behind them."""

import json
import os

import pytest
from PIL import Image

import slots


@pytest.mark.slow
def test_every_image_is_square_and_marketplace_sized(gallery_images):
    for sku, slot, path in gallery_images:
        with Image.open(path) as im:
            assert im.width == im.height, f"{sku}/{slot} is {im.size}, not square"
            # Shopify needs >800px for zoom to work at all.
            assert im.width >= 1000, f"{sku}/{slot} is only {im.width}px"


@pytest.mark.slow
def test_images_are_webp_and_opaque_rgb(gallery_images):
    for sku, slot, path in gallery_images:
        with Image.open(path) as im:
            assert im.format == "WEBP", f"{sku}/{slot} is {im.format}"
            # A stray alpha channel renders as black on some marketplace viewers.
            assert im.mode == "RGB", f"{sku}/{slot} is mode {im.mode}"


@pytest.mark.slow
def test_file_sizes_stay_in_shopifys_recommended_band(gallery_images):
    for sku, slot, path in gallery_images:
        kb = os.path.getsize(path) / 1024
        assert kb < 500, f"{sku}/{slot} is {kb:.0f} KB; Shopify advises under 500"


@pytest.mark.slow
def test_slot_names_are_all_known(gallery_images):
    for sku, slot, _ in gallery_images:
        assert slot in slots.SLOT_ORDER, f"{sku} has unknown slot '{slot}'"


@pytest.mark.slow
def test_every_product_has_the_two_slots_that_are_never_optional(built_skus):
    for sku in built_skus:
        present = {slots.slot_name(f) for f in os.listdir(os.path.join("output", sku))
                   if f.endswith(".webp")}
        for required in ("catalog-hero", "white-background"):
            assert required in present, f"{sku} is missing {required}"


@pytest.mark.slow
def test_cutouts_preserve_the_source_aspect_ratio():
    """The compositor may scale a product but must never stretch it. The sidecar
    box is the bounding box in the source photo; the cutout is what got carried
    forward, and the two must describe the same shape."""
    d = os.path.join("output", "_cutouts")
    if not os.path.isdir(d):
        pytest.skip("no cutout cache")
    checked = 0
    for side in sorted(f for f in os.listdir(d) if f.endswith(".box.json")):
        with open(os.path.join(d, side), encoding="utf-8") as fh:
            box = json.load(fh).get("box")
        png = os.path.join(d, side[:-len(".box.json")])
        if not box or not os.path.exists(png):
            continue
        x0, y0, x1, y1 = box
        src = (x1 - x0) / (y1 - y0)
        with Image.open(png) as im:
            got = im.width / im.height
        checked += 1
        assert abs(got - src) / src < 0.02, \
            f"{side}: cutout {got:.3f} vs source {src:.3f}"
    assert checked, "no cutouts with a sidecar box"
