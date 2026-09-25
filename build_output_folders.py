#!/usr/bin/env python3
"""Populate a top-level output/<SKU>/ folder per active product with its curated
final image set, copied from input/<FOLDER>/output/ (the working pipeline dir).

Reuses shopify_export.curated_filenames() so the file selection (CatalogClean
first, _wm marketing copies, Hero_titled/FeatureCard, then any extras) stays
identical to what the Shopify CSV references -- this is a clean, SKU-keyed copy
of the same files for a dev handoff, independent of the working pipeline layout.

    python build_output_folders.py
"""
import csv
import os
import shutil

import shopify_export as se

OUT_ROOT = "output"


def main():
    with open("catalog_products.csv", newline="", encoding="utf-8") as f:
        products = [r for r in csv.DictReader(f) if r["sku"].strip()]

    os.makedirs(OUT_ROOT, exist_ok=True)
    missing, copied_total, built = [], 0, set()

    for prod in products:
        sku, handle = prod["sku"], prod["handle"]
        src_dir = os.path.join(se.PRODUCTS_DIR, handle.upper(), "output")
        files = se.curated_filenames(src_dir)
        if not files:
            missing.append(sku)
            continue
        dest_dir = os.path.join(OUT_ROOT, sku)
        os.makedirs(dest_dir, exist_ok=True)
        for fname in files:
            shutil.copy2(os.path.join(src_dir, fname), os.path.join(dest_dir, fname))
        # a file archived out of the working dir must leave the handoff too, or it stays in the
        # gallery (curated_filenames() appends unrecognised files); shopify_import.csv is
        # written here by split_import_csv.py
        for stale in set(os.listdir(dest_dir)) - set(files) - {"shopify_import.csv"}:
            os.remove(os.path.join(dest_dir, stale))
            print(f"  removed stale {dest_dir}/{stale}")
        built.add(sku)
        copied_total += len(files)
        print(f"[{sku}] {len(files)} image(s) -> {dest_dir}/")

    # a leftover output/<SKU>/ would mark a product "processed" for every downstream script
    for stale in sorted(set(os.listdir(OUT_ROOT)) - built):
        if os.path.isdir(os.path.join(OUT_ROOT, stale)):
            shutil.rmtree(os.path.join(OUT_ROOT, stale))
            print(f"removed stale {OUT_ROOT}/{stale}/")

    print(f"\n{len(products)} products, {copied_total} files copied, "
          f"{len(missing)} with no images: {missing}")


if __name__ == "__main__":
    main()
