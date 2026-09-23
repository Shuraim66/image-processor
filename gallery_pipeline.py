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
import csv
import datetime
import json
import os
import sys
import traceback

from PIL import Image
from pydantic import ValidationError

import process_products as pp
import make_hero as mh
import gallery
import analyzer
import providers
import quality
import fal_listing
import photo_tags

OUTPUT_ROOT = "gallery_out"
CUTOUT_DIR = "gallery_out/_cutouts"
SPECS_PATH = "specs.json"

# Durable record of every fal run: one row per product attempt, appended (never rewritten).
RECORDS_PATH = "processed_products.csv"
RECORD_FIELDS = ["processed_at", "sku", "provider", "status", "fal_images_new",
                 "fal_images_reused", "est_cost_usd", "output_dir", "error"]


# fal only runs for SKUs listed here (one per line, # comments) — review the free
# --dry-run plan first. Keeps paid generations to folders someone has checked.
APPROVED_PATH = "approved_skus.txt"


def load_approved():
    if not os.path.exists(APPROVED_PATH):
        return set()
    with open(APPROVED_PATH, encoding="utf-8") as f:
        return {ln.split("#")[0].strip() for ln in f if ln.split("#")[0].strip()}


def record_processed(row):
    new_file = not os.path.exists(RECORDS_PATH)
    with open(RECORDS_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RECORD_FIELDS)
        if new_file:
            w.writeheader()
        w.writerow(row)


def fal_slots_present(out_dir):
    return sum(os.path.exists(os.path.join(out_dir, s + ".png")) for s in fal_listing.SLOT_PROMPTS)


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
    profile = None
    if os.path.exists(path) and not reanalyze:
        try:
            profile = analyzer.ProductProfile.model_validate_json(
                open(path, encoding="utf-8").read())
        except ValidationError:
            # a folder sorted and tagged but with no listing copy yet: write it now (local, free).
            # The hand-curated keys survive — they are all in analyzer.MANUAL_KEYS.
            print("  no listing copy yet — analysing")
    if profile is None:
        profile = analyzer.analyze_folder(folder, use_ollama=use_ollama)
    return {**profile.model_dump(), **analyzer.manual_overrides(path)}


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

    cont = get_profile(sku, folder, use_ollama, reanalyze)
    # Which photo shows the product itself? raws[0] is usually the box front, so the main
    # image used to be a picture of the packaging. plan_slots reads the photo labels and
    # prefers an unpackaged view for the hero, falling back to the first photo.
    plan = fal_listing.plan_slots(raws, cont) if raws else {}
    primary_raw = plan.get("CatalogHero") or plan.get("CatalogClean") or raws[0]
    cutout = make_cutout(primary_raw, sku)
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
                         "fal = catalog image set (CatalogHero/CatalogClean/"
                         "Detail/Lifestyle + FeatureCard). fal needs FAL_KEY.")
    ap.add_argument("--fal-model", choices=sorted(fal_listing.FAL_MODELS), default=fal_listing.FAL_MODEL,
                    help="fal image-edit model (default: FAL_IMAGE_MODEL env or gpt-image-2.5-sunburst-medium)")
    ap.add_argument("--no-ollama", action="store_true",
                    help="skip the Qwen3-VL analyzer; use deterministic fallback copy")
    ap.add_argument("--reanalyze", action="store_true",
                    help="re-run the analyzer even if product.json already exists")
    ap.add_argument("--format", choices=["webp", "jpg"], default="webp",
                    help="output image format (default webp)")
    ap.add_argument("--per-product", action=argparse.BooleanOptionalAction, default=True,
                    help="write images into input/<SKU>/output/ (default; the product folder is the one place). "
                         "--no-per-product writes to gallery_out/<SKU>/")
    ap.add_argument("--cache-backgrounds", action="store_true",
                    help="save generated scenes to backgrounds/ for reuse (memory sequencing)")
    ap.add_argument("--vlm-check", action="store_true",
                    help="VLM check that the lifestyle image matches the real product")
    ap.add_argument("--feature-image", action="store_true",
                    help="fal: also generate the AI FeatureProduct image (the local FeatureCard is free)")
    ap.add_argument("--dry-run", action="store_true",
                    help="fal: label photos and print each product's plan + cost; spend nothing")
    ap.add_argument("--budget", type=float,
                    help="fal: stop before any product that would take this run past $BUDGET (list price)")
    args = ap.parse_args()

    specs = load_specs()
    is_fal = args.bg_provider == "fal"
    fal_listing.FAL_MODEL = args.fal_model
    fal_listing.FEATURE_PRODUCT_ALL = args.feature_image
    provider = None if is_fal else providers.get_provider(args.bg_provider)
    print(f"Scene engine: {args.bg_provider}" + (f" ({args.fal_model})" if is_fal else ""))

    skus = [args.sku] if args.sku else pp.find_sku_folders(pp.INPUT_DIR)
    approved, planned_usd, spent_usd = load_approved(), 0.0, 0.0
    for i, sku in enumerate(skus, 1):
        print(f"[{i}/{len(skus)}] {sku}")
        try:
            if is_fal:   # fal renders the product into each scene (product-in-scene set)
                folder = os.path.join(pp.INPUT_DIR, sku)
                out_dir = (os.path.join(folder, "output") if args.per_product
                           else os.path.join(OUTPUT_ROOT, sku))
                raws = pp.raw_images_in(folder)
                cont = get_profile(sku, folder, not args.no_ollama, args.reanalyze)   # local, free
                if not args.no_ollama:   # label photos so each slot uses the right one
                    cont["photos"] = photo_tags.tag_folder(folder)
                    cont.update({k: v for k, v in analyzer.manual_overrides(os.path.join(folder, "product.json")).items()
                                 if k in ("photo_items", "photo_packaging")})
                plan = fal_listing.plan_slots(raws, cont) if raws else {}
                todo = fal_listing.slots_to_generate(plan, out_dir) if plan else []
                est = len(fal_listing.paid(todo)) * fal_listing.FAL_MODELS[args.fal_model]["usd"]
                odd = photo_tags.mixed_folder(cont.get("photo_items") or {})
                print("  plan: " + ", ".join(f"{s}<-{os.path.basename(p)}" for s, p in plan.items()))
                print(f"  new fal images: {len(fal_listing.paid(todo))} (~${est:.3f}), "
                      f"made locally: {len(todo) - len(fal_listing.paid(todo))}"
                      + (f"   ! MIXED FOLDER? {', '.join(odd)} look like a different product" if odd else ""))
                if photo_tags.name_mismatch(sku, cont.get("photo_items") or {}):
                    print("  ! photos don't match the folder name — check the folder")
                for note in (fal_listing.plan_warnings(plan, cont) if plan else []):
                    print(f"  ! {note}")
                planned_usd += est
                if args.dry_run or not todo:
                    continue
                if sku not in approved and pp.sku_of(sku) not in approved:   # approve by folder or stock code
                    print(f"  skip: not in {APPROVED_PATH} (review the --dry-run plan, then add it)")
                    continue
                if odd:   # you approved it after the dry-run showed this flag
                    print("  warning: approved despite the mixed-folder flag — generating")
                if args.budget is not None and spent_usd + est > args.budget:
                    print(f"  STOP: ${spent_usd:.2f} spent; this product (~${est:.3f}) would pass --budget ${args.budget:.2f}")
                    break
                before = fal_slots_present(out_dir)
                cost_before = fal_listing.fal_cost
                row = {"sku": pp.sku_of(sku), "folder": sku, "provider": f"fal:{args.fal_model}", "fal_images_reused": before,
                       "output_dir": out_dir}
                try:
                    fal_listing.build(sku, raws, cont, out_dir, ext=args.format)
                    row["status"] = "ok"
                except Exception as exc:
                    row.update(status="failed", error=str(exc)[:300])
                    raise
                finally:   # billed calls count even when a later step fails
                    row.update(processed_at=datetime.datetime.now().isoformat(timespec="seconds"),
                               fal_images_new=fal_slots_present(out_dir) - before,
                               est_cost_usd=f"{fal_listing.fal_cost - cost_before:.3f}")
                    record_processed(row)
                    spent_usd += fal_listing.fal_cost - cost_before
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
    if is_fal:
        print(f"\nfal: new images planned ~${planned_usd:.2f}"
              + ("" if args.dry_run else f", spent this run ~${spent_usd:.2f}") + " (list price)")
    print(f"\nDone. Galleries in '{OUTPUT_ROOT}/<SKU>/'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
