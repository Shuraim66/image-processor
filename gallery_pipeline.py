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
import analyzer
import providers
import quality
import fal_listing

OUTPUT_ROOT = "gallery_out"
CUTOUT_DIR = "gallery_out/_cutouts"
SPECS_PATH = "specs.json"


def load_specs():
    with open(SPECS_PATH, encoding="utf-8") as f:
        return json.load(f)


def specs_for(specs, sku):
    return {**specs.get("_default", {}), **specs.get(sku, {})}


def get_profile(sku, folder, use_ollama, reanalyze):
    """Load input/<SKU>/product.json, or generate it via the analyzer.

    Returns the content dict the templates consume (a superset of the fields
    they read). product.json is the single source of truth for copy.
    """
    path = os.path.join(folder, "product.json")
    if os.path.exists(path) and not reanalyze:
        profile = analyzer.ProductProfile.model_validate_json(
            open(path, encoding="utf-8").read())
    else:
        profile = analyzer.analyze_folder(folder, use_ollama=use_ollama)
    return profile.model_dump()


def make_cutout(raw_path, sku):
    """Transparent, trimmed cutout via the full rembg model (cached across SKUs)."""
    os.makedirs(CUTOUT_DIR, exist_ok=True)
    out = os.path.join(CUTOUT_DIR, f"{sku}.png")
    src = Image.open(raw_path).convert("RGBA")
    cut = pp.trim_to_content(pp.remove_background(src))
    cut.save(out)
    return out


def build_for_sku(sku, specs, provider, use_ollama, reanalyze, ext="webp",
                  per_product=False, cache_bg=False, vlm=False):
    folder = os.path.join(pp.INPUT_DIR, sku)
    raws = pp.raw_images_in(folder)
    if not raws:
        print(f"  ! no images for {sku}", file=sys.stderr)
        return []
    # step 5: per-product folder becomes the record (products/<SKU>/output style)
    out_dir = os.path.join(folder, "output") if per_product else os.path.join(OUTPUT_ROOT, sku)
    os.makedirs(out_dir, exist_ok=True)

    primary_raw = raws[0]
    cutout = make_cutout(primary_raw, sku)
    cont = get_profile(sku, folder, use_ollama, reanalyze)
    sp = specs_for(specs, sku)
    made = []

    def op(name):
        return os.path.join(out_dir, f"{name}.{ext}")

    # 01 — pure white main (no watermark; marketplace-safe), matched to gallery size
    p = op("01_main")
    (pp.process_image(primary_raw, None)
       .resize((mh.SIZE, mh.SIZE), Image.LANCZOS)
       .save(p, quality=92)); made.append(p)

    # 02 — branded hero (procedural bg)
    made.append(mh.render_hero(cutout, cont, op("02_hero")))

    # 03/04 — lifestyle scenes (pluggable provider), real product composited on top
    prompts = cont.get("scene_prompts", []) + ["bright playroom", "sunny living room"]
    for slot, variant, prompt in [("03_lifestyle_a", "A", prompts[0]),
                                  ("04_lifestyle_b", "B", prompts[1])]:
        scene = provider.scene(sku, cutout, primary_raw, variant, prompt)
        if cache_bg:   # step 7: save the scene so a later --bg-provider folder run reuses it
            os.makedirs("backgrounds", exist_ok=True)
            scene.convert("RGB").save(os.path.join("backgrounds", f"{sku}_{variant.lower()}.{ext}"))
        made.append(mh.render_hero(cutout, cont, op(slot), background=scene))

    # 05 — feature infographic
    made.append(gallery.render_infographic(cutout, cont, op("05_infographic")))

    # 06 — size & age card
    made.append(gallery.render_size_card(cutout, {
        "title": sp.get("title", "SIZE & SPECS"),
        "height": sp["height"], "length": sp["length"], "badges": sp["badges"],
        "theme": cont.get("theme", {}),
    }, op("06_size")))

    # 07 — detail close-up
    made.append(gallery.render_detail(primary_raw, tuple(sp["detail_crop"]),
                sp.get("detail_label", "CLOSER LOOK"), cont, op("07_detail")))

    # quality report (deterministic checks + optional VLM semantic check)
    report = quality.check_gallery(sku, out_dir, mh.SIZE, cutout_path=cutout)
    if vlm:   # step 6: does the lifestyle image faithfully show the real product?
        v = quality.vlm_check(primary_raw, op("03_lifestyle_a"))
        report["vlm_check"] = v
        if v["status"] == "review":
            report["status"] = "review"
    with open(os.path.join(out_dir, "quality-report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"  -> quality: {report['status']}")
    return made


def main():
    ap = argparse.ArgumentParser(description="Generate the 7-image listing gallery per product.")
    ap.add_argument("--sku", help="only this SKU (default: all under input/)")
    ap.add_argument("--bg-provider", choices=["procedural", "folder", "drawthings", "fal"],
                    default="procedural",
                    help="scene engine. procedural/folder/drawthings = bare-bg + composite; "
                         "fal = product-in-scene listing set (CatalogHero/WhiteBG/Packshot/"
                         "Detail/Lifestyle + FeatureCard). fal needs FAL_KEY.")
    ap.add_argument("--no-ollama", action="store_true",
                    help="skip the Qwen3-VL analyzer; use deterministic fallback copy")
    ap.add_argument("--reanalyze", action="store_true",
                    help="re-run the analyzer even if product.json already exists")
    ap.add_argument("--format", choices=["webp", "jpg"], default="webp",
                    help="output image format (default webp)")
    ap.add_argument("--per-product", action="store_true",
                    help="write images + report into input/<SKU>/output/ (folder = record)")
    ap.add_argument("--cache-backgrounds", action="store_true",
                    help="save generated scenes to backgrounds/ for reuse (memory sequencing)")
    ap.add_argument("--vlm-check", action="store_true",
                    help="VLM check that the lifestyle image matches the real product")
    args = ap.parse_args()

    specs = load_specs()
    is_fal = args.bg_provider == "fal"
    provider = None if is_fal else providers.get_provider(args.bg_provider)
    print(f"Scene engine: {args.bg_provider}")

    skus = [args.sku] if args.sku else pp.find_sku_folders(pp.INPUT_DIR)
    for i, sku in enumerate(skus, 1):
        print(f"[{i}/{len(skus)}] {sku}")
        try:
            if is_fal:   # fal renders the product into each scene (product-in-scene set)
                folder = os.path.join(pp.INPUT_DIR, sku)
                cont = get_profile(sku, folder, not args.no_ollama, args.reanalyze)
                out_dir = (os.path.join(folder, "output") if args.per_product
                           else os.path.join(OUTPUT_ROOT, sku))
                fal_listing.build(sku, pp.raw_images_in(folder), cont, out_dir, ext=args.format)
            else:
                for p in build_for_sku(sku, specs, provider,
                                       use_ollama=not args.no_ollama,
                                       reanalyze=args.reanalyze, ext=args.format,
                                       per_product=args.per_product,
                                       cache_bg=args.cache_backgrounds,
                                       vlm=args.vlm_check):
                    print(f"  -> {p}")
        except Exception as exc:  # keep the batch alive
            print(f"  ! {sku} failed: {exc}", file=sys.stderr)
            traceback.print_exc()
    print(f"\nDone. Galleries in '{OUTPUT_ROOT}/<SKU>/'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
