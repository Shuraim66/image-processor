#!/usr/bin/env python3
"""
Shopify product CSV exporter.

Reads the verified catalog (`catalog_products.csv` + `catalog_variants.csv` --
box-checked, priced and stocked) and each product's final curated image set
(`output/<SKU>/*.png`, built by build_output_folders.py from the working
`input/<FOLDER>/output/` pipeline dirs), and writes a Shopify-import CSV: one
row per product (or per variant, for multi-variant products), then one extra
row per additional image.

    python shopify_export.py
    python shopify_export.py --status active \
        --image-base-url https://cdn.example.com/toys/

Note: Shopify's importer fetches Image Src over HTTP, so it needs PUBLIC URLs.
Pass --image-base-url to prefix your hosted image location; without it the CSV
lists local paths (fine for review / for devs to swap in a real host, not for
importing to Shopify directly).
"""

import argparse
import csv
import html
import json
import os
import sys
from collections import defaultdict

PRODUCTS_DIR = "input"
OUTPUT_DIR = "output"      # final per-SKU image folders (output/<SKU>/), built by build_output_folders.py
CATALOG_PRODUCTS = "catalog_products.csv"
CATALOG_VARIANTS = "catalog_variants.csv"
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")

COLUMNS = [
    "Handle", "Title", "Body (HTML)", "Vendor", "Product Category", "Type",
    "Tags", "Published", "Option1 Name", "Option1 Value", "Variant SKU",
    "Variant Barcode", "Variant Inventory Tracker", "Variant Inventory Qty",
    "Variant Inventory Policy", "Variant Fulfillment Service", "Variant Price",
    "Variant Compare At Price", "Variant Requires Shipping", "Variant Taxable",
    "Image Src", "Image Position", "Image Alt Text", "Gift Card",
    "SEO Title", "SEO Description", "Status",
]

# Gallery order for a per-product output/ folder: the plain CatalogClean main image first
# (the one Shopify/Google Shopping feeds need unwatermarked), then the branded "_wm" copy of
# each marketing slot -- falling back to the plain copy only if that slot was never branded --
# then the two locally-rendered extras. Anything else in the folder (a hand-added variant
# photo, a future slot) is appended afterwards, alphabetically, so nothing gets silently lost.
GALLERY_SLOTS = ["CatalogHero", "Angle", "Open", "Box", "Detail", "FeatureProduct", "Lifestyle"]
GALLERY_EXTRAS = ["Hero_titled", "FeatureCard"]


def curated_filenames(d):
    """The gallery order for one product's image dir: plain CatalogClean main image
    first (Shopify/Google Shopping feeds need it unwatermarked), then the branded
    "_wm" copy of each marketing slot -- falling back to the plain copy only if that
    slot was never branded -- then the two locally-rendered extras. Anything else in
    the folder is appended afterwards, alphabetically, so nothing gets silently lost.
    Used both to build output/<SKU>/ from a pipeline dir and to list it back out."""
    if not os.path.isdir(d):
        return []
    existing = set(os.listdir(d))

    def pick(name):
        return next((name + ext for ext in IMG_EXTS if name + ext in existing), None)

    files, handled = [], set()
    main = pick("CatalogClean")
    if main:
        files.append(main)
    handled.add("CatalogClean")
    for slot in GALLERY_SLOTS:
        f = pick(slot + "_wm") or pick(slot)
        if f:
            files.append(f)
        handled.add(slot)          # decided either way -- the plain copy never falls through too
    for extra in GALLERY_EXTRAS:
        f = pick(extra)
        if f:
            files.append(f)
        handled.add(extra)

    def base_name(fname):
        stem = os.path.splitext(fname)[0]
        return stem[:-3] if stem.endswith("_wm") else stem

    files += sorted(f for f in os.listdir(d)
                     if f.lower().endswith(IMG_EXTS) and base_name(f) not in handled)
    return files


def images_for(sku, base_url, image_dir=OUTPUT_DIR):
    d = os.path.join(image_dir, sku)
    files = curated_filenames(d)
    return [f"{base_url}{sku}/{f}" if base_url else os.path.join(d, f) for f in files]


def body_html(description, bullet_points, whats_included):
    parts = [f"<p>{html.escape(description)}</p>"]
    if bullet_points:
        parts.append("<ul>" + "".join(
            f"<li>{html.escape(b)}</li>" for b in bullet_points) + "</ul>")
    if whats_included:
        parts.append("<p><strong>What's included:</strong></p><ul>" + "".join(
            f"<li>{html.escape(w)}</li>" for w in whats_included) + "</ul>")
    return "".join(parts)


def row_template():
    return {c: "" for c in COLUMNS}


def load_variants_by_handle():
    by_handle = defaultdict(list)
    with open(CATALOG_VARIANTS, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            by_handle[r["product_handle"]].append(r)
    return by_handle


def rows_for(prod, variants, args, image_dir=OUTPUT_DIR, product_dir=None):
    handle = prod["handle"]
    product_dir = product_dir or os.path.join(PRODUCTS_DIR, handle.upper())
    pj_path = os.path.join(product_dir, "product.json")
    alt_text, bullets, included = "", [], []
    if os.path.exists(pj_path):
        pj = json.load(open(pj_path, encoding="utf-8"))
        alt_text = pj.get("alt_text") or ""
        bullets = pj.get("bullet_points") or []
        included = pj.get("whats_included") or []
    alt_text = alt_text or prod["title"]

    imgs = images_for(prod["sku"], args.image_base_url, image_dir)
    if not imgs:
        print(f"  ! {prod['sku']}: no images in {image_dir}/{prod['sku']}/", file=sys.stderr)

    status = (prod["status"] or "draft").lower()
    base = row_template()
    base.update({
        "Handle": handle,
        "Title": prod["title"],
        "Body (HTML)": body_html(prod["description"], bullets, included),
        "Vendor": prod["vendor"],
        "Type": prod["product_type"],
        "Tags": prod["all_tags"],
        "Published": "TRUE" if status == "active" else "FALSE",
        "Variant Inventory Tracker": "shopify",
        "Variant Inventory Policy": "deny",
        "Variant Fulfillment Service": "manual",
        "Variant Requires Shipping": "TRUE",
        "Variant Taxable": "TRUE",
        "Gift Card": "FALSE",
        "SEO Title": prod["seo_title"],
        "SEO Description": prod["seo_description"],
        "Status": status,
    })

    # catalog_variants.csv carries one row per product even for single-SKU products
    # (variant == "Default Title") -- real multi-style products (football figures,
    # squishy flavors, appliance colors) just have more than one row there.
    if not variants:
        variants = [{"variant": "Default Title", "sku": prod["sku"], "barcode": "",
                     "price": prod["price"], "compare_at_price": prod.get("compare_at_price", ""),
                     "stock": prod["stock"]}]
    option_name = "Style" if len(variants) > 1 else "Title"

    rows = []
    first = True
    for v in variants:
        r = base if first else row_template()
        r.update({
            "Handle": handle,
            "Option1 Name": option_name,
            "Option1 Value": v["variant"],
            "Variant SKU": v["sku"],
            "Variant Barcode": v.get("barcode", ""),
            "Variant Price": v["price"],
            "Variant Compare At Price": v.get("compare_at_price", ""),
            "Variant Inventory Qty": v["stock"],
            "Variant Inventory Tracker": "shopify",
            "Variant Inventory Policy": "deny",
            "Variant Fulfillment Service": "manual",
            "Variant Requires Shipping": "TRUE",
            "Variant Taxable": "TRUE",
        })
        if first and imgs:
            r["Image Src"], r["Image Position"], r["Image Alt Text"] = imgs[0], "1", alt_text
        rows.append(r)
        first = False

    for i, src in enumerate(imgs[1:], start=2):
        r = row_template()
        r.update({"Handle": handle, "Image Src": src, "Image Position": str(i),
                  "Image Alt Text": alt_text})
        rows.append(r)
    return rows


def main():
    ap = argparse.ArgumentParser(
        description="Export catalog_products.csv + catalog_variants.csv + generated "
                     "images to a Shopify-import CSV.")
    ap.add_argument("--sku", help="only this SKU (default: all in catalog_products.csv)")
    ap.add_argument("--only-imaged", action="store_true",
                     help="skip products with no images in output/<SKU>/ (for splitting a "
                          "'ready to import' bundle from products still waiting on a generated "
                          "image set)")
    ap.add_argument("--out", default="shopify_import.csv")
    ap.add_argument("--image-base-url", default="",
                     help="public URL prefix for images (Shopify fetches Image Src over HTTP); "
                          "omit for local paths (fine for review, not for import)")
    args = ap.parse_args()
    if args.image_base_url and not args.image_base_url.endswith("/"):
        args.image_base_url += "/"

    with open(CATALOG_PRODUCTS, encoding="utf-8", newline="") as f:
        products = list(csv.DictReader(f))
    incomplete = [p["sku"] for p in products if not p["price"].strip() or not p["stock"].strip()]
    if incomplete:
        print(f"Skipping {len(incomplete)} incomplete catalog row(s) (no price/stock -- "
              f"never finished intake): {incomplete}", file=sys.stderr)
    products = [p for p in products if p["price"].strip() and p["stock"].strip()]
    if args.sku:
        products = [p for p in products if p["sku"] == args.sku]
        if not products:
            sys.exit(f"No such SKU in {CATALOG_PRODUCTS}: {args.sku}")
    if args.only_imaged:
        unimaged = [p["sku"] for p in products if not curated_filenames(os.path.join(OUTPUT_DIR, p["sku"]))]
        if unimaged:
            print(f"--only-imaged: excluding {len(unimaged)} product(s) with no output/<SKU>/ images: "
                  f"{unimaged}", file=sys.stderr)
        products = [p for p in products if p["sku"] not in unimaged]
    variants_by_handle = load_variants_by_handle()

    all_rows = []
    for prod in products:
        rows = rows_for(prod, variants_by_handle.get(prod["handle"], []), args)
        print(f"[{prod['sku']}] {len(rows)} row(s)")
        all_rows.extend(rows)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(all_rows)
    print(f"\nWrote {len(all_rows)} rows for {len(products)} product(s) to '{args.out}'.")
    if not args.image_base_url:
        print("Note: Image Src is a local path -- set --image-base-url to public URLs "
              "before importing to Shopify.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
