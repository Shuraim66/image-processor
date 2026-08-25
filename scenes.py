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
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

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
                "number", "laptop", "science", "board game", "wooden",
                "montessori", "reading", "maths", "math"),
    "nursery": ("plush", "soft toy", "stuffed", "teddy", "baby", "infant",
                "cuddle", "doll", "rattle", "night lamp"),
    "creative": ("art", "craft", "crafts", "paint", "painting", "drawing",
                 "colouring", "coloring", "beads", "jewellery", "clay",
                 "sticker", "creative", "make your own", "diy"),
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
    "creative": {"A": ((250, 244, 232), (208, 190, 166)),
                 "B": ((244, 240, 248), (200, 186, 168))},
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
    "creative": [(.74, .26, .18, .40), (.88, .20, .14, .46), (-.06, .30, .18, .34)],
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


# --------------------------------------------------------------------------- #
# Preparing a photo (or a generated image) into a usable plate
# --------------------------------------------------------------------------- #
# Geometry the hero templates assume. A plate that ignores these still renders,
# but the headline lands on clutter and the product appears to float.
TEXT_ZONE = 0.42          # left fraction reserved for the headline column
HORIZON_TARGET = 0.66     # where the surface should sit, as a fraction of height
HORIZON_BAND = (0.50, 0.84)
CALM_STDDEV = 34          # above this, the text zone is too busy to read on


def _detect_horizon(img):
    """Fraction down the image where the strongest horizontal edge sits.

    Row-mean brightness changes fastest where a wall meets a floor, which is the
    line a product needs to stand on. Returns None when nothing stands out.
    """
    grey = np.asarray(img.convert("L").resize((96, 96), Image.BILINEAR), float)
    rows = grey.mean(axis=1)
    lo, hi = int(96 * HORIZON_BAND[0]), int(96 * HORIZON_BAND[1])
    steps = np.abs(np.diff(rows))[lo:hi]
    if steps.size == 0 or steps.max() < 1.5:
        return None
    return (lo + int(steps.argmax())) / 96


def _square_on_horizon(img):
    """Crop to a square, sliding the crop so the horizon lands where we want."""
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    found = _detect_horizon(img)
    if found is None:
        top = (h - side) // 2
    else:
        # place the detected line at HORIZON_TARGET within the crop
        top = int(found * h - HORIZON_TARGET * side)
        top = max(0, min(h - side, top))
    return img.crop((left, top, left + side, top + side))


def _calm_text_zone(img, size):
    """Blur and lift the headline column until type can sit on it."""
    zone_w = int(size * TEXT_ZONE)
    zone = img.crop((0, 0, zone_w, size))
    busy = float(np.asarray(zone.convert("L"), float).std())
    if busy > CALM_STDDEV:
        zone = zone.filter(ImageFilter.GaussianBlur(size / 90))
    veil = Image.new("RGBA", (zone_w, size), (255, 255, 255, 0))
    grad = Image.new("L", (zone_w, 1))
    for x in range(zone_w):                       # strongest at the left edge
        grad.putpixel((x, 0), int(120 * (1 - x / zone_w) ** 1.4))
    veil.putalpha(grad.resize((zone_w, size)))
    zone = Image.alpha_composite(zone.convert("RGBA"), veil)
    img.paste(zone.convert("RGB"), (0, 0))
    return busy


def prepare_plate(img, size=PLATE_PX):
    """Turn any photo into a plate the templates can use. -> (image, report)."""
    img = ImageOps.exif_transpose(img).convert("RGB")
    before = _detect_horizon(img)
    img = _square_on_horizon(img).resize((size, size), Image.LANCZOS)

    # Every plate is background behind a product and a headline, so none of it
    # should be sharp enough to compete.
    img = img.filter(ImageFilter.GaussianBlur(size / 200))
    busy = _calm_text_zone(img, size)

    vig = Image.new("L", (size, size), 0)
    ImageDraw.Draw(vig).ellipse(
        [-size // 5, -size // 5, size + size // 5, size + size // 5], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(size // 12))
    dark = Image.new("RGBA", (size, size), (26, 30, 40, 52))
    img = Image.composite(img.convert("RGBA"),
                          Image.alpha_composite(img.convert("RGBA"), dark), vig)

    after = _detect_horizon(img)
    return img.convert("RGB"), {
        "horizon_before": round(before, 3) if before else None,
        "horizon_after": round(after, 3) if after else None,
        "text_zone_stddev": round(busy, 1),
        "warnings": _plate_warnings(before, after, busy),
    }


def _plate_warnings(before, after, busy):
    out = []
    if before is None:
        out.append("no clear surface line — the product may look like it is floating")
    elif after is not None and abs(after - HORIZON_TARGET) > 0.09:
        out.append(f"surface sits at {after:.2f}, wanted ~{HORIZON_TARGET} "
                   f"(crop could not slide far enough)")
    if busy > CALM_STDDEV * 1.6:
        out.append(f"headline column is busy (stddev {busy:.0f}) — "
                   f"blurred and lifted, but check the hero")
    return out


def prepare_folder(src_dir, out_dir=BG_DIR, size=PLATE_PX):
    """Prep every image in a folder. Names are kept, so drop in
    playroom_a.jpg / outdoor_b.png etc. and they land where the pipeline looks."""
    exts = (".jpg", ".jpeg", ".png", ".webp")
    files = sorted(f for f in os.listdir(src_dir) if f.lower().endswith(exts))
    if not files:
        print(f"No images in {src_dir}", file=sys.stderr)
        return []
    os.makedirs(out_dir, exist_ok=True)
    done = []
    for name in files:
        with Image.open(os.path.join(src_dir, name)) as raw:
            plate, report = prepare_plate(raw, size)
        dest = os.path.join(out_dir, os.path.splitext(name)[0] + ".jpg")
        plate.save(dest, quality=90)
        done.append(dest)
        note = "  ".join(report["warnings"]) or "ok"
        print(f"  -> {dest}  horizon {report['horizon_after']}  {note}")
    return done


# --------------------------------------------------------------------------- #
# Generating with mflux (local, Apple Silicon, FLUX.1 schnell is Apache 2.0)
# --------------------------------------------------------------------------- #
SCENE_PROMPTS = {
    "playroom": "empty modern children's playroom, plain pale wall on the left, "
                "wide unbroken wooden floor across the foreground",
    "outdoor":  "empty sunlit garden path beside a lawn, plain fence on the left, "
                "wide smooth paving across the foreground",
    "garden":   "empty potting bench in a bright greenhouse, plain wall on the "
                "left, wide clear wooden surface across the foreground",
    "desk":     "empty light wooden study table by a window, plain wall on the "
                "left, wide clear tabletop across the foreground",
    "nursery":  "empty soft nursery corner, plain pastel wall on the left, "
                "wide clear carpet across the foreground",
    "creative": "empty craft table with paper and paint pots pushed to the far "
                "right, plain wall on the left, wide clear tabletop in front",
}
PROMPT_SUFFIX = ("soft daylight from the {side}, shallow depth of field, "
                 "product photography backdrop, no people, no toys, no text")
NEGATIVE = "people, hands, children, toys, products, text, watermark, logo, clutter"


def mflux_available():
    return shutil.which("mflux-generate") or shutil.which("mf-txt2img")


def generate_with_mflux(category, variant, out_path, size=1024, steps=4, seed=None):
    """Run mflux for one plate. Raises RuntimeError with the fix if it is absent."""
    exe = mflux_available()
    if not exe:
        raise RuntimeError(
            "mflux is not installed. Install it (a one-time ~9.9 GB model "
            "download on first run):\n    pip install mflux")
    side = "left" if variant.upper() == "A" else "right"
    prompt = f"{SCENE_PROMPTS[category]}, {PROMPT_SUFFIX.format(side=side)}"
    cmd = [exe, "--model", "schnell", "-q", "4", "--low-ram",
           "--steps", str(steps), "--width", str(size), "--height", str(size),
           "--seed", str(seed if seed is not None else abs(hash((category, variant))) % 10**6),
           "--prompt", prompt, "--output", out_path]
    print(f"  [{category}_{variant.lower()}] {' '.join(cmd[:8])} ...")
    subprocess.run(cmd, check=True)
    return out_path


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


def _list_categories(out_dir="output"):
    paths = sorted(glob.glob(os.path.join(out_dir, "*", "product.json")))
    if not paths:   # pre-output-root runs kept profiles beside the photos
        paths = sorted(glob.glob(os.path.join("input", "*", "product.json")))
    if not paths:
        print("No product.json found — run analyzer.py first.")
        return
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            content = json.load(fh)
        sku = os.path.basename(os.path.dirname(path))
        print(f"  {sku:26s} -> {category_for(content):9s} "
              f"({', '.join(content.get('tags', [])[:4])})")


def main():
    ap = argparse.ArgumentParser(description="Scene categories and placeholder plates.")
    ap.add_argument("--list", action="store_true",
                    help="show the category each SKU resolves to, and stop")
    ap.add_argument("--out-dir", default="output", metavar="DIR",
                    help="where product.json files live (default output/)")
    ap.add_argument("--prepare", metavar="DIR",
                    help="prep every image in DIR into a template-ready plate "
                         "(stock photos, mflux output, anything). Filenames are "
                         "kept, so name them <category>_a.jpg")
    ap.add_argument("--generate", action="store_true",
                    help="generate plates locally with mflux, then prep them")
    ap.add_argument("--category", metavar="NAME",
                    help="with --generate, only this scene category")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace plates that already exist (e.g. your real ones)")
    args = ap.parse_args()

    if args.list:
        _list_categories(args.out_dir)
        return 0

    if args.prepare:
        prepare_folder(args.prepare)
        return 0

    if args.generate:
        cats = [args.category] if args.category else list(CATEGORIES)
        bad = [c for c in cats if c not in SCENE_PROMPTS]
        if bad:
            print(f"Unknown category: {', '.join(bad)}. "
                  f"Known: {', '.join(CATEGORIES)}", file=sys.stderr)
            return 1
        if not mflux_available():
            print("mflux is not installed. One-time setup:\n"
                  "    pip install mflux\n"
                  "The first generation downloads FLUX.1 schnell 4-bit (~9.9 GB); "
                  "it is Apache 2.0, so the images are yours to use commercially.",
                  file=sys.stderr)
            return 1
        os.makedirs(BG_DIR, exist_ok=True)
        raw_dir = os.path.join(BG_DIR, "_raw")
        os.makedirs(raw_dir, exist_ok=True)
        for cat in cats:
            for variant in ("a", "b"):
                raw = os.path.join(raw_dir, f"{cat}_{variant}.png")
                try:
                    generate_with_mflux(cat, variant, raw)
                except (RuntimeError, subprocess.CalledProcessError) as exc:
                    print(f"  ! {cat}_{variant}: {exc}", file=sys.stderr)
                    continue
                with Image.open(raw) as img:
                    plate, report = prepare_plate(img)
                dest = os.path.join(BG_DIR, f"{cat}_{variant}.jpg")
                plate.save(dest, quality=90)
                note = "  ".join(report["warnings"]) or "ok"
                print(f"  -> {dest}  horizon {report['horizon_after']}  {note}")
        print(f"\nRaw model output kept in {raw_dir}/ so you can re-prep "
              f"without regenerating.")
        return 0
    write_plates(overwrite=args.overwrite)
    print("\nThese are drawn, not photographed. Replace them any time with\n"
          "  python scenes.py --generate      (local mflux)\n"
          "  python scenes.py --prepare DIR   (photos you supply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
