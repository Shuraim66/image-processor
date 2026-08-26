#!/usr/bin/env python3
"""The gallery slot vocabulary: what images a listing has, and in what order.

This lives in its own module because three unrelated places need it — the
pipeline that renders the slots, the exporter that orders them for Shopify, and
the quality checks that know which ones carry the brand mark. Importing the
orchestrator just to read a tuple made the exporter depend on the renderer.
"""

import os

# Filenames say what each image is; the listing order lives here rather than in a
# numeric prefix, so Shopify positions stay right without "01_" in front of every
# name. Slots that do not apply to a product are simply absent.
SLOT_ORDER = (
    "catalog-hero",           # product on a scene, no text on it at all
    "white-background",       # marketplace main image
    "with-packaging",         # product shown with its retail box
    "every-angle",            # the other shots you took
    "lifestyle-scene",        # in a room, from a second angle
    "features-and-benefits",  # the branded feature card
    "size-and-specs",         # only when real measurements exist
    "close-up-detail",
)

# Slots that must stay free of the brand mark. Google Merchant Center disapproves
# product images carrying a watermark or logo, and these two are the plain
# product-on-white shots a marketplace feed reaches for. Everything else in
# SLOT_ORDER is a branded creative and must carry it.
CLEAN_SLOTS = ("white-background", "with-packaging")

BRANDED_SLOTS = tuple(s for s in SLOT_ORDER if s not in CLEAN_SLOTS)


def slot_name(filename):
    """The slot a rendered file belongs to, i.e. its stem."""
    return os.path.splitext(os.path.basename(filename))[0]


def slot_sort_key(filename):
    """Position in SLOT_ORDER, unknown names last, for a stable gallery order."""
    stem = slot_name(filename)
    return (SLOT_ORDER.index(stem) if stem in SLOT_ORDER else len(SLOT_ORDER), stem)
