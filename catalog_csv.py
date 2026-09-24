#!/usr/bin/env python3
"""Write the shop's product/variant CSVs from the product folders.

Columns match the exports the Shopify developer sent (~/Downloads/products.csv and
variants.csv), so the rows can be pasted straight in. Price, compare-at price and
stock are left empty on purpose: pricing is done by hand, in PKR.

`collections` is not guessed. store_taxonomy evaluates the shop's own smart-collection
rules, so a row lands where Shopify will actually put it; the price-band collections
(under Rs. 1,000 / 2,500 / 5,000 and big-gifts) can't be decided without a price and
are listed separately in the report.

    python catalog_csv.py                  # products with finished catalog images
    python catalog_csv.py --all            # every product folder, ready or not
"""

import argparse
import csv
import json
import os
import re
import sys

import process_products as pp
import store_taxonomy as st

PRODUCTS_CSV = "catalog_products.csv"
VARIANTS_CSV = "catalog_variants.csv"
PENDING_CSV = "catalog_needs_input.csv"
FIELDS = ["handle", "title", "vendor", "product_type", "status", "price", "compare_at_price", "sku", "stock",
          "age", "occasions", "play", "subcategories", "features", "collections", "all_tags", "image", "url",
          "seo_title", "seo_description", "description"]
VARIANT_FIELDS = ["product_handle", "product_title", "variant", "sku", "barcode", "price", "compare_at_price", "stock"]


def profile(sku):
    path = os.path.join(pp.INPUT_DIR, sku, "product.json")
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}


def seo_title_for(prof, title):
    """The store's form: '<Name> in Pakistan | Toy Gift Shop' (see the developer's products.csv)."""
    t = (prof.get("seo_title") or "").strip()
    if t.endswith("| Toy Gift Shop"):
        return t
    name = (prof.get("product_name") or title).strip()
    out = f"{name} in Pakistan | Toy Gift Shop"
    return out if len(out) <= 70 else f"{name} | Toy Gift Shop"


def row_for(folder, prof, collections):
    sku = prof.get("sku") or folder
    title = prof.get("title") or prof.get("product_name") or folder
    category = prof.get("category") or "Novelty & Fun Toys"
    sub = prof.get("sub") or st.PLAY_SUB.get(category, ("games", ""))[1]
    occasions = list(prof.get("occasions") or ["birthday", "eid"])
    # "features" is also the FeatureCard's icon list (dicts) on analysed products — the store's
    # feature tags (gift-ready, new, pick) are only the plain strings
    features = [f for f in (prof.get("store_features") or prof.get("features") or []) if isinstance(f, str)] or ["new"]
    tags = st.tags_for(category, printed_age=prof.get("printed_age", ""), gender=prof.get("gender", ""),
                       occasions=occasions, features=features, sub=sub)
    price = prof.get("price_pkr")                     # the shop's selling price, PKR
    got, price_pending = st.collections_for(category, tags, price, collections)
    age_source = "box" if prof.get("printed_age") else ("n/a" if category in st.NON_TOY_TYPES else "type default")
    age = next((t.split(":", 1)[1] for t in tags if t.startswith("age:")), "")
    play = next((t.split(":", 1)[1] for t in tags if t.startswith("play:")), "")
    row = {
        # store convention: handle = folder name lowercased. Every downstream script finds a
        # product's folder via handle.upper(), so a title-derived handle silently breaks them.
        "handle": prof.get("handle") or folder.lower(),
        "title": title,
        "vendor": prof.get("vendor") or "The Toy Gift Shop",
        "product_type": category,
        "status": prof.get("status") or "DRAFT",       # priced by hand before it goes ACTIVE
        "price": f"{price:.2f}" if price else "", "compare_at_price": "",
        "stock": prof.get("stock", ""),
        "sku": sku,
        "age": age,
        "occasions": ", ".join(occasions),
        "play": play,
        "subcategories": sub,
        "features": ", ".join(features),
        "collections": ", ".join(got if "all" in got else got + ["all"]),
        "all_tags": ", ".join(tags),
        "image": "", "url": "",                        # filled in once the images are uploaded
        "seo_title": seo_title_for(prof, title),
        "seo_description": prof.get("seo_description") or prof.get("meta_description", ""),
        "description": prof.get("description", ""),
    }
    return row, price_pending, age_source


def images_for(sku):
    out = os.path.join(pp.INPUT_DIR, sku, "output")
    order = ["CatalogHero", "CatalogClean", "WhiteBG", "Angle", "Open", "Box", "Detail", "FeatureCard",
             "FeatureProduct", "Lifestyle", "Hero_titled"]
    if not os.path.isdir(out):
        return []
    have = {os.path.splitext(f)[0]: f for f in os.listdir(out) if f.endswith(".png") and not f.endswith("_wm")}
    return [have[n] for n in order if n in have]


def variant_rows(row, prof):
    """catalog_variants.csv rows for one product: one per Star / Colour / Character, else a
    single Default Title row."""
    opts = prof.get("variants") or {}
    values = [v for v in (opts.get("values") or []) if v and v != "assorted"]
    if not values:
        return [{"product_handle": row["handle"], "product_title": row["title"], "variant": "Default Title",
                 "sku": row["sku"], "barcode": "", "price": row["price"], "compare_at_price": "",
                 "stock": row["stock"]}]
    skus = opts.get("skus") or {}
    out = []
    for v in values:
        code = re.sub(r"[^A-Z0-9]+", "-", v.upper()).strip("-")[:20]
        vp = (opts.get("prices") or {}).get(v) or prof.get("price_pkr")
        vs = (opts.get("stock") or {}).get(v, "")    # blank = count not given yet
        out.append({"product_handle": row["handle"], "product_title": row["title"], "variant": v,
                    "sku": skus.get(v) or f"{row['sku']}-{code}", "barcode": "",
                    "price": f"{vp:.2f}" if vp else "", "compare_at_price": "", "stock": vs})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="every product folder, not only the finished ones")
    ap.add_argument("--out", default=".", help="where to write the CSVs")
    args = ap.parse_args()

    collections = st.load_collections()
    rows, variants, pending = [], [], []
    for sku in pp.find_sku_folders(pp.INPUT_DIR):
        prof = profile(sku)
        done = bool(prof.get("images_done")) or bool(images_for(sku))
        if not (args.all or done):
            continue
        row, price_pending, age_source = row_for(sku, prof, collections)
        rows.append(row)
        variants.extend(variant_rows(row, prof))
        missing = [k for k in ("description", "seo_title", "seo_description") if not row[k]]
        if not images_for(sku):
            missing.append("catalog images")
        pending.append({"sku": row["sku"], "title": row["title"], "images": len(images_for(sku)),
                        "age_from": age_source,
                        "needs": "; ".join(missing + ([] if prof.get("price_pkr") else ["price (PKR)"])
                                           + ([] if prof.get("stock") != None else ["stock"])
                                           + [f"stock for {', '.join((prof.get('variants') or {}).get('stock_pending', []))}"]
                                             * bool((prof.get("variants") or {}).get("stock_pending"))),
                        "collections_pending_on_price": ", ".join(price_pending)})

    os.makedirs(args.out, exist_ok=True)
    for name, fields, data in ((PRODUCTS_CSV, FIELDS, rows), (VARIANTS_CSV, VARIANT_FIELDS, variants),
                              (PENDING_CSV, ["sku", "title", "images", "age_from", "needs", "collections_pending_on_price"], pending)):
        with open(os.path.join(args.out, name), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(data)
        print(f"wrote {os.path.join(args.out, name)}  ({len(data)} rows)")
    for r, p in zip(rows, pending):
        print(f"  {r['sku']:30s} {r['product_type']:28s} {r['collections']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
