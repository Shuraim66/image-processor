#!/usr/bin/env python3
"""Label what each product photo shows, so every catalog image uses the right one.

A shoot has the product from the front, other angles, opened with its contents,
next to its box, the box front/back… The fal set used to re-stage only the first
photo; fal_listing.plan_slots() now picks a photo per slot from these labels.

Each photo gets one view from VIEWS, asked of the local vision model one photo at
a time (downscaled — it's a coarse judgment, and single images keep it reliable).
Labels are saved in input/<SKU>/product.json under "photos" — hand-edit any that
are wrong; they're kept on re-analysis and only re-asked with --retag.

The same call names the item in each photo ("photo_items") and records whether
any retail packaging is visible ("photo_packaging": box, sleeve, band, card, tag).
mixed_folder() flags folders whose photos show different products — e.g. a tractor
shot filed under the cow toy — and the Lifestyle image only ever uses a photo with
no packaging in it.

    python photo_tags.py --sku TGS-CASE-BRIEFCASE-UNICORN-RAINBOW-PINK
    python photo_tags.py --all
"""

import argparse
import base64
import hashlib
import io
import json
import os
import sys

from PIL import Image, ImageOps

import analyzer
import process_products as pp

VIEWS = {
    "product_front": "the product itself (out of its box, or a product sold without a box), main side facing the camera",
    "product_angle": "the product itself seen from its side, top or a three-quarter angle",
    "product_back": "the product itself seen from directly behind (its back or rear side)",
    "product_open": "the product opened up (lid, case or door open) so its inside or included items are visible",
    "product_with_box": "the product out of the box placed next to or in front of its retail box",
    "box_front": "the closed retail box or packaging, front side, product still inside",
    "box_back": "the back or side of the retail box, showing printed features or instructions",
    "contents": "the included pieces or accessories laid out separately",
    "closeup": "a close-up of one part or detail of the product",
}
PROMPT = (
    "This is one photo from a product photo shoot for a children's toy shop. "
    "Which ONE of these best describes what the photo shows?\n"
    + "\n".join(f"- {k}: {v}" for k, v in VIEWS.items())
    + "\nA product that wears a printed cardboard sleeve or band is still the product itself. "
    "Also give 'item': a 2-4 word name for the toy itself, e.g. 'dancing cow toy' or "
    "'toy tractor' (if only a box is shown, name the toy printed on it). "
    "And 'packaging': true if ANY retail packaging is visible anywhere in the photo — a box, "
    "a cardboard sleeve or band around the product, a blister card, a bag or a hang tag — "
    "even when the product itself is also shown; false only if the product is completely "
    "free of packaging. "
    "Reply as JSON: {\"view\": \"<name>\", \"item\": \"<name>\", \"packaging\": true|false}"
)
TAG_PX = 768
# Model labels keyed by the photo's content, so a photo moved to another folder is never
# re-asked. Hand corrections live in each product.json and always win over this cache.
LABEL_CACHE = "photo_labels.json"
_cache = None


def _md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def cached_label(path, ask=True):
    """(view, item, packaging) for a photo from the content cache, asking the model once."""
    global _cache
    if _cache is None:
        _cache = json.load(open(LABEL_CACHE, encoding="utf-8")) if os.path.exists(LABEL_CACHE) else {}
    key = _md5(path)
    if key not in _cache:
        if not ask:
            return None
        view, item, packed = tag_photo(path)
        _cache[key] = {"view": view, "item": item, "packaging": packed}
        with open(LABEL_CACHE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(_cache, f, indent=1)
        os.replace(LABEL_CACHE + ".tmp", LABEL_CACHE)
    c = _cache[key]
    return c["view"], c["item"], c["packaging"]


def _b64(path, px=TAG_PX):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    im.thumbnail((px, px))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def tag_photo(path):
    import ollama
    resp = ollama.chat(
        model=analyzer.OLLAMA_MODEL,
        messages=[{"role": "user", "content": PROMPT, "images": [_b64(path)]}],
        format={"type": "object", "properties": {"view": {"type": "string", "enum": list(VIEWS)},
                                                 "item": {"type": "string"},
                                                 "packaging": {"type": "boolean"}},
                "required": ["view", "item", "packaging"]},
        options={"temperature": 0.0, "num_ctx": 4096},
    )
    data = json.loads(resp["message"]["content"])
    return data["view"], data.get("item", "").strip().lower(), bool(data.get("packaging", True))


# words that don't tell two products apart
_GENERIC = {"toy", "toys", "kids", "kid", "children", "childrens", "child", "baby", "box", "set",
            "game", "the", "a", "an", "with", "and", "of", "for", "in", "mini", "small", "large",
            "plastic", "product", "packaging", "retail", "kit", "play", "electric", "musical"}


def _words(item):
    return {w.strip(".,'\"()-").rstrip("s") for w in item.lower().replace("-", " ").split()} - _GENERIC - {""}


def _related(a, b):
    """Words for the same thing: exact, or one a stem of the other ('dino' / 'dinosaur')."""
    return any(x == y or (min(len(x), len(y)) >= 3 and (x.startswith(y) or y.startswith(x)))
               for x in a for y in b)


def mixed_folder(items):
    """Photos whose item shares no word with any other photo's item (e.g. 'toy tractor'
    among 'dancing cow' shots); every photo if nothing matches at all. [] = consistent."""
    if len(items) < 2:
        return []
    words = {n: _words(i) for n, i in items.items()}
    odd = [n for n, w in words.items() if w and not any(_related(w, o) for m, o in words.items() if m != n)]
    return odd if len(odd) < len(items) else sorted(items)   # nothing in common at all: flag all


def tag_folder(folder, retag=False):
    """Return {filename: view} for the folder, asking the model only for new photos."""
    pj = os.path.join(folder, "product.json")
    data = json.load(open(pj, encoding="utf-8")) if os.path.exists(pj) else {}
    tags = {} if retag else dict(data.get("photos") or {})
    items = {} if retag else dict(data.get("photo_items") or {})
    packaging = {} if retag else dict(data.get("photo_packaging") or {})
    changed = False
    for path in pp.raw_images_in(folder):
        name = os.path.basename(path)
        if name in tags and name in items and name in packaging:
            continue
        try:
            view, item, packed = cached_label(path)
            tags.setdefault(name, view)          # never overwrite a label someone corrected
            items.setdefault(name, item)
            packaging.setdefault(name, packed)
        except Exception as exc:  # noqa: BLE001 — an untagged photo just isn't planned for
            print(f"  ! {name}: {exc}", file=sys.stderr)
            continue
        changed = True
        print(f"  {name:22s} {tags[name]:17s} {'[packaging] ' if packaging[name] else ''}{items[name]}",
              flush=True)
    tags = {k: v for k, v in tags.items() if os.path.exists(os.path.join(folder, k))}
    items = {k: v for k, v in items.items() if k in tags}
    packaging = {k: v for k, v in packaging.items() if k in tags}
    if changed or retag:
        data["photos"], data["photo_items"], data["photo_packaging"] = tags, items, packaging
        with open(pj, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False))
    return tags


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sku", action="append", help="product folder name; repeatable")
    ap.add_argument("--all", action="store_true", help="every product under input/")
    ap.add_argument("--retag", action="store_true", help="ask again even for photos already labelled")
    args = ap.parse_args()
    skus = pp.find_sku_folders(pp.INPUT_DIR) if args.all else (args.sku or [])
    if not skus:
        ap.error("give --sku or --all")
    for sku in skus:
        print(f"[{sku}]")
        folder = os.path.join(pp.INPUT_DIR, sku)
        tag_folder(folder, retag=args.retag)
        odd = mixed_folder(items_for(folder))
        if odd:
            print(f"  ! MIXED FOLDER? these photos look like a different product: {', '.join(odd)}")
    return 0


_NAME_NOISE = {"red", "blue", "green", "yellow", "pink", "black", "white", "grey", "gray", "silver", "teal",
               "navy", "maroon", "brown", "purple", "orange", "beige", "peach", "rosegold", "darkblue",
               "whiteblue", "whitegreen", "blueorange", "colorful", "rainbow", "gold", "electric", "walking",
               "dancing", "boxed", "deluxe", "large", "small", "lg", "duo", "trio", "pair", "solo", "open",
               "clearcase", "box", "toy", "set", "kids", "mini", "tgs"}


def name_mismatch(sku, items):
    """The photos' item names share nothing with the folder name (PONY folder, dinosaur photos)."""
    name = _words(" ".join(w for w in sku.lower().split("-") if w not in _NAME_NOISE))
    seen = set().union(*(_words(i) for i in items.values())) if items else set()
    return bool(name and seen) and not _related(name, seen)


def items_for(folder):
    pj = os.path.join(folder, "product.json")
    return (json.load(open(pj, encoding="utf-8")).get("photo_items") or {}) if os.path.exists(pj) else {}


if __name__ == "__main__":
    sys.exit(main())
