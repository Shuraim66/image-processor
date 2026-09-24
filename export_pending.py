#!/usr/bin/env python3
"""
Build the "pending" dev-handoff bundle: everything NOT yet ready for a real
Shopify import, split into three reasons via the Row Type column:

  active_unimaged     -- in catalog_products.csv (priced, stocked, DRAFT) but
                          fal.ai hasn't generated its CatalogHero/etc. yet
  content_policy      -- backlog-products-image-failed/: fully priced/stocked,
                          fal/OpenAI refuses the image (licensed characters)
  backlog_low_stock   -- backlog-products/: below the stock-listing threshold,
                          price may still be TBD

Writes shopify_import_pending.csv (same 27 Shopify columns as shopify_export.py,
plus Row Type / Units On Hand / Notes for tracking -- NOT meant to be imported
as-is) and copies up to --max-photos raw shoot photos per product into
output_pending/<SKU>/ (there's no generated output/ to reuse for these).

    python export_pending.py
"""
import argparse
import csv
import json
import os
import sys

from PIL import Image

import shopify_export as se

PENDING_DIR = "output_pending"
BACKLOG_DIR = "backlog-products"
FAILED_DIR = "backlog-products-image-failed"
IMG_EXTS = se.IMG_EXTS
MAX_DIM = 1280  # these are raw camera shoot photos (several MB each) -- for a "what's
                # outstanding" reference bundle they're downscaled, not archival originals
EXTRA_COLUMNS = ["Row Type", "Units On Hand", "Notes"]
COLUMNS = se.COLUMNS + EXTRA_COLUMNS


def raw_photos(folder, limit):
    if not os.path.isdir(folder):
        return []
    files = sorted(
        f for f in os.listdir(folder)
        if f.lower().endswith(IMG_EXTS) and os.path.isfile(os.path.join(folder, f))
    )
    return files[:limit]


def copy_images(sku, src_dir, limit):
    files = raw_photos(src_dir, limit)
    if not files:
        return []
    dest = os.path.join(PENDING_DIR, sku)
    os.makedirs(dest, exist_ok=True)
    out_names = []
    for fn in files:
        out_name = os.path.splitext(fn)[0] + ".jpg"
        try:
            im = Image.open(os.path.join(src_dir, fn))
            im = im.convert("RGB")
            im.thumbnail((MAX_DIM, MAX_DIM), Image.LANCZOS)
            im.save(os.path.join(dest, out_name), "JPEG", quality=82, optimize=True)
        except Exception as e:
            print(f"  ! {sku}/{fn}: {e}", file=sys.stderr)
            continue
        out_names.append(out_name)
    return out_names


def blank_row():
    r = se.row_template()
    for c in EXTRA_COLUMNS:
        r[c] = ""
    return r


def rows_for_pending(sku, title, vendor, ptype, tags, seo_title, seo_desc, body_html,
                      price, stock, images, row_type, units_note, notes, base_url, image_base_dir):
    handle = sku.lower()
    base = blank_row()
    base.update({
        "Handle": handle,
        "Title": title,
        "Body (HTML)": body_html,
        "Vendor": vendor,
        "Type": ptype,
        "Tags": tags,
        "Published": "FALSE",
        "Option1 Name": "Title",
        "Option1 Value": "Default Title",
        "Variant SKU": sku,
        "Variant Inventory Tracker": "shopify",
        "Variant Inventory Policy": "deny",
        "Variant Fulfillment Service": "manual",
        "Variant Price": price,
        "Variant Inventory Qty": stock,
        "Variant Requires Shipping": "TRUE",
        "Variant Taxable": "TRUE",
        "Gift Card": "FALSE",
        "SEO Title": seo_title,
        "SEO Description": seo_desc,
        "Status": "draft",
        "Row Type": row_type,
        "Units On Hand": units_note,
        "Notes": notes,
    })
    rows = []
    if images:
        first = f"{base_url}{sku}/{images[0]}" if base_url else os.path.join(image_base_dir, sku, images[0])
        base["Image Src"], base["Image Position"], base["Image Alt Text"] = first, "1", title
    rows.append(base)
    for i, fn in enumerate(images[1:], start=2):
        r = blank_row()
        src = f"{base_url}{sku}/{fn}" if base_url else os.path.join(image_base_dir, sku, fn)
        r.update({"Handle": handle, "Image Src": src, "Image Position": str(i),
                   "Image Alt Text": title, "Row Type": row_type})
        rows.append(r)
    return rows


def active_unimaged_rows(args):
    with open(se.CATALOG_PRODUCTS, encoding="utf-8", newline="") as f:
        products = [p for p in csv.DictReader(f) if p["price"].strip() and p["stock"].strip()]
    variants_by_handle = se.load_variants_by_handle()
    out, n = [], 0
    for p in products:
        src_dir = os.path.join(se.PRODUCTS_DIR, p["handle"].upper())
        if se.curated_filenames(os.path.join(se.OUTPUT_DIR, p["sku"])):
            continue  # already in the "ready" bundle
        n += 1
        images = copy_images(p["sku"], src_dir, args.max_photos)
        variants = variants_by_handle.get(p["handle"], [])
        variant_stocks = [v["stock"] for v in variants if v.get("stock", "").strip()]
        stock = sum(int(float(s)) for s in variant_stocks) if variant_stocks else int(float(p["stock"]))
        bullets, included = [], []
        pj_path = os.path.join(src_dir, "product.json")
        if os.path.exists(pj_path):
            pj = json.load(open(pj_path, encoding="utf-8"))
            bullets, included = pj.get("bullet_points") or [], pj.get("whats_included") or []
        body = se.body_html(p["description"], bullets, included)
        out += rows_for_pending(
            p["sku"], p["title"], p["vendor"], p["product_type"], p["all_tags"],
            p["seo_title"], p["seo_description"], body, p["price"], stock, images,
            "active_unimaged", str(stock), "Priced & stocked; waiting on a generated CatalogHero/Lifestyle image.",
            args.image_base_url, PENDING_DIR)
    return out, n


def backlog_rows(folder_root, row_type, note_prefix, args):
    out, count = [], 0
    if not os.path.isdir(folder_root):
        return out, count
    for folder in sorted(os.listdir(folder_root)):
        d = os.path.join(folder_root, folder)
        pj_path = os.path.join(d, "product.json")
        if not os.path.isfile(pj_path):
            continue
        count += 1
        pj = json.load(open(pj_path, encoding="utf-8"))
        sku = pj.get("sku") or folder
        title = pj.get("title") or pj.get("product_name") or folder
        price = pj.get("price_pkr")
        price = f"{float(price):.2f}" if price not in (None, "") else ""
        units = pj.get("units_last_seen")
        units_note = str(units) if units not in (None, "") else "unknown"
        tags = ", ".join(pj.get("tags") or [])
        seo_title = pj.get("seo_title") or title
        seo_desc = pj.get("meta_description") or ""
        body = se.body_html(pj.get("description") or "", pj.get("bullet_points") or [],
                             pj.get("whats_included") or [])
        images = copy_images(sku, d, args.max_photos)
        notes = f"{note_prefix} Folder: {folder_root}/{folder}"
        out += rows_for_pending(
            sku, title, "The Toy Gift Shop", pj.get("category") or "", tags,
            seo_title, seo_desc, body, price, 0, images, row_type, units_note, notes,
            args.image_base_url, PENDING_DIR)
    return out, count


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-photos", type=int, default=3,
                     help="raw shoot photos to copy per pending product (default: 3, to keep "
                          "the handoff zip a manageable size)")
    ap.add_argument("--image-base-url", default="")
    ap.add_argument("--out", default="shopify_import_pending.csv")
    ap.add_argument("--shopify-only", action="store_true",
                     help="write a clean, standard 27-column Shopify-import CSV instead: only the "
                          "real priced/stocked products waiting on an image (active_unimaged + "
                          "content_policy) -- excludes backlog_low_stock (not real listings yet, "
                          "many have no price) and drops the Row Type/Units On Hand/Notes tracking "
                          "columns. All rows still Published=FALSE / Status=draft.")
    args = ap.parse_args()
    if args.image_base_url and not args.image_base_url.endswith("/"):
        args.image_base_url += "/"

    os.makedirs(PENDING_DIR, exist_ok=True)

    unimaged_rows, unimaged_n = active_unimaged_rows(args)
    failed_rows, failed_n = backlog_rows(
        FAILED_DIR, "content_policy",
        "Fully priced/stocked; fal/OpenAI content-policy block (licensed character) -- needs a manual image.",
        args)
    backlog_rows_, backlog_n = backlog_rows(
        BACKLOG_DIR, "backlog_low_stock",
        "Below the stock-listing threshold (or explicitly discontinued) -- not priced for sale yet.",
        args)

    if args.shopify_only:
        all_rows = unimaged_rows + failed_rows
        for r in all_rows:
            for c in EXTRA_COLUMNS:
                r.pop(c, None)
        out_path = args.out if args.out != "shopify_import_pending.csv" else "shopify_import_draft.csv"
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=se.COLUMNS)
            w.writeheader()
            w.writerows(all_rows)
        print(f"active_unimaged: {unimaged_n} products")
        print(f"content_policy:  {failed_n} products")
        print(f"(backlog_low_stock excluded: {backlog_n} products -- not real listings yet)")
        print(f"\nWrote {len(all_rows)} rows for {unimaged_n + failed_n} product(s) to '{out_path}' "
              f"(standard Shopify columns only, Published=FALSE).")
        return 0

    all_rows = unimaged_rows + failed_rows + backlog_rows_
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(all_rows)

    print(f"active_unimaged:   {unimaged_n} products")
    print(f"content_policy:    {failed_n} products")
    print(f"backlog_low_stock: {backlog_n} products")
    print(f"\nWrote {len(all_rows)} rows for {unimaged_n + failed_n + backlog_n} product(s) to '{args.out}'.")
    if not args.image_base_url:
        print("Note: Image Src is a local path.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
