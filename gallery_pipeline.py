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

    python gallery_pipeline.py                       # all SKUs, procedural
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
import specs as specs_mod
import quality
import slots

# input/ holds only the raw photos you supply. Everything generated — images,
# product.json, cutout cache, manifest — lives under OUTPUT_ROOT, so the input
# tree stays exactly as you left it and the output tree is safe to delete.
OUTPUT_ROOT = "output"
SPECS_PATH = "specs.json"


def out_root(root=None):
    return root or OUTPUT_ROOT


def sku_dir(sku, root=None):
    return os.path.join(out_root(root), sku)


def cutout_dir(root=None):
    return os.path.join(out_root(root), "_cutouts")


def manifest_path(root=None):
    return os.path.join(out_root(root), "_manifest.json")

# A worker holding a rembg session peaks around this much — measured at 5.9-7.0 GB
# with birefnet-general-lite on 3120x4160 photos. The old 3.5 figure was optimistic
# and is why parallel rendering ran SLOWER than serial: two workers already exceed
# an 18 GB machine once the OS takes its share. Most of the peak is the full-res
# RGBA image, not the weights, so the full birefnet-general costs no more here.
WORKER_PEAK_GB = 7.0


def load_specs():
    return specs_mod.load(SPECS_PATH)


def specs_for(specs, sku):
    return specs_mod.for_sku(specs, sku)


def get_profile(sku, folder, out_dir, use_ollama, reanalyze, allow_fallback=False):
    """Load <out_dir>/product.json, or generate it via the analyzer.

    product.json is generated, so it belongs with the other output. Older runs
    wrote it next to the photos; that location is still read as a fallback so an
    existing catalog does not have to be re-analyzed.
    """
    path = analyzer.profile_path(folder, out_dir)
    legacy = os.path.join(folder, "product.json")
    if not reanalyze:
        for candidate in (path, legacy):
            if os.path.exists(candidate):
                return analyzer.ProductProfile.model_validate_json(
                    open(candidate, encoding="utf-8").read()).model_dump()
    return analyzer.analyze_folder(folder, out_dir=out_dir, use_ollama=use_ollama,
                                   allow_fallback=allow_fallback).model_dump()


# Extra angles each cost a rembg pass, which is the slowest step, so this caps
# what a very thorough shoot will spend.
MAX_ANGLES = int(os.environ.get("MAX_ANGLES", "4"))

# The slot vocabulary and listing order live in slots.py so the exporter and the
# quality checks can read them without importing this module.
SLOT_ORDER = slots.SLOT_ORDER
slot_sort_key = slots.slot_sort_key


def make_cutout(raw_path, sku, root=None, suffix=""):
    """Transparent, trimmed cutout via the full rembg model (cached across SKUs)."""
    os.makedirs(cutout_dir(root), exist_ok=True)
    out = os.path.join(cutout_dir(root), f"{sku}{suffix}.png")
    src = Image.open(raw_path).convert("RGBA")
    cut, box = pp.trim_to_content(pp.remove_background(src), return_box=True)
    cut.save(out)
    with open(out + ".box.json", "w", encoding="utf-8") as fh:
        json.dump({"box": box, "size": src.size}, fh)      # for auto_detail_crop
    return out


def build_for_sku(sku, specs, provider, use_ollama, reanalyze, ext="webp",
                  root=None, cache_bg=False, vlm=False, allow_fallback=False):
    folder = os.path.join(pp.INPUT_DIR, sku)
    raws = pp.raw_images_in(folder)
    if not raws:
        print(f"  ! no images for {sku}", file=sys.stderr)
        return []
    out_dir = sku_dir(sku, root)
    os.makedirs(out_dir, exist_ok=True)

    primary_raw = raws[0]
    cutout = make_cutout(primary_raw, sku, root)
    # Every other angle you shot, cut out too — otherwise the whole gallery is
    # one photograph seen seven times.
    angle_cuts = [cutout] + [
        make_cutout(p, sku, root, suffix=f"_a{i}")
        for i, p in enumerate(raws[1:MAX_ANGLES], start=2)
    ]
    cont = get_profile(sku, folder, out_dir, use_ollama, reanalyze, allow_fallback)
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

    # A rename leaves the previous run's images behind and the exporter picks them
    # up as extra gallery slots. SLOT_ORDER is the allow-list rather than a list of
    # retired names: a deny-list has to be updated by hand at every rename, which
    # is how "01_main" survived one. Only images are touched, so product.json and
    # quality-report.json are safe.
    for stale in os.listdir(out_dir):
        stem, dot_ext = os.path.splitext(stale)
        if dot_ext == f".{ext}" and stem not in SLOT_ORDER:
            os.remove(os.path.join(out_dir, stale))

    prompts = cont.get("scene_prompts", []) + ["bright playroom", "sunny living room"]
    plate_a = provider.scene(sku, cutout, primary_raw, "A", prompts[0], cont["category"])

    # catalog hero — the product on a scene with NOTHING written on it. Copy
    # belongs on the feature card; on every image it made the set look stamped.
    made.append(mh.render_hero(cutout, cont, op("catalog-hero"),
                               background=plate_a, layout="clean"))

    # white background — the marketplace-safe main image, no watermark
    p = op("white-background")
    (pp.standardize(Image.open(cutout).convert("RGBA")).convert("RGB")
       .resize((mh.SIZE, mh.SIZE), Image.LANCZOS)
       .save(p, quality=92)); made.append(p)

    # with packaging — the clearest box shot, but never the primary photo: on a
    # single-photo product the detector points at the main image, and a packshot
    # identical to the white-background slot is just a duplicate.
    primary_name = os.path.basename(primary_raw)
    packaging = [os.path.join(folder, n) for n in cont.get("packaging_photos", [])
                 if n != primary_name and os.path.exists(os.path.join(folder, n))]
    if packaging:
        pack_cut = make_cutout(packaging[0], sku, root, suffix="_pack")
        p = op("with-packaging")
        (pp.standardize(Image.open(pack_cut).convert("RGBA")).convert("RGB")
           .resize((mh.SIZE, mh.SIZE), Image.LANCZOS)
           .save(p, quality=92)); made.append(p)

    # every angle — the other shots you took, on cards
    if len(angle_cuts) > 1:
        made.append(gallery.render_angles(angle_cuts, cont, op("every-angle")))

    # lifestyle — a scene, from a different angle than the hero
    plate_b = provider.scene(sku, cutout, primary_raw, "B", prompts[1], cont["category"])
    if cache_bg:
        os.makedirs("backgrounds", exist_ok=True)
        plate_b.convert("RGB").save(os.path.join("backgrounds", f"{sku}_b.{ext}"))
    lifestyle_cut = angle_cuts[1] if len(angle_cuts) > 1 else cutout
    made.append(mh.render_hero(lifestyle_cut, cont, op("lifestyle-scene"),
                               background=plate_b))

    # features & benefits
    made.append(gallery.render_infographic(cutout, cont, op("features-and-benefits")))

    # size & specs, skipped without real measurements
    skipped = []
    if specs_mod.has_dimensions(sp):
        made.append(gallery.render_size_card(cutout, {
            "title": sp.get("title", "SIZE & SPECS"),
            "height": sp["height"], "length": sp["length"], "badges": sp["badges"],
            "theme": cont.get("theme", {}),
            "category": cont.get("category"),
        }, op("size-and-specs")))
    else:
        skipped.append("size-and-specs (no dimensions in specs.json/specs.csv)")

    # close-up, aimed at the product rather than a fixed rectangle
    crop = tuple(sp["detail_crop"]) if sp.get("detail_crop_manual") else None
    if crop is None:
        side_path = cutout + ".box.json"
        box = None
        if os.path.exists(side_path):
            with open(side_path, encoding="utf-8") as fh:
                box = json.load(fh).get("box")
        crop = gallery.auto_detail_crop(primary_raw, box)
    made.append(gallery.render_detail(primary_raw, crop,
                sp.get("detail_label", "CLOSER LOOK"), cont, op("close-up-detail")))

    # quality report (deterministic checks + optional VLM semantic check)
    report = quality.check_gallery(sku, out_dir, cutout_path=cutout,
                                   copy_source=cont.get("source", ""),
                                   copy_flags=cont.get("review_flags", []),
                                   render_size=mh.SIZE,
                                   order_key=slot_sort_key)
    if skipped:
        report["skipped_slots"] = skipped
    if vlm:   # step 6: does the lifestyle image faithfully show the real product?
        v = quality.vlm_check(primary_raw, op("lifestyle-scene"))
        report["vlm_check"] = v
        # 'fail' means the check itself could not run. Asked for and not answered
        # is not a pass, so it holds the product back just as a mismatch does.
        if v["status"] in ("review", "fail"):
            report["status"] = "review"
    with open(os.path.join(out_dir, "quality-report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"  -> quality: {report['status']}")
    return made, report


def load_manifest(root=None):
    """Per-SKU record of what has been built, for --resume."""
    path = manifest_path(root)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("skus", {})
    except (json.JSONDecodeError, OSError):
        print(f"  ! {path} unreadable — starting a fresh manifest", file=sys.stderr)
        return {}


def save_manifest(skus, root=None):
    """Write via a temp file so an interrupt cannot leave a truncated manifest."""
    path = manifest_path(root)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "skus": skus},
                  fh, indent=2)
    os.replace(tmp, path)


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
              f"(most of a worker's peak is the full-res photo, not the model, "
              f"so a lighter REMBG_MODEL barely moves this).", file=sys.stderr)
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
    ap.add_argument("--bg-provider", choices=["procedural", "folder"],
                    default="folder",
                    help="background engine for slots 3-4 (default folder: "
                         "reads category plates from backgrounds/)")
    ap.add_argument("--no-ollama", action="store_true",
                    help="skip the Qwen3-VL analyzer; use deterministic fallback copy")
    ap.add_argument("--reanalyze", action="store_true",
                    help="re-run the analyzer even if product.json already exists")
    ap.add_argument("--format", choices=["webp", "jpg"], default="webp",
                    help="output image format (default webp)")
    ap.add_argument("--out-dir", default=OUTPUT_ROOT, metavar="DIR",
                    help=f"where generated images, product.json, cutouts and the "
                         f"manifest are written (default {OUTPUT_ROOT}/). "
                         f"input/ is never written to")
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

    manifest = load_manifest(args.out_dir)
    if args.resume:
        before = len(skus)
        skus = [s for s in skus if manifest.get(s, {}).get("status") != "ok"]
        print(f"Resuming: {before - len(skus)} already built, {len(skus)} to go")
    if not skus:
        print("Nothing to do.")
        return 0

    opts = dict(use_ollama=not args.no_ollama, reanalyze=args.reanalyze,
                ext=args.format, root=args.out_dir,
                cache_bg=args.cache_backgrounds, vlm=args.vlm_check,
                allow_fallback=args.allow_fallback)

    jobs = safe_jobs(max(1, args.jobs))
    threads = max(1, (os.cpu_count() or 4) // jobs)
    if jobs > 1:
        # Workers must not queue up on one Ollama instance, so analysis has to
        # be done already. Say which SKUs are missing rather than failing later.
        missing = [s for s in skus
                   if not os.path.exists(analyzer.profile_path(
                       os.path.join(pp.INPUT_DIR, s), sku_dir(s, args.out_dir)))]
        if missing or args.reanalyze:
            print(f"--jobs {jobs} needs every SKU analyzed first "
                  f"({len(missing)} missing). Run:\n"
                  f"    python analyzer.py --all\n"
                  f"then re-run with --jobs.", file=sys.stderr)
            return 1

    print(f"Background provider: {args.bg_provider} | {len(skus)} SKU(s) | "
          f"jobs={jobs} ({threads} thread(s) each) | out: {args.out_dir}/")
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
            save_manifest(manifest, args.out_dir)   # after every SKU: a kill is cheap
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
          f"({per:.0f}s/SKU). Output: {args.out_dir}/")
    review = [s for s, r in manifest.items() if r.get("quality") == "review"]
    if review:
        print(f"Needs review: {', '.join(sorted(review))}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
