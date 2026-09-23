#!/usr/bin/env python3
"""Propose which SKUs are really color-variants of one product.

Rule: identical mold/shape in a different color -> one Shopify product with a
Color variant. Different shape/design -> stays a separate product, even if it
shares a category (a "sports car" die-cast and another "sports car" die-cast
are still different products unless they're literally the same tooling).

A same/different judgment call like that is exactly what a vision model can
help with, but pure "are these the same item" VLM matching has a measured
failure rate on this kind of product photography (see intake.py's docstring —
2 of 6 on a comparable task), so this narrows the search first: group folders
by a coarse category keyword (cheap, no model needed), then only spend a model
call on pairs *within* the same category. That keeps the comparison space
small enough that a wrong call is rare and, more importantly, cheap to correct
by hand from the printed report — nothing is renamed or merged automatically.

    python detect_variants.py                      # scan input/, print proposal
    python detect_variants.py --out variant_groups.json --apply

--apply only writes the proposal to --out; it never touches input/ folders.
shopify_export.py can later read that file to group variant rows under one
Handle instead of treating every folder as its own product.
"""

import argparse
import itertools
import json
import os
import re
import sys

import ollama

INPUT_DIR = "input"
MODEL = os.environ.get("OLLAMA_VLM", "qwen3-vl:8b-instruct-q4_K_M")
VALID = (".jpg", ".jpeg", ".png", ".webp")

PROMPT = (
    "You are shown two product photos from an online toy catalog, photo A first "
    "then photo B. Decide: do A and B show the SAME physical product design/mold, "
    "just in a different color, or are they DIFFERENT product designs (different "
    "shape, different mechanism, different kind of item)? Two die-cast cars of "
    "different real-world models are DIFFERENT even if both are cars. Two "
    "identical-looking cases in different colors are SAME.\n"
    "Reply as JSON: {\"verdict\": \"SAME\" or \"DIFFERENT\", \"reason\": \"<one short sentence>\"}"
)


def category_of(sku):
    """Coarse pre-filter: the first word after the TGS- prefix (CASE, CAR, TUMBLER...)."""
    from process_products import sku_stem
    return sku_stem(sku).split("-")[0]


def front_photo(sku_dir):
    for fn in sorted(os.listdir(sku_dir)):
        if fn.lower().startswith("front") and fn.lower().endswith(VALID):
            return os.path.join(sku_dir, fn)
    for fn in sorted(os.listdir(sku_dir)):
        if fn.lower().endswith(VALID):
            return os.path.join(sku_dir, fn)
    return None


def compare(path_a, path_b):
    try:
        resp = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": PROMPT, "images": [path_a, path_b]}],
            options={"temperature": 0.1, "num_ctx": 4096},
            format={"type": "object", "properties": {
                "verdict": {"type": "string", "enum": ["SAME", "DIFFERENT"]},
                "reason": {"type": "string"}}},
        )
        data = json.loads(resp["message"]["content"])
        return data.get("verdict", "DIFFERENT"), data.get("reason", "")
    except Exception as exc:  # noqa: BLE001 — keep the scan alive
        return "DIFFERENT", f"error: {exc}"


def union_find_groups(pairs, all_skus):
    parent = {s: s for s in all_skus}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in pairs:
        union(a, b)

    groups = {}
    for s in all_skus:
        groups.setdefault(find(s), []).append(s)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=INPUT_DIR, help="folder of product folders to scan (default input/)")
    ap.add_argument("--out", default="variant_groups.json", help="where to write the proposal")
    ap.add_argument("--apply", action="store_true", help="write --out (default: print only)")
    args = ap.parse_args()

    skus = sorted(d for d in os.listdir(args.dir) if os.path.isdir(os.path.join(args.dir, d)))
    by_category = {}
    for sku in skus:
        by_category.setdefault(category_of(sku), []).append(sku)

    candidates = {cat: members for cat, members in by_category.items() if len(members) > 1}
    total_pairs = sum(len(list(itertools.combinations(m, 2))) for m in candidates.values())
    print(f"{len(skus)} SKUs, {len(candidates)} categories with 2+ members, "
          f"{total_pairs} pair(s) to check\n")

    same_pairs, reasons = [], {}
    done = 0
    for cat, members in candidates.items():
        for a, b in itertools.combinations(members, 2):
            pa, pb = front_photo(os.path.join(args.dir, a)), front_photo(os.path.join(args.dir, b))
            if not pa or not pb:
                continue
            verdict, reason = compare(pa, pb)
            done += 1
            print(f"[{done}/{total_pairs}] {a} vs {b}: {verdict} ({reason})")
            if verdict == "SAME":
                same_pairs.append((a, b))
                reasons[f"{a}|{b}"] = reason

    groups = union_find_groups(same_pairs, skus)
    print(f"\n{len(groups)} proposed variant group(s):\n")
    for g in groups:
        print(f"  {g}")

    if not groups:
        print("\nNo variant candidates found — every SKU stays its own product.")
        return 0

    if not args.apply:
        print(f"\nRe-run with --apply to write this proposal to {args.out}. "
              "Nothing in input/ is changed either way — review the groups above first.")
        return 0

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"groups": groups, "reasons": reasons}, f, indent=2)
    print(f"\nWrote proposal to {args.out}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
