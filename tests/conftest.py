"""Shared fixtures.

The 12 products under input/ and output/ are the fixtures. They are real photos
that have been through the whole pipeline, so the tests assert against the thing
that actually ships rather than a synthetic stand-in. Tests that need a built
gallery skip cleanly when output/ is absent.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture(scope="session")
def repo_root():
    return ROOT


@pytest.fixture(scope="session")
def built_skus():
    """SKUs with a rendered gallery, or skip."""
    out = os.path.join(ROOT, "output")
    if not os.path.isdir(out):
        pytest.skip("no output/ — run 'python gallery_pipeline.py' first")
    skus = sorted(d for d in os.listdir(out)
                  if not d.startswith("_")
                  and os.path.isdir(os.path.join(out, d)))
    if not skus:
        pytest.skip("output/ has no built products")
    return skus


@pytest.fixture(scope="session")
def gallery_images(built_skus):
    """(sku, slot, path) for every rendered image."""
    import slots
    out = os.path.join(ROOT, "output")
    items = []
    for sku in built_skus:
        d = os.path.join(out, sku)
        for f in sorted(os.listdir(d)):
            if f.lower().endswith((".webp", ".jpg", ".png")):
                items.append((sku, slots.slot_name(f), os.path.join(d, f)))
    return items
