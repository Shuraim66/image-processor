"""The Shopify CSV: the last gate before a listing goes live."""

import csv
import io
import os

import pytest

import shopify_export
import slots


def test_column_set_is_complete():
    """A trimmed column list silently drops behaviour: without Image Position the
    gallery order is whatever Shopify feels like, and without Status every import
    lands in the wrong publish state."""
    for required in ("Handle", "Title", "Variant SKU", "Image Src",
                     "Image Position", "Image Alt Text", "Status", "Published",
                     "SEO Title", "SEO Description"):
        assert required in shopify_export.COLUMNS
    assert len(shopify_export.COLUMNS) == len(set(shopify_export.COLUMNS))


def test_handles_are_slugs_without_trademarks():
    assert shopify_export.slug("Spider-Man Plush!! 40cm") == "spider-man-plush-40cm"
    assert shopify_export.slug("  ") == ""


def test_handle_collisions_fall_back_to_the_sku():
    class P:
        title = "Red Scooter"
    seen = set()
    a = shopify_export.handle_for(P(), "SCOOTER-A", "title", seen)
    b = shopify_export.handle_for(P(), "SCOOTER-B", "title", seen)
    assert a != b, "two products cannot share a URL"
    assert "scooter-b" in b


@pytest.mark.slow
def test_generated_csv_orders_images_by_slot(tmp_path, built_skus):
    """Image Position must follow the listing order, not the alphabet."""
    import subprocess, sys
    out = tmp_path / "shopify.csv"
    r = subprocess.run([sys.executable, "shopify_export.py", "--out", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rows = list(csv.DictReader(io.open(out, encoding="utf-8")))
    if not rows:
        pytest.skip("every product was held back for review")

    by_handle = {}
    for row in rows:
        if row["Image Src"]:
            by_handle.setdefault(row["Handle"], []).append(
                (int(row["Image Position"]), slots.slot_name(row["Image Src"])))
    assert by_handle
    for handle, entries in by_handle.items():
        entries.sort()
        positions = [p for p, _ in entries]
        assert positions == list(range(1, len(positions) + 1)), \
            f"{handle} has gaps in Image Position: {positions}"
        names = [n for _, n in entries]
        assert names == sorted(names, key=slots.slot_sort_key), \
            f"{handle} image order is {names}"


@pytest.mark.slow
def test_handles_are_unique_across_the_export(tmp_path):
    import subprocess, sys
    out = tmp_path / "shopify.csv"
    r = subprocess.run([sys.executable, "shopify_export.py", "--out", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rows = list(csv.DictReader(io.open(out, encoding="utf-8")))
    product_rows = [x for x in rows if x["Title"]]
    handles = [x["Handle"] for x in product_rows]
    assert len(handles) == len(set(handles))
