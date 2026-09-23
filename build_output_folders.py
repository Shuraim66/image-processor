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
    missing, copied_total = [], 0

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
        copied_total += len(files)
        print(f"[{sku}] {len(files)} image(s) -> {dest_dir}/")

    print(f"\n{len(products)} products, {copied_total} files copied, "
          f"{len(missing)} with no images: {missing}")


if __name__ == "__main__":
    main()
