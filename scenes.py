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
# Soft silhouettes per category, as (x, y, w, h) fractions. Blurred hard at the
# end, so these read as out-of-focus furniture rather than shapes.
SILHOUETTES = {
    "playroom": [(-.06, .30, .22, .38), (.80, .24, .28, .44), (.62, .44, .16, .24)],
    "outdoor":  [(-.10, .10, .30, .52), (.78, .04, .34, .58)],
    "garden":   [(-.08, .06, .28, .40), (.76, .00, .32, .40), (.86, .40, .20, .28)],
    "desk":     [(.72, .22, .14, .44), (.86, .18, .12, .48), (-.04, .34, .14, .32)],
    "nursery":  [(-.05, .22, .24, .34), (.80, .16, .26, .40)],
}


def _perspective_floor(img, horizon, floor, size, rng):
    """Converging floor lines. This is what makes a gradient read as a room."""
    d = ImageDraw.Draw(img, "RGBA")
    vx = int(size * 0.5)
    line = tuple(int(c * 0.86) for c in floor)

    # boards running away from the viewer, toward a vanishing point
    for i in range(-9, 10):
        x_bottom = vx + i * int(size * 0.17)
        d.line([(vx, horizon), (x_bottom, size)], fill=line + (58,), width=max(1, size // 700))

    # cross-joints, spaced so they crowd toward the horizon
    depth = size - horizon
    for step in range(1, 9):
        y = horizon + depth * (step / 9) ** 2.1
        d.line([(0, y), (size, y)], fill=line + (44,), width=max(1, size // 800))


def _window_light(img, horizon, size, from_left):
    """A soft bright panel on the wall plus its spill on the floor."""
    glow = Image.new("L", (size, size), 0)
    g = ImageDraw.Draw(glow)
    x0 = int(size * (0.04 if from_left else 0.62))
    g.rectangle([x0, int(size * 0.06), x0 + int(size * 0.34), int(horizon * 0.92)], fill=210)
    # spill, widening as it falls across the floor
    spill_x = x0 + int(size * (0.10 if from_left else 0.06))
    g.polygon([(spill_x, horizon), (spill_x + int(size * 0.26), horizon),
               (spill_x + int(size * 0.46), size), (spill_x - int(size * 0.20), size)],
              fill=120)
    glow = glow.filter(ImageFilter.GaussianBlur(size // 14))
    return Image.composite(Image.new("RGBA", (size, size), (255, 253, 246, 255)), img, glow)


def make_plate(category, variant, size=PLATE_PX):
    """A soft, out-of-focus room: wall, perspective floor, window light, depth.

    Composed for the hero templates — the left third stays calm so headline text
    stays readable, and the floor plane runs through where products are placed so
    they look like they are standing on something rather than floating.
    """
    wall, floor = PALETTES.get(category, PALETTES[DEFAULT_CATEGORY])[variant]
    rng = random.Random(f"{category}{variant}")          # deterministic plates
    horizon = int(size * 0.66)
    img = Image.new("RGB", (size, size), wall)
    d = ImageDraw.Draw(img)

    # wall, lightening toward the horizon
    for y in range(horizon):
        t = y / horizon
        d.line([(0, y), (size, y)],
               fill=tuple(int(c + (255 - c) * (t * 0.5)) for c in wall))

    # floor, darkening toward the viewer
    for y in range(horizon, size):
        t = (y - horizon) / max(1, size - horizon)
        d.line([(0, y), (size, y)],
               fill=tuple(int(c * (1 - t * 0.26)) for c in floor))

    img = img.convert("RGBA")
    _perspective_floor(img, horizon, floor, size, rng)

    # furniture and foliage, pushed to the edges to keep the middle usable
    shapes = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shapes)
    for fx, fy, fw, fh in SILHOUETTES.get(category, SILHOUETTES[DEFAULT_CATEGORY]):
        box = [fx * size, fy * size, (fx + fw) * size, (fy + fh) * size]
        tone = tuple(int(c * 0.74) for c in floor) + (rng.randint(52, 78),)
        sd.rounded_rectangle(box, radius=size * 0.06, fill=tone)
    img = Image.alpha_composite(img, shapes.filter(ImageFilter.GaussianBlur(size // 22)))

    img = _window_light(img, horizon, size, from_left=(variant == "A"))

    # contact shading where wall meets floor, so products sit rather than float
    band = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(band).rectangle(
        [0, horizon - size // 120, size, horizon + size // 44], fill=(0, 0, 0, 42))
    img = Image.alpha_composite(img, band.filter(ImageFilter.GaussianBlur(size // 50)))

    # vignette keeps attention centred
    vig = Image.new("L", (size, size), 0)
    ImageDraw.Draw(vig).ellipse(
        [-size // 5, -size // 5, size + size // 5, size + size // 5], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(size // 12))
    dark = Image.new("RGBA", (size, size), (26, 30, 40, 66))
    img = Image.composite(img, Image.alpha_composite(img, dark), vig)

    # shallow depth of field: the whole plate is background, so none of it is sharp
    return img.convert("RGB").filter(ImageFilter.GaussianBlur(size / 190))


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
