#!/usr/bin/env python3
"""
Background providers for the lifestyle slots (3 & 4).

A provider returns a *bare* square background scene (PIL RGBA, W x W). The
pipeline then composites the REAL product cutout on top — the scene is never
trusted to contain the product, which keeps every listing product-faithful.

    ProceduralProvider   free, offline, works everywhere (default / fallback)

Draw Things note: this Linux dev box can't reach a Draw Things server, so the
gRPC provider is written against Draw Things' documented interface and MUST be
finalized/verified on your Mac (see DRAWTHINGS_SETUP.md). If it can't connect or
errors, it logs a warning and falls back to ProceduralProvider so the batch
never dies.
"""

import os
import sys
from PIL import Image, ImageFilter
import make_hero as mh

W = mh.W


def _tint(theme, variant):
    """Slightly shift the procedural background per variant so A/B differ."""
    shifts = {
        "A": {"bg_top": (232, 244, 255)},   # cool daylight
        "B": {"bg_top": (255, 244, 236)},   # warm daylight
    }
    return {**theme, **shifts.get(variant, {})}


class BackgroundProvider:
    name = "base"

    def scene(self, sku, cutout_path, original_path, variant, prompt, category=None):
        raise NotImplementedError


class ProceduralProvider(BackgroundProvider):
    """Soft studio gradient + bokeh. Free, deterministic, always available."""
    name = "procedural"

    def scene(self, sku, cutout_path, original_path, variant, prompt, category=None):
        theme = _tint(mh.THEME, variant)
        return mh.make_background(theme)


class FolderProvider(BackgroundProvider):
    """Reads pre-made scene plates from ./backgrounds.

    Resolution order, most specific first:
        backgrounds/<SKU>_a.*        a plate you made for this one product
        backgrounds/<category>_a.*   the shared plate for its category
        backgrounds/_a.*             one look for the whole catalog
    then procedural, so a missing file never kills the batch.

    Category plates are the intended path: a thousand products do not need a
    thousand rooms, and a storefront whose lifestyle shots share a look reads as
    more considered, not less. `python scenes.py` writes placeholder plates;
    replace them with Draw Things output under the same names.
    """
    name = "folder"
    BG_DIR = "backgrounds"
    EXTS = (".png", ".jpg", ".jpeg", ".webp")

    def __init__(self):
        self._fallback = ProceduralProvider()

    def _find(self, sku, variant, category):
        v = variant.lower()
        stems = [f"{sku}_{v}"]
        if category:
            stems.append(f"{category}_{v}")
        stems.append(f"_{v}")
        for stem in stems:
            for ext in self.EXTS:
                p = os.path.join(self.BG_DIR, stem + ext)
                if os.path.exists(p):
                    return p
        return None

    def scene(self, sku, cutout_path, original_path, variant, prompt, category=None):
        p = self._find(sku, variant, category)
        if p is None:
            print(f"  [folder] no plate for {sku}/{variant} in {self.BG_DIR}/ "
                  f"(wanted {sku}_{variant.lower()}.* or "
                  f"{category}_{variant.lower()}.*); using procedural",
                  file=sys.stderr)
            return self._fallback.scene(sku, cutout_path, original_path, variant,
                                        prompt, category)
        return Image.open(p).convert("RGBA").resize((W, W), Image.LANCZOS)


def get_provider(name):
    return {"procedural": ProceduralProvider,
            "folder": FolderProvider}[name]()
