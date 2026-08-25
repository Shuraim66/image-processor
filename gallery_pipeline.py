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
    python gallery_pipeline.py --no-ollama          # deterministic copy, no model
"""

import argparse
import json
import multiprocessing
import os
import sys
import time
import traceback

from PIL import Image

import process_products as pp
import make_hero as mh
import gallery
import analyzer
import palette
import providers
import scenes
import quality

OUTPUT_ROOT = "gallery_out"
CUTOUT_DIR = "gallery_out/_cutouts"
SPECS_PATH = "specs.json"
MANIFEST_PATH = "gallery_out/_manifest.json"

# A worker holding a rembg session peaks around this much. Measured with
# bria-rmbg; a lighter REMBG_MODEL needs far less. It is the binding constraint
# on --jobs: four workers want ~13 GB, which is why parallel rendering runs
# SLOWER than serial on an 18 GB machine once it starts swapping.
WORKER_PEAK_GB = 3.5


def load_specs():
    with open(SPECS_PATH, encoding="utf-8") as f:
        return json.load(f)


def specs_for(specs, sku):
    return {**specs.get("_default", {}), **specs.get(sku, {})}


def get_profile(sku, folder, use_ollama, reanalyze, allow_fallback=False):
    """Load input/<SKU>/product.json, or generate it via the analyzer.

    Returns the content dict the templates consume (a superset of the fields
    they read). product.json is the single source of truth for copy.
    """
    path = os.path.join(folder, "product.json")
    if os.path.exists(path) and not reanalyze:
        profile = analyzer.ProductProfile.model_validate_json(
            open(path, encoding="utf-8").read())
    else:
        profile = analyzer.analyze_folder(folder, use_ollama=use_ollama,
                                          allow_fallback=allow_fallback)
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
                  per_product=False, cache_bg=False, vlm=False,
                  allow_fallback=False):
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
    cont = get_profile(sku, folder, use_ollama, reanalyze, allow_fallback)
    # Colour the whole set from the product itself, so a pink scooter and a
    # green plant dome stop shipping in the same corporate blue and red. A theme
    # pinned in product.json wins.
    cont["theme"] = palette.as_theme(cont.get("theme")) or palette.extract_theme(cutout)
    # Category drives both the scene plate and the display typeface.
    cont["category"] = scenes.category_for(cont)
    sp = specs_for(specs, sku)
    made = []

    def op(name):
        return os.path.join(out_dir, f"{name}.{ext}")

    # 01 — pure white main (no watermark; marketplace-safe), matched to gallery size.
    # Built from the cached cutout: process_image() would re-run rembg on a photo
    # we have already segmented, doubling the slowest step in the pipeline.
    p = op("01_main")
    (pp.standardize(Image.open(cutout).convert("RGBA")).convert("RGB")
       .resize((mh.SIZE, mh.SIZE), Image.LANCZOS)
       .save(p, quality=92)); made.append(p)

    # 02 — branded hero (procedural bg)
    made.append(mh.render_hero(cutout, cont, op("02_hero")))

    # 03/04 — lifestyle scenes (pluggable provider), real product composited on top
    prompts = cont.get("scene_prompts", []) + ["bright playroom", "sunny living room"]
    for slot, variant, prompt in [("03_lifestyle_a", "A", prompts[0]),
                                  ("04_lifestyle_b", "B", prompts[1])]:
        scene = provider.scene(sku, cutout, primary_raw, variant, prompt,
                               cont["category"])
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
        "category": cont.get("category"),
    }, op("06_size")))

    # 07 — detail close-up
    made.append(gallery.render_detail(primary_raw, tuple(sp["detail_crop"]),
                sp.get("detail_label", "CLOSER LOOK"), cont, op("07_detail")))

    # quality report (deterministic checks + optional VLM semantic check)
    report = quality.check_gallery(sku, out_dir, cutout_path=cutout,
                                   copy_source=cont.get("source", ""),
                                   copy_flags=cont.get("review_flags", []))
    if vlm:   # step 6: does the lifestyle image faithfully show the real product?
        v = quality.vlm_check(primary_raw, op("03_lifestyle_a"))
        report["vlm_check"] = v
        if v["status"] == "review":
            report["status"] = "review"
    with open(os.path.join(out_dir, "quality-report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"  -> quality: {report['status']}")
    return made, report


def load_manifest():
    """Per-SKU record of what has been built, for --resume."""
    if not os.path.exists(MANIFEST_PATH):
        return {}
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as fh:
            return json.load(fh).get("skus", {})
    except (json.JSONDecodeError, OSError):
        print(f"  ! {MANIFEST_PATH} unreadable — starting a fresh manifest",
              file=sys.stderr)
        return {}


def save_manifest(skus):
    """Write via a temp file so an interrupt cannot leave a truncated manifest."""
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    tmp = MANIFEST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "skus": skus},
                  fh, indent=2)
    os.replace(tmp, MANIFEST_PATH)


_WORKER = {}


def total_ram_gb():
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except (ValueError, OSError, AttributeError):
        return 0.0


def safe_jobs(requested):
    """Clamp --jobs to what memory allows, and say so.

    onnxruntime already saturates every core inside one process, so extra
    workers buy throughput only while they all fit in RAM. Past that the machine
    swaps and the whole batch gets slower, not faster.
    """
    ram = total_ram_gb()
    if not ram:
        return requested
    budget = max(1, int((ram * 0.6) // WORKER_PEAK_GB))
    if requested > budget:
        print(f"  ! --jobs {requested} needs ~{requested * WORKER_PEAK_GB:.0f} GB; "
              f"this machine has {ram:.0f} GB. Using {budget} to stay out of swap "
              f"(a lighter REMBG_MODEL raises this).", file=sys.stderr)
        return budget
    return requested


def _init_worker(provider_name, specs, opts, threads):
    """Each process builds its own provider and rembg session once."""
    # Pin thread counts before the ONNX session is created, or N workers each
    # spawn one thread per core and fight each other for the same cores.
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[var] = str(threads)
    _WORKER["provider"] = providers.get_provider(provider_name)
    _WORKER["specs"] = specs
    _WORKER["opts"] = opts


def _build_one(sku):
    try:
        made, report = build_for_sku(sku, _WORKER["specs"], _WORKER["provider"],
                                     **_WORKER["opts"])
        return {"sku": sku, "status": "ok", "images": len(made),
                "quality": report["status"], "flags": report.get("copy_flags", []),
                "finished": time.strftime("%Y-%m-%dT%H:%M:%S")}
    except Exception as exc:  # keep the batch alive; the manifest records why
        traceback.print_exc()
        return {"sku": sku, "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "finished": time.strftime("%Y-%m-%dT%H:%M:%S")}


def main():
    ap = argparse.ArgumentParser(description="Generate the 7-image listing gallery per product.")
    ap.add_argument("--sku", help="only this SKU (default: all under input/)")
    ap.add_argument("--bg-provider", choices=["procedural", "folder", "drawthings"],
                    default="folder",
                    help="background engine for slots 3-4 (default folder: "
                         "reads category plates from backgrounds/)")
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
    ap.add_argument("--allow-fallback", action="store_true",
                    help="use placeholder copy when analysis fails instead of skipping the SKU")
    ap.add_argument("--jobs", type=int, default=1, metavar="N",
                    help="render N products in parallel. Rendering is CPU-bound and "
                         "scales well; analysis is not, so every SKU must already "
                         "have a product.json when N > 1")
    ap.add_argument("--resume", action="store_true",
                    help="skip SKUs the manifest already records as built")
    args = ap.parse_args()

    specs = load_specs()
    skus = [args.sku] if args.sku else pp.find_sku_folders(pp.INPUT_DIR)

    manifest = load_manifest()
    if args.resume:
        before = len(skus)
        skus = [s for s in skus if manifest.get(s, {}).get("status") != "ok"]
        print(f"Resuming: {before - len(skus)} already built, {len(skus)} to go")
    if not skus:
        print("Nothing to do.")
        return 0

    opts = dict(use_ollama=not args.no_ollama, reanalyze=args.reanalyze,
                ext=args.format, per_product=args.per_product,
                cache_bg=args.cache_backgrounds, vlm=args.vlm_check,
                allow_fallback=args.allow_fallback)

    jobs = safe_jobs(max(1, args.jobs))
    threads = max(1, (os.cpu_count() or 4) // jobs)
    if jobs > 1:
        # Workers must not queue up on one Ollama instance, so analysis has to
        # be done already. Say which SKUs are missing rather than failing later.
        missing = [s for s in skus
                   if not os.path.exists(os.path.join(pp.INPUT_DIR, s, "product.json"))]
        if missing or args.reanalyze:
            print(f"--jobs {jobs} needs every SKU analyzed first "
                  f"({len(missing)} missing). Run:\n"
                  f"    python analyzer.py --all\n"
                  f"then re-run with --jobs.", file=sys.stderr)
            return 1

    print(f"Background provider: {args.bg_provider} | {len(skus)} SKU(s) | "
          f"jobs={jobs} ({threads} thread(s) each)")
    started = time.time()
    done = 0

    if jobs == 1:
        _init_worker(args.bg_provider, specs, opts, os.cpu_count() or 4)
        results = (_build_one(s) for s in skus)
    else:
        pool = multiprocessing.Pool(jobs, initializer=_init_worker,
                                    initargs=(args.bg_provider, specs, opts, threads))
        results = pool.imap_unordered(_build_one, skus)

    ok = failed = 0
    try:
        for result in results:
            done += 1
            manifest[result["sku"]] = result
            save_manifest(manifest)          # after every SKU, so a kill is cheap
            if result["status"] == "ok":
                ok += 1
                note = f" ({result['quality']})" if result["quality"] != "pass" else ""
                print(f"[{done}/{len(skus)}] {result['sku']}: {result['images']} images{note}")
            else:
                failed += 1
                print(f"[{done}/{len(skus)}] {result['sku']}: FAILED — {result['error']}",
                      file=sys.stderr)
    except KeyboardInterrupt:
        print("\nInterrupted — manifest saved; re-run with --resume.", file=sys.stderr)
        return 130
    finally:
        if jobs > 1:
            pool.terminate()
            pool.join()

    elapsed = time.time() - started
    per = elapsed / max(1, done)
    print(f"\n{ok} built, {failed} failed in {elapsed / 60:.1f} min "
          f"({per:.0f}s/SKU). Manifest: {MANIFEST_PATH}")
    review = [s for s, r in manifest.items() if r.get("quality") == "review"]
    if review:
        print(f"Needs review: {', '.join(sorted(review))}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
