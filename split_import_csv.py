#!/usr/bin/env python3
"""Write a per-product Shopify-import CSV into each output/<SKU>/ folder, alongside
its images, so a single product's folder is self-contained (devs can hand off or
review one SKU at a time without cross-referencing the combined shopify_import.csv).

Reuses shopify_export.rows_for() so every row matches the combined CSV exactly --
this is a split of the same data, not a separate source of truth.

    python split_import_csv.py
    python build_output_folders.py && python split_import_csv.py && python shopify_export.py
"""
import argparse
import csv
import sys

import shopify_export as se

OUT_ROOT = "output"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image-base-url", default="",
                     help="same as shopify_export.py -- pass the same value you use there")
    args = ap.parse_args()
    if args.image_base_url and not args.image_base_url.endswith("/"):
        args.image_base_url += "/"

    with open(se.CATALOG_PRODUCTS, encoding="utf-8", newline="") as f:
        products = list(csv.DictReader(f))
    incomplete = [p["sku"] for p in products if not p["price"].strip() or not p["stock"].strip()]
    products = [p for p in products if p["price"].strip() and p["stock"].strip()]
    variants_by_handle = se.load_variants_by_handle()

    written, missing = 0, []
    for prod in products:
        rows = se.rows_for(prod, variants_by_handle.get(prod["handle"], []), args)
        dest_dir = f"{OUT_ROOT}/{prod['sku']}"
        try:
            with open(f"{dest_dir}/shopify_import.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=se.COLUMNS)
                w.writeheader()
                w.writerows(rows)
            written += 1
        except FileNotFoundError:
            missing.append(prod["sku"])  # output/<SKU>/ doesn't exist -- run build_output_folders.py first

    print(f"Wrote a per-product CSV into {written} output/<SKU>/ folders.")
    if incomplete:
        print(f"Skipped {len(incomplete)} incomplete catalog row(s): {incomplete}", file=sys.stderr)
    if missing:
        print(f"Missing output/<SKU>/ dir for {len(missing)} product(s) -- run "
              f"build_output_folders.py first: {missing}", file=sys.stderr)


if __name__ == "__main__":
    main()
