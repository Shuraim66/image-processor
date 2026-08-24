#!/usr/bin/env python3
"""
Shopify product CSV exporter.

Reads each product's `input/<SKU>/product.json` (from analyzer.py) + its gallery
images (`gallery_out/<SKU>/*.jpg`) and writes a Shopify-import CSV: one product
row with the full data, then one extra row per additional image.

    python shopify_export.py
    python shopify_export.py --image-base-url https://cdn.example.com/toys/ \
        --status active --price 29.99

Note: Shopify's importer fetches Image Src over HTTP, so it needs PUBLIC URLs.
Pass --image-base-url to prefix your hosted image location; without it the CSV
lists relative paths (fine for review, but upload the images or set a base URL
before importing to Shopify).
"""

import argparse
import csv
import html
import json
import os
import re
import sys

import analyzer

PRODUCTS_DIR = "input"
GALLERY_DIR = "gallery_out"
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")

COLUMNS = [
    "Handle", "Title", "Body (HTML)", "Vendor", "Product Category", "Type",
    "Tags", "Published", "Option1 Name", "Option1 Value", "Variant SKU",
    "Variant Inventory Tracker", "Variant Inventory Qty", "Variant Inventory Policy",
    "Variant Fulfillment Service", "Variant Price", "Variant Requires Shipping",
    "Variant Taxable", "Image Src", "Image Position", "Image Alt Text",
    "Gift Card", "SEO Title", "SEO Description", "Status",
]


def slug(sku):
    return re.sub(r"[^a-z0-9]+", "-", sku.lower()).strip("-")


def body_html(p: "analyzer.ProductProfile"):
    parts = [f"<p>{html.escape(p.description)}</p>"]
    if p.bullet_points:
        parts.append("<ul>" + "".join(
            f"<li>{html.escape(b)}</li>" for b in p.bullet_points) + "</ul>")
    if p.whats_included:
        parts.append("<p><strong>What's included:</strong></p><ul>" + "".join(
            f"<li>{html.escape(w)}</li>" for w in p.whats_included) + "</ul>")
    return "".join(parts)


def images_for(sku, base_url, per_product=False):
    d = os.path.join(PRODUCTS_DIR, sku, "output") if per_product else os.path.join(GALLERY_DIR, sku)
    if not os.path.isdir(d):
        return []
    files = sorted(f for f in os.listdir(d) if f.lower().endswith(IMG_EXTS))
    return [f"{base_url}{sku}/{f}" if base_url else os.path.join(d, f) for f in files]


def rows_for(sku, folder, args):
    prof_path = os.path.join(folder, "product.json")
    if not os.path.exists(prof_path):
        print(f"  ! {sku}: no product.json (run analyzer.py first)", file=sys.stderr)
        return []
    p = analyzer.ProductProfile.model_validate_json(open(prof_path, encoding="utf-8").read())
    imgs = images_for(sku, args.image_base_url, per_product=args.per_product)
    if not imgs:
        print(f"  ! {sku}: no gallery images in {GALLERY_DIR}/{sku}", file=sys.stderr)

    handle = slug(sku)
    base = {c: "" for c in COLUMNS}
    base.update({
        "Handle": handle,
        "Title": p.title,
        "Body (HTML)": body_html(p),
        "Vendor": args.vendor,
        "Type": "Toy",
        "Tags": ", ".join(p.tags),
        "Published": "TRUE" if args.status == "active" else "FALSE",
        "Option1 Name": "Title",
        "Option1 Value": "Default Title",
        "Variant SKU": sku,
        "Variant Inventory Tracker": "shopify",
        "Variant Inventory Qty": str(args.qty),
        "Variant Inventory Policy": "deny",
        "Variant Fulfillment Service": "manual",
        "Variant Price": str(args.price) if args.price else "",
        "Variant Requires Shipping": "TRUE",
        "Variant Taxable": "TRUE",
        "Gift Card": "FALSE",
        "SEO Title": p.seo_title,
        "SEO Description": p.meta_description,
        "Status": args.status,
        "Image Src": imgs[0] if imgs else "",
        "Image Position": "1" if imgs else "",
        "Image Alt Text": p.alt_text,
    })
    rows = [base]
    for i, src in enumerate(imgs[1:], start=2):        # extra images: image-only rows
        r = {c: "" for c in COLUMNS}
        r.update({"Handle": handle, "Image Src": src, "Image Position": str(i),
                  "Image Alt Text": p.alt_text})
        rows.append(r)
    return rows


def main():
    ap = argparse.ArgumentParser(description="Export product.json + gallery images to a Shopify CSV.")
    ap.add_argument("--sku", help="only this SKU (default: all under input/)")
    ap.add_argument("--out", default="shopify_import.csv")
    ap.add_argument("--vendor", default="The Toy Gift Shop")
    ap.add_argument("--status", choices=["draft", "active"], default="draft")
    ap.add_argument("--price", default="", help="variant price (blank = set later in Shopify)")
    ap.add_argument("--qty", type=int, default=0, help="inventory quantity")
    ap.add_argument("--per-product", action="store_true",
                    help="read images from input/<SKU>/output/ (matches --per-product build)")
    ap.add_argument("--image-base-url", default="",
                    help="public URL prefix for images (Shopify fetches Image Src over HTTP)")
    args = ap.parse_args()
    if args.image_base_url and not args.image_base_url.endswith("/"):
        args.image_base_url += "/"

    skus = ([args.sku] if args.sku else
            sorted(d for d in os.listdir(PRODUCTS_DIR)
                   if os.path.isdir(os.path.join(PRODUCTS_DIR, d))))

    all_rows = []
    for sku in skus:
        rows = rows_for(sku, os.path.join(PRODUCTS_DIR, sku), args)
        if rows:
            print(f"[{sku}] {len(rows)} row(s)")
            all_rows.extend(rows)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(all_rows)
    print(f"\nWrote {len(all_rows)} rows for {len(skus)} product(s) to '{args.out}'.")
    if not args.image_base_url:
        print("Note: Image Src is relative — set --image-base-url to public URLs "
              "before importing to Shopify.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
