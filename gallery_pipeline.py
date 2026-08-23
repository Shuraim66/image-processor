#!/usr/bin/env python3
"""
Full listing-gallery pipeline — produces the 7-image set per product.

Slots (hero-heavy recipe):
    01_main         pure white catalog (no watermark)      free
    02_hero         branded hero (procedural background)   free
    03_lifestyle_a  product in a scene (variant A)         provider
    04_lifestyle_b  product in a scene (variant B)         provider
    05_infographic  feature callouts                       free
    06_size         size & age card                        free (specs.json)
    07_detail       detail close-up                        free

Background provider for slots 3-4 is pluggable:
    --bg-provider procedural   (default, free, offline)
    --bg-provider drawthings   (local Draw Things gRPC on your Mac)

    python gallery_pipeline.py                       # all SKUs, procedural
    python gallery_pipeline.py --sku SCOOTER-LED-PINK --bg-provider drawthings
    python gallery_pipeline.py --no-gemini           # deterministic copy, no API
"""

import argparse
import json
import os
import sys
import traceback

from PIL import Image

import process_products as pp
import make_hero as mh
import gallery
import content as content_mod
import providers

OUTPUT_ROOT = "gallery_out"
CUTOUT_DIR = "gallery_out/_cutouts"
SPECS_PATH = "specs.json"


def load_specs():
    with open(SPECS_PATH, encoding="utf-8") as f:
        return json.load(f)


def specs_for(specs, sku):
    return {**specs.get("_default", {}), **specs.get(sku, {})}


def make_cutout(raw_path, sku):
    """Transparent, trimmed cutout via the full rembg model (cached across SKUs)."""
    os.makedirs(CUTOUT_DIR, exist_ok=True)
    out = os.path.join(CUTOUT_DIR, f"{sku}.png")
    src = Image.open(raw_path).convert("RGBA")
    cut = pp.trim_to_content(pp.remove_background(src))
    cut.save(out)
    return out


def build_for_sku(sku, specs, provider, use_gemini):
    folder = os.path.join(pp.INPUT_DIR, sku)
    raws = pp.raw_images_in(folder)
    if not raws:
        print(f"  ! no images for {sku}", file=sys.stderr)
        return []
    out_dir = os.path.join(OUTPUT_ROOT, sku)
    os.makedirs(out_dir, exist_ok=True)

    primary_raw = raws[0]
    cutout = make_cutout(primary_raw, sku)
    cont = content_mod.build_content(sku, primary_raw, use_gemini=use_gemini)
    sp = specs_for(specs, sku)
    made = []

    # 01 — pure white main (no watermark; marketplace-safe)
    p = os.path.join(out_dir, "01_main.jpg")
    pp.process_image(primary_raw, None).save(p, quality=94); made.append(p)

    # 02 — branded hero (procedural bg)
    made.append(mh.render_hero(cutout, cont, os.path.join(out_dir, "02_hero.jpg")))

    # 03/04 — lifestyle scenes (pluggable provider), real product composited on top
    prompts = cont.get("scene_prompts", []) + ["bright playroom", "sunny living room"]
    for slot, variant, prompt in [("03_lifestyle_a", "A", prompts[0]),
                                  ("04_lifestyle_b", "B", prompts[1])]:
        scene = provider.scene(sku, cutout, primary_raw, variant, prompt)
        made.append(mh.render_hero(cutout, cont,
                                   os.path.join(out_dir, f"{slot}.jpg"),
                                   background=scene))

    # 05 — feature infographic
    made.append(gallery.render_infographic(cutout, cont,
                os.path.join(out_dir, "05_infographic.jpg")))

    # 06 — size & age card
    made.append(gallery.render_size_card(cutout, {
        "title": sp.get("title", "SIZE & SPECS"),
        "height": sp["height"], "length": sp["length"], "badges": sp["badges"],
        "theme": cont.get("theme", {}),
    }, os.path.join(out_dir, "06_size.jpg")))

    # 07 — detail close-up
    made.append(gallery.render_detail(primary_raw, tuple(sp["detail_crop"]),
                sp.get("detail_label", "CLOSER LOOK"), cont,
                os.path.join(out_dir, "07_detail.jpg")))
    return made


def main():
    ap = argparse.ArgumentParser(description="Generate the 7-image listing gallery per product.")
    ap.add_argument("--sku", help="only this SKU (default: all under input/)")
    ap.add_argument("--bg-provider", choices=["procedural", "folder", "drawthings"],
                    default="procedural", help="background engine for slots 3-4")
    ap.add_argument("--no-gemini", action="store_true",
                    help="skip the free Gemini copy step; use deterministic fallback")
    args = ap.parse_args()

    specs = load_specs()
    provider = providers.get_provider(args.bg_provider)
    print(f"Background provider: {provider.name}")

    skus = [args.sku] if args.sku else pp.find_sku_folders(pp.INPUT_DIR)
    for i, sku in enumerate(skus, 1):
        print(f"[{i}/{len(skus)}] {sku}")
        try:
            for p in build_for_sku(sku, specs, provider, use_gemini=not args.no_gemini):
                print(f"  -> {p}")
        except Exception as exc:  # keep the batch alive
            print(f"  ! {sku} failed: {exc}", file=sys.stderr)
            traceback.print_exc()
    print(f"\nDone. Galleries in '{OUTPUT_ROOT}/<SKU>/'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
