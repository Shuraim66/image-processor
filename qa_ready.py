#!/usr/bin/env python3
"""
Pre-launch QA pass over the "ready" bundle (98 active products with a generated
image set) -- everything scheduled to go live today. Checks pricing, stock,
category/subcategory/age completeness, copy/SEO quality, image file integrity,
and structural correctness of shopify_import_ready.csv itself.

    python qa_ready.py
"""
import csv
import hashlib
import json
import os
import re
import sys

from PIL import Image

import shopify_export as se

CSV_PATH = "shopify_import_ready.csv"


def load_ready_skus():
    with open(se.CATALOG_PRODUCTS, encoding="utf-8", newline="") as f:
        products = [p for p in csv.DictReader(f)
                    if p["price"].strip() and p["stock"].strip()
                    and se.curated_filenames(os.path.join(se.OUTPUT_DIR, p["sku"]))]
    return products


def check_product_row(p, issues):
    sku = p["sku"]
    # price
    try:
        price = float(p["price"])
        if price <= 0:
            issues.append((sku, "price", f"non-positive price: {price}"))
    except ValueError:
        issues.append((sku, "price", f"unparseable price: {p['price']!r}"))
    # stock
    try:
        stock = int(float(p["stock"]))
        if stock <= 0:
            issues.append((sku, "stock", f"zero/negative stock: {stock}"))
    except ValueError:
        issues.append((sku, "stock", f"unparseable stock: {p['stock']!r}"))
    # category / sub / age
    if not p["product_type"].strip():
        issues.append((sku, "category", "blank product_type"))
    if not p["subcategories"].strip():
        issues.append((sku, "subcategory", "blank subcategories"))
    if not p["age"].strip():
        issues.append((sku, "age", "blank age tag"))
    # copy
    desc = p["description"].strip()
    if len(desc) < 40:
        issues.append((sku, "description", f"too short ({len(desc)} chars): {desc!r}"))
    seo_title = p["seo_title"].strip()
    if not seo_title.endswith("| Toy Gift Shop"):
        issues.append((sku, "seo_title", f"doesn't end '| Toy Gift Shop': {seo_title!r}"))
    if not p["seo_description"].strip():
        issues.append((sku, "seo_description", "blank"))
    # glitch patterns: stray non-English words, leftover placeholders, double spaces
    text_blob = f"{p['title']} {desc} {p['seo_description']}"
    for pat, label in [
        (r"\bTBD\b|\bTODO\b|\bundefined\b|\bNone\b|\bnull\b", "placeholder text"),
        (r"  +", "double space"),
        (r"[À-ÿ]{3,}", "non-ASCII / foreign-script run (possible stray translation)"),
    ]:
        m = re.search(pat, text_blob)
        if m:
            issues.append((sku, "copy-glitch", f"{label}: ...{text_blob[max(0,m.start()-20):m.end()+20]}..."))
    if p["title"] != p["title"].strip():
        issues.append((sku, "title", f"leading/trailing whitespace: {p['title']!r}"))


def check_images(sku, issues):
    d = os.path.join(se.OUTPUT_DIR, sku)
    files = se.curated_filenames(d)
    if not files:
        issues.append((sku, "image", "no curated images at all"))
        return {}
    if "_wm" in files[0] or not files[0].startswith("CatalogClean"):
        issues.append((sku, "image",
                       f"main image (position 1) is {files[0]!r}, not an unwatermarked CatalogClean -- "
                       f"likely missing output/{sku}/CatalogClean.png"))
    hashes = {}
    for fn in files:
        path = os.path.join(d, fn)
        try:
            im = Image.open(path)
            im.verify()
        except Exception as e:
            issues.append((sku, "image", f"{fn}: fails to open/verify ({e})"))
            continue
        size = os.path.getsize(path)
        if size < 1024:
            issues.append((sku, "image", f"{fn}: suspiciously small ({size} bytes)"))
        with open(path, "rb") as f:
            h = hashlib.md5(f.read()).hexdigest()
        hashes[fn] = h
    return hashes


def main():
    products = load_ready_skus()
    issues = []

    seen_handles, seen_skus = {}, {}
    all_hashes = {}  # md5 -> [(sku, fname), ...] to catch cross-product duplicate images
    for p in products:
        sku = p["sku"]
        check_product_row(p, issues)
        if p["handle"] in seen_handles:
            issues.append((sku, "duplicate", f"handle '{p['handle']}' also used by {seen_handles[p['handle']]}"))
        seen_handles[p["handle"]] = sku
        if sku in seen_skus:
            issues.append((sku, "duplicate", "duplicate SKU in catalog_products.csv"))
        seen_skus[sku] = True
        hashes = check_images(sku, issues)
        for fn, h in hashes.items():
            all_hashes.setdefault(h, []).append((sku, fn))

    for h, occurrences in all_hashes.items():
        skus_involved = {sku for sku, _ in occurrences}
        if len(skus_involved) > 1:
            issues.append((", ".join(sorted(skus_involved)), "image",
                            f"identical image reused across products: {occurrences}"))

    # CSV structural check
    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    by_handle = {}
    for r in rows:
        by_handle.setdefault(r["Handle"], []).append(r)
    for handle, hrows in by_handle.items():
        positions = [r["Image Position"] for r in hrows if r["Image Position"].strip()]
        expected = [str(i) for i in range(1, len(positions) + 1)]
        if positions != expected:
            issues.append((handle, "csv-structure", f"Image Position sequence not 1..N: {positions}"))
        variant_rows = [r for r in hrows if r["Variant SKU"].strip()]
        if not variant_rows:
            issues.append((handle, "csv-structure", "no variant row (missing price/sku entirely)"))
        for r in variant_rows:
            if not r["Variant Price"].strip():
                issues.append((handle, "csv-structure", f"variant {r['Variant SKU']} has no price"))

    print(f"Checked {len(products)} ready products, {len(rows)} CSV rows.\n")
    if not issues:
        print("No issues found.")
        return 0

    by_field = {}
    for sku, field, msg in issues:
        by_field.setdefault(field, []).append((sku, msg))
    for field, items in sorted(by_field.items()):
        print(f"=== {field} ({len(items)}) ===")
        for sku, msg in items:
            print(f"  {sku}: {msg}")
        print()
    print(f"TOTAL: {len(issues)} issue(s) across {len(set(i[0] for i in issues))} product(s)/group(s).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
