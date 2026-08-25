#!/usr/bin/env python3
"""
Scene categories and stand-in background plates.

Generating a unique room for each of a thousand products is slow, expensive and
pointless — a storefront reads as *more* professional when its lifestyle shots
share a look. So scenes are chosen by product category and reused:

    backgrounds/<category>_a.jpg      one plate per category, per variant
    backgrounds/<SKU>_a.jpg           a per-product override, if you make one

`category_for()` picks the category from the product's own copy. The plates this
module draws are placeholders: they prove the wiring and look better than a flat
gradient, but the real ones should come out of Draw Things (SDXL, 1024px,
upscaled to 2048 — see DRAWTHINGS_SETUP.md) and be dropped into backgrounds/
under the same names.

    python scenes.py                 # write placeholder plates for every category
    python scenes.py --list          # show which category each SKU resolves to
"""

import argparse
import glob
import json
import os
import random

from PIL import Image, ImageDraw, ImageFilter

BG_DIR = "backgrounds"
PLATE_PX = 1600

# Keyword -> category. First by weight of matches, defaulting to playroom.
CATEGORY_KEYWORDS = {
    "outdoor": ("scooter", "ride-on", "ride on", "bike", "tricycle", "trike",
                "skate", "outdoor", "sport", "football", "soccer", "ball",
                "drone", "rc ", "remote control", "car", "racing"),
    "garden":  ("plant", "grow", "garden", "seed", "greenhouse", "flower",
                "nature", "botany", "terrarium"),
    "desk":    ("stem", "educational", "learning", "learn", "puzzle", "alphabet",
                "number", "laptop", "science", "craft", "art", "drawing",
                "board game", "wooden", "montessori"),
    "nursery": ("plush", "soft toy", "stuffed", "teddy", "baby", "infant",
                "cuddle", "doll", "rattle", "night lamp"),
}
DEFAULT_CATEGORY = "playroom"
CATEGORIES = tuple(CATEGORY_KEYWORDS) + (DEFAULT_CATEGORY,)

# Wall / floor colours per category, per variant. Kept desaturated so the
# product and its headline stay the loudest things on the image.
PALETTES = {
    "playroom": {"A": ((236, 242, 250), (214, 205, 194)),
                 "B": ((250, 242, 234), (206, 196, 184))},
    "outdoor":  {"A": ((214, 233, 248), (196, 206, 186)),
                 "B": ((236, 240, 226), (186, 196, 172))},
    "garden":   {"A": ((226, 240, 228), (190, 178, 160)),
                 "B": ((238, 244, 226), (178, 172, 150))},
    "desk":     {"A": ((242, 238, 230), (196, 176, 150)),
                 "B": ((234, 238, 244), (188, 172, 152))},
    "nursery":  {"A": ((248, 236, 240), (222, 210, 206)),
                 "B": ((240, 236, 248), (214, 206, 212))},
}


def category_for(content):
    """Scene category for a product, from its title, name and tags."""
    hay = " ".join([
        str(content.get("title", "")), str(content.get("name", "")),
        " ".join(content.get("tags", []) or []),
    ]).lower()
    scores = {cat: sum(1 for kw in words if kw in hay)
              for cat, words in CATEGORY_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else DEFAULT_CATEGORY


# --------------------------------------------------------------------------- #
# Placeholder plates
# --------------------------------------------------------------------------- #
def make_plate(category, variant, size=PLATE_PX):
    """A soft, out-of-focus room: tinted wall, floor plane, depth blobs.

    Composed for the hero templates — the left third stays calm so headline text
    stays readable, and the horizon sits where products are placed so they look
    like they are standing on something.
    """
    wall, floor = PALETTES.get(category, PALETTES[DEFAULT_CATEGORY])[variant]
    rng = random.Random(f"{category}{variant}")          # deterministic plates
    img = Image.new("RGB", (size, size), wall)
    d = ImageDraw.Draw(img)

    # wall gradient, lighter toward the horizon
    horizon = int(size * 0.66)
    for y in range(horizon):
        t = y / horizon
        d.line([(0, y), (size, y)],
               fill=tuple(int(c + (255 - c) * (t * 0.55)) for c in wall))

    # floor plane, receding darker toward the bottom
    for y in range(horizon, size):
        t = (y - horizon) / max(1, size - horizon)
        d.line([(0, y), (size, y)],
               fill=tuple(int(c * (1 - t * 0.22)) for c in floor))

    # depth blobs — furniture, foliage, light. Kept off the left third.
    blobs = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blobs)
    for _ in range(7):
        cx = rng.randint(int(size * 0.34), int(size * 1.02))
        cy = rng.randint(int(size * 0.10), horizon)
        r = rng.randint(int(size * 0.07), int(size * 0.20))
        shade = rng.choice([(255, 255, 255, 70), (0, 0, 0, 26),
                            tuple(int(c * 0.82) for c in floor) + (44,)])
        bd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=shade)
    img = Image.alpha_composite(img.convert("RGBA"),
                                blobs.filter(ImageFilter.GaussianBlur(size // 26)))

    # contact shading along the horizon so products do not look pasted on
    band = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(band).rectangle([0, horizon - size // 90, size, horizon + size // 60],
                                   fill=(0, 0, 0, 34))
    img = Image.alpha_composite(img, band.filter(ImageFilter.GaussianBlur(size // 45)))

    # vignette keeps attention centred
    vig = Image.new("L", (size, size), 0)
    ImageDraw.Draw(vig).ellipse([-size // 5, -size // 5, size + size // 5, size + size // 5],
                                fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(size // 12))
    dark = Image.new("RGBA", (size, size), (26, 30, 40, 62))
    img = Image.composite(img, Image.alpha_composite(img, dark), vig)
    return img.convert("RGB").filter(ImageFilter.GaussianBlur(size / 340))


def write_plates(out_dir=BG_DIR, overwrite=False):
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for category in CATEGORIES:
        for variant in ("a", "b"):
            path = os.path.join(out_dir, f"{category}_{variant}.jpg")
            if os.path.exists(path) and not overwrite:
                print(f"  = {path} (kept — pass --overwrite to replace)")
                continue
            make_plate(category, variant.upper()).save(path, quality=90)
            written.append(path)
            print(f"  -> {path}")
    return written


def _list_categories():
    for path in sorted(glob.glob(os.path.join("input", "*", "product.json"))):
        with open(path, encoding="utf-8") as fh:
            content = json.load(fh)
        sku = os.path.basename(os.path.dirname(path))
        print(f"{sku:26s} -> {category_for(content)}")


def main():
    ap = argparse.ArgumentParser(description="Scene categories and placeholder plates.")
    ap.add_argument("--list", action="store_true",
                    help="show the category each SKU resolves to, and stop")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace plates that already exist (e.g. your real ones)")
    args = ap.parse_args()

    if args.list:
        _list_categories()
        return 0
    write_plates(overwrite=args.overwrite)
    print("\nThese are placeholders. Replace them with Draw Things plates using "
          "the same filenames — see DRAWTHINGS_SETUP.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
