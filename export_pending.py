#!/usr/bin/env python3
"""
Build the "unprocessed" dev-handoff bundle: every product without a generated image
set, grouped by why (the Row Type column):

  active_unimaged     -- in catalog_products.csv (priced, stocked, DRAFT), waiting on
                          a generated CatalogHero/Lifestyle image
  content_policy      -- backlog-products-image-failed/: priced/stocked, but fal/OpenAI
                          refuses the image (licensed characters)
  backlog_low_stock   -- backlog-products/: below the stock threshold, not a listing yet

Real products (the first two groups) are built with shopify_export.rows_for() -- the
same function as the processed bundle -- so their handle, variants, tags and body are
identical to what the processed CSV will say once they get images: the later import
updates the draft instead of creating a duplicate. Only the images (downscaled raw
shoot photos from output_pending/<SKU>/) and the draft status differ.

Writes, in one run:
  shopify_import_draft.csv            real products only, standard Shopify columns
  output_pending/<SKU>/shopify_import.csv   the same rows, one file per product
  shopify_import_pending.csv          tracking sheet: everything, plus Row Type /
                                      Units On Hand / Notes (not for import)

    python export_pending.py
"""
import argparse
import csv
import json
import os
import shutil
import sys

from PIL import Image

import catalog_csv as cc
import shopify_export as se
import store_taxonomy as st

PENDING_DIR = "output_pending"
BACKLOG_DIR = "backlog-products"
FAILED_DIR = "backlog-products-image-failed"
DRAFT_CSV = "shopify_import_draft.csv"
TRACKING_CSV = "shopify_import_pending.csv"
MAX_DIM = 1280  # raw camera photos are several MB each -- downscaled for a reference bundle
EXTRA_COLUMNS = ["Row Type", "Units On Hand", "Notes"]
NOTES = {
    "active_unimaged": "Priced & stocked; waiting on a generated CatalogHero/Lifestyle image.",
    "content_policy": "Priced & stocked; fal/OpenAI content-policy block (licensed character) "
                      "-- needs a manual image.",
    "backlog_low_stock": "Below the stock-listing threshold -- not a listing yet.",
}


def raw_photos(folder, limit):
    if not os.path.isdir(folder):
        return []
    files = [f for f in os.listdir(folder)
             if f.lower().endswith(se.IMG_EXTS) and os.path.isfile(os.path.join(folder, f))]
    # front shot first: it becomes the draft listing's main image
    return sorted(files, key=lambda f: (not f.lower().startswith("front"), f))[:limit]


def copy_images(sku, src_dir, limit):
    dest = os.path.join(PENDING_DIR, sku)
    os.makedirs(dest, exist_ok=True)
    for fn in raw_photos(src_dir, limit):
        try:
            im = Image.open(os.path.join(src_dir, fn)).convert("RGB")
            im.thumbnail((MAX_DIM, MAX_DIM), Image.LANCZOS)
            im.save(os.path.join(dest, os.path.splitext(fn)[0] + ".jpg"), "JPEG", quality=82, optimize=True)
        except Exception as e:
            print(f"  ! {sku}/{fn}: {e}", file=sys.stderr)


def product_folders(root):
    """(folder path, product.json) for every product folder under root."""
    if not os.path.isdir(root):
        return []
    out = []
    for folder in sorted(os.listdir(root)):
        pj_path = os.path.join(root, folder, "product.json")
        if os.path.isfile(pj_path):
            out.append((os.path.join(root, folder), json.load(open(pj_path, encoding="utf-8"))))
    return out


def with_tracking(rows, row_type, units):
    for r in rows:
        r.update({c: "" for c in EXTRA_COLUMNS})
        r["Row Type"] = row_type
    rows[0].update({"Units On Hand": units, "Notes": NOTES[row_type]})
    return rows


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-photos", type=int, default=3,
                     help="raw shoot photos to copy per product (default 3, keeps the zip small)")
    ap.add_argument("--image-base-url", default="",
                     help="public URL prefix for output_pending/ images (same as shopify_export.py)")
    args = ap.parse_args()
    if args.image_base_url and not args.image_base_url.endswith("/"):
        args.image_base_url += "/"
    os.makedirs(PENDING_DIR, exist_ok=True)

    with open(se.CATALOG_PRODUCTS, encoding="utf-8", newline="") as f:
        catalog = [p for p in csv.DictReader(f) if p["price"].strip() and p["stock"].strip()]
    variants_by_handle = se.load_variants_by_handle()
    input_dirs = {pj.get("sku"): (d, pj) for d, pj in product_folders(se.PRODUCTS_DIR)}
    collections = st.load_collections()

    # (sku, row_type, prod, variants, product_dir, product.json) for every real product
    real = []
    for p in catalog:
        if se.curated_filenames(os.path.join(se.OUTPUT_DIR, p["sku"])):
            continue  # already processed
        d, pj = input_dirs[p["sku"]]
        real.append((p["sku"], "active_unimaged", p, variants_by_handle.get(p["handle"], []), d, pj))
    for d, pj in product_folders(FAILED_DIR):
        row, _, _ = cc.row_for(os.path.basename(d), pj, collections)
        real.append((row["sku"], "content_policy", row, cc.variant_rows(row, pj), d, pj))

    draft_rows, tracking_rows, counts = [], [], {}
    for sku, row_type, prod, variants, d, pj in real:
        copy_images(sku, d, args.max_photos)
        rows = se.rows_for(prod, variants, args, image_dir=PENDING_DIR, product_dir=d)
        write_csv(os.path.join(PENDING_DIR, sku, "shopify_import.csv"), se.COLUMNS, rows)
        draft_rows += rows
        tracking_rows += with_tracking([dict(r) for r in rows], row_type, str(pj.get("units_last_seen") or ""))
        counts[row_type] = counts.get(row_type, 0) + 1

    # backlog items aren't listings (many unpriced): tracking sheet only, minimal rows
    for d, pj in product_folders(BACKLOG_DIR):
        sku = pj.get("sku") or os.path.basename(d)
        copy_images(sku, d, args.max_photos)
        r = se.row_template()
        price = pj.get("price_pkr")
        r.update({"Handle": pj.get("handle") or os.path.basename(d).lower(),
                  "Title": pj.get("title") or pj.get("product_name") or sku,
                  "Variant SKU": sku, "Variant Price": f"{float(price):.2f}" if price else "",
                  "Variant Inventory Qty": "0", "Status": "draft", "Published": "FALSE"})
        tracking_rows += with_tracking([r], "backlog_low_stock", str(pj.get("units_last_seen") or ""))
        counts["backlog_low_stock"] = counts.get("backlog_low_stock", 0) + 1

    write_csv(DRAFT_CSV, se.COLUMNS, draft_rows)
    write_csv(TRACKING_CSV, se.COLUMNS + EXTRA_COLUMNS, tracking_rows)

    # products that got processed, were discontinued or were removed leave a folder behind
    current = {sku for sku, *_ in real} | {r["Variant SKU"] for r in tracking_rows
                                              if r["Row Type"] == "backlog_low_stock"}
    for stale in sorted(set(os.listdir(PENDING_DIR)) - current):
        if os.path.isdir(os.path.join(PENDING_DIR, stale)):
            shutil.rmtree(os.path.join(PENDING_DIR, stale))
            print(f"removed stale {PENDING_DIR}/{stale}/")

    for k in NOTES:
        print(f"{k:18s} {counts.get(k, 0)} products")
    print(f"\n{DRAFT_CSV}: {len(draft_rows)} rows for {len(real)} real products (standard Shopify columns, draft)")
    print(f"{PENDING_DIR}/<SKU>/shopify_import.csv: {len(real)} per-product files")
    print(f"{TRACKING_CSV}: {len(tracking_rows)} rows (tracking only, not for import)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
