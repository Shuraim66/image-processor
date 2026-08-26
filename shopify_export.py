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
import copyguard

PRODUCTS_DIR = "input"
GALLERY_DIR = "output"
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")

COLUMNS = [
    "Handle", "Title", "Body (HTML)", "Vendor", "Product Category", "Type",
    "Tags", "Published", "Option1 Name", "Option1 Value", "Variant SKU",
    "Variant Inventory Tracker", "Variant Inventory Qty", "Variant Inventory Policy",
    "Variant Fulfillment Service", "Variant Price", "Variant Requires Shipping",
    "Variant Taxable", "Image Src", "Image Position", "Image Alt Text",
    "Gift Card", "SEO Title", "SEO Description", "Status",
]


MAX_HANDLE = 70          # Shopify truncates long handles; keep them readable


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def handle_for(profile, sku, mode, seen):
    """The product's URL. Derived from the title by default, not the SKU.

    The handle is what Shopify publishes and what search engines index, so a SKU
    like FIGURE-RONALDO-DANCE puts a trademarked name in the URL even after the
    copy has been cleaned of it. Titles are already sanitized, so they are the
    safer and more searchable source. Collisions fall back to the SKU.
    """
    base = slug(profile.title)[:MAX_HANDLE] if mode == "title" else ""
    if not base:
        base = slug(sku)
    handle = base if base not in seen else f"{base}-{slug(sku)}"[:MAX_HANDLE]
    seen.add(handle)

    leaked = copyguard._hits(handle.replace("-", " "), copyguard.TRADEMARK_TERMS)
    if leaked:
        print(f"  ! {sku}: handle '{handle}' still contains {', '.join(leaked)}",
              file=sys.stderr)
    return handle


def body_html(p: "analyzer.ProductProfile"):
    parts = [f"<p>{html.escape(p.description)}</p>"]
    if p.bullet_points:
        parts.append("<ul>" + "".join(
            f"<li>{html.escape(b)}</li>" for b in p.bullet_points) + "</ul>")
    if p.whats_included:
        parts.append("<p><strong>What's included:</strong></p><ul>" + "".join(
            f"<li>{html.escape(w)}</li>" for w in p.whats_included) + "</ul>")
    return "".join(parts)


def images_for(sku, base_url, out_dir=GALLERY_DIR):
    d = os.path.join(out_dir, sku)
    if not os.path.isdir(d):
        return []
    import gallery_pipeline
    files = [f for f in os.listdir(d) if f.lower().endswith(IMG_EXTS)]
    files.sort(key=gallery_pipeline.slot_sort_key)   # listing order, not A-Z
    return [f"{base_url}{sku}/{f}" if base_url else os.path.join(d, f) for f in files]


def rows_for(sku, folder, args, seen_handles):
    prof_path = analyzer.profile_path(folder, os.path.join(args.out_dir, sku))
    if not os.path.exists(prof_path):
        legacy = os.path.join(folder, "product.json")      # pre-output-root runs
        if not os.path.exists(legacy):
            print(f"  ! {sku}: no product.json (run analyzer.py first)", file=sys.stderr)
            return []
        prof_path = legacy
    p = analyzer.ProductProfile.model_validate_json(open(prof_path, encoding="utf-8").read())

    # The CSV is the last gate before a listing is live, so a product the copy
    # checks flagged does not slip through on its own.
    if p.review_flags and not args.include_flagged:
        print(f"  ! {sku}: held back — {'; '.join(p.review_flags)}", file=sys.stderr)
        return []

    imgs = images_for(sku, args.image_base_url, args.out_dir)
    if not imgs:
        print(f"  ! {sku}: no images in {args.out_dir}/{sku}", file=sys.stderr)

    handle = handle_for(p, sku, args.handle_from, seen_handles)
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
    ap.add_argument("--out-dir", default=GALLERY_DIR, metavar="DIR",
                    help=f"where the pipeline wrote its output (default {GALLERY_DIR}/)")
    ap.add_argument("--handle-from", choices=["title", "sku"], default="title",
                    help="source for the product URL (default title: SEO-friendly "
                         "and free of SKU codes)")
    ap.add_argument("--include-flagged", action="store_true",
                    help="export products the copy checks flagged for review "
                         "(held back by default)")
    ap.add_argument("--image-base-url", default="",
                    help="public URL prefix for images (Shopify fetches Image Src over HTTP)")
    args = ap.parse_args()
    if args.image_base_url and not args.image_base_url.endswith("/"):
        args.image_base_url += "/"

    skus = ([args.sku] if args.sku else
            sorted(d for d in os.listdir(PRODUCTS_DIR)
                   if os.path.isdir(os.path.join(PRODUCTS_DIR, d))))

    all_rows, seen_handles, held = [], set(), 0
    for sku in skus:
        rows = rows_for(sku, os.path.join(PRODUCTS_DIR, sku), args, seen_handles)
        if rows:
            print(f"[{sku}] {len(rows)} row(s)")
            all_rows.extend(rows)
        else:
            held += 1

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(all_rows)
    exported = len(skus) - held
    print(f"\nWrote {len(all_rows)} rows for {exported} product(s) to '{args.out}'.")
    if held:
        print(f"{held} product(s) held back. Fix the flags in product.json, or pass "
              f"--include-flagged to export anyway.", file=sys.stderr)
    if not args.image_base_url:
        print("Note: Image Src holds local paths. Fine for review; Shopify's "
              "importer needs public URLs, so set --image-base-url when you get "
              "to that.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
