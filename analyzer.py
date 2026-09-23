#!/usr/bin/env python3
"""
Multi-photo product analyzer — local Qwen3-VL via Ollama.

Sends ALL of a product's photos together to a local vision model and returns a
validated ProductProfile (Pydantic), saved as product.json. Replaces the cloud
Gemini call: fully local, no API key, no quota.

    ollama pull qwen3-vl:8b            # once, on the Mac
    python analyzer.py input/SCOOTER-LED-PINK
    python analyzer.py --all           # every SKU under input/

Falls back to deterministic copy if Ollama is unavailable, so nothing crashes.
"""

import argparse
import json
import os
import sys
from typing import List

from pydantic import BaseModel, Field, ValidationError

OLLAMA_MODEL = os.environ.get("OLLAMA_VLM", "qwen3-vl:8b")
# product.json keys you can hand-edit; preserved on re-analysis (see fal_listing.py).
# The catalog block (product_name .. images_pipeline) is the store taxonomy and the sorting
# decisions — curated by hand and by store_taxonomy, never written by the vision model, so
# re-analysing a folder must not wipe it.
MANUAL_KEYS = ("title_override", "hero_photo", "lifestyle_photo", "lifestyle_scene", "slot_photos", "style",
               "photos", "photo_items", "photo_packaging",
               "product_name", "category", "sub", "handle", "vendor", "status", "printed_age",
               "occasions", "store_features", "gender", "variants", "merged_from",
               "not_a_variant_of", "decisions", "images_done", "images_pipeline",
               # shop data the copy writer must never touch: price, stock, supplier, the folder's own name
               "price_pkr", "stock", "compare_at_pkr", "supplier", "variants_off", "folder",
               # the stock code: the model names products after their folder, which is no longer the SKU
               "sku")
INPUT_DIR = "input"
ANALYZE_PX = 1024          # longest side sent to the model; enough to read box print
MAX_PHOTOS = 8             # a folder with 10 shots still fits the context window
VALID_EXTS = (".jpg", ".jpeg", ".png", ".webp")
ICONS = ["shield", "arrows", "wheel", "smiley"]     # icons the templates can draw


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
class Feature(BaseModel):
    icon: str = Field(description="one of: shield, arrows, wheel, smiley")
    label: str = Field(description="two short CAPS lines separated by \\n")


class ProductProfile(BaseModel):
    sku: str = ""
    name: str                       # short punchy name for the hero wordmark (CAPS)
    title: str                      # full marketplace product title
    tagline_top: str
    tagline_sub: str
    description: str                # 3-5 sentence marketplace description
    bullet_points: List[str]        # 5 selling points
    features: List[Feature]         # exactly 4, icons from ICONS
    whats_included: List[str]
    seo_title: str
    meta_description: str
    tags: List[str]
    alt_text: str
    info_title: str                 # heading for the feature graphic
    ribbon: str                     # short badge phrase
    callout: str                    # 2-3 word highlight
    detail_caption: str
    scene_prompts: List[str]        # 2 lifestyle background prompts


PROMPT = (
    "You are a factual product-listing writer for a children's toy store called "
    "The Toy Gift Shop. You are given MULTIPLE photos of ONE product (angles, "
    "packaging, close-ups). Study all of them together — read any text on the "
    "packaging — and produce complete listing content as JSON.\n\n"
    "Accuracy rules (most important — apply to every field):\n"
    "- Describe only what is visibly true: real materials, mechanism/function, "
    "included parts, and any age range or specs actually printed on the box.\n"
    "- Do NOT use unverifiable superlative or hype language: no 'amazing', 'best', "
    "'perfect', 'premium', 'incredible', 'ultimate', 'must-have'. Plain, concrete "
    "wording only.\n"
    "- Do NOT claim a certification, safety standard, material, or capability that "
    "isn't visibly printed or shown. If you aren't sure of a claim, omit it rather "
    "than guess.\n"
    "- Do not invent a brand name if none is visible.\n\n"
    "Fields:\n"
    "- name: short product name in CAPS (1-2 words) for a hero wordmark. It MUST "
    "correctly name the actual product type you see (e.g. SCOOTER, PLANE, PLUSH) "
    "— never mislabel it (a scooter is NOT a skateboard).\n"
    "- title: full, specific, factual marketplace product title.\n"
    "- tagline_top / tagline_sub: a plain two-line label (2-3 words each, in CAPS) "
    "naming the product/category — not a hype slogan.\n"
    "- description: 3-5 factual sentences on what it is, what it's made of, how it "
    "works, and what it's for. No invented benefits.\n"
    "- bullet_points: exactly 5 concrete, factual points (material, size cue, "
    "moving parts, accessories, intended use) — not generic praise.\n"
    "- features: EXACTLY 4, and every one must be a real selling point of THIS product: "
    "what it does, what it is made of, what is included, who it is for, or an age/size "
    "printed on the box. Each has 'label' (two short CAPS lines joined by \\n, a concrete "
    "factual attribute, e.g. 'HARD PLASTIC\\nBUILD' not 'AMAZING\\nQUALITY') and 'icon' "
    "chosen ONLY from: shield (safety/sturdy), arrows (adjustable/size), wheel "
    "(movement/smooth), smiley (fun/age). NEVER state the absence of something as a "
    "feature — no 'NO MOVEMENT', 'NO BATTERIES', 'NO SIZE ADJUSTMENT'. If the product is "
    "simple, repeat nothing and use its material, its size, what is in the pack, and its "
    "age guidance instead.\n"
    "- whats_included: what's in the box (from the packaging if visible).\n"
    "- seo_title (<=60 chars), meta_description (<=155 chars), tags (8-13 RELEVANT "
    "keywords only, no unrelated terms), alt_text (one factual descriptive sentence).\n"
    "- info_title: plain heading for a features graphic (e.g. 'FEATURES').\n"
    "- ribbon: a short factual badge phrase (CAPS, e.g. a real included-item count "
    "or age range); callout: a 2-3 word factual highlight (CAPS).\n"
    "- detail_caption: one factual sentence about the standout detail.\n"
    "- scene_prompts: 2 lifestyle BACKGROUND descriptions (a bright, relevant "
    "room/place for THIS product, NO people, NO text), each ending with "
    "'product photography, soft daylight, square, empty foreground surface'.\n"
    "Base everything only on what is visible."
)


# --------------------------------------------------------------------------- #
# Fallback (no Ollama)
# --------------------------------------------------------------------------- #
def _fallback(sku: str) -> ProductProfile:
    from process_products import sku_stem
    pretty = sku_stem(sku).replace("-", " ").title()
    return ProductProfile(
        sku=sku, name=sku_stem(sku).split("-")[0].upper(), title=pretty,
        tagline_top="BUILT FOR", tagline_sub="BIG SMILES!",
        description=f"The {pretty} is a fun, well-made toy kids will love.",
        bullet_points=[f"{pretty} — great gift", "Fun and durable",
                       "Bright, kid-friendly design", "Easy to use",
                       "Ages 3+"],
        features=[Feature(icon="shield", label="SAFE &\nSTURDY"),
                  Feature(icon="arrows", label="JUST THE\nRIGHT SIZE"),
                  Feature(icon="wheel", label="SMOOTH &\nRELIABLE"),
                  Feature(icon="smiley", label="HOURS OF\nFUN")],
        whats_included=["1x " + pretty],
        seo_title=pretty[:60], meta_description=f"Buy the {pretty} at The Toy Gift Shop."[:155],
        tags=["toy", "kids", "gift", "fun"], alt_text=f"{pretty} product photo.",
        info_title="WHY KIDS LOVE IT", ribbon="MADE TO LAST!", callout="KID FAVOURITE",
        detail_caption=f"A closer look at the {pretty}.",
        scene_prompts=[
            "bright modern children's playroom, product photography, soft daylight, square, empty foreground surface",
            "sunny living room with warm wood floor, product photography, soft daylight, square, empty foreground surface",
        ],
    )


def _normalize(data: dict, sku: str) -> dict:
    data["sku"] = sku
    feats = [f for f in data.get("features", []) if f.get("icon") in ICONS][:4]
    fb = _fallback(sku).features
    while len(feats) < 4:
        f = fb[len(feats)]
        feats.append({"icon": f.icon, "label": f.label})
    data["features"] = feats
    return data


# --------------------------------------------------------------------------- #
# Analyze
# --------------------------------------------------------------------------- #
def images_in(folder: str) -> List[str]:
    from process_products import photo_sort_key
    return sorted((os.path.join(folder, f) for f in os.listdir(folder)
                   if f.lower().endswith(VALID_EXTS)), key=photo_sort_key)


def analyze(sku: str, image_paths: List[str], use_ollama: bool = True, known_title: str = "",
            known_product: str = "", known_category: str = "", variants: dict | None = None) -> ProductProfile:
    if not (use_ollama and image_paths):
        return _fallback(sku)
    try:
        import ollama
        from photo_tags import _b64       # ~1 MP each: full phone photos overflow the context
        anchor = ""
        if known_product:
            anchor += (f"\n\nThe shop has identified this product as: \"{known_product}\""
                       + (f", filed under {known_category}" if known_category else "") + ". "
                       "That identification is correct — trust it over your reading of the photos. "
                       "It tells you WHAT THE ITEM IS: a squishy or toy version of something is a toy, "
                       "never the real thing (never describe it as food, or as a working appliance or device), "
                       "and every field must describe that toy.")
        if variants and variants.get("values"):
            anchor += (f"\n\nIt is sold in these {variants.get('option', 'variant')} options: "
                       + ", ".join(variants["values"]) + ". Some photos show different options of the SAME "
                       "product — write one listing that covers them, and never present an option as a separate item.")
        if known_title:
            anchor += (f"\n\nThe shop has confirmed this product's title: \"{known_title}\". "
                       "Use it as the title and keep every other field consistent with it.")
        resp = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": PROMPT + anchor,
                       "images": [_b64(p, ANALYZE_PX) for p in image_paths[:MAX_PHOTOS]]}],
            format=ProductProfile.model_json_schema(),   # structured output
            options={"temperature": 0.4,
                     "num_ctx": int(os.environ.get("OLLAMA_NUM_CTX", "8192"))},
        )
        data = _normalize(json.loads(resp["message"]["content"]), sku)
        return ProductProfile(**data)
    except (ImportError, ConnectionError) as exc:
        print(f"  [analyzer] Ollama unavailable ({exc}); using fallback", file=sys.stderr)
        return _fallback(sku)
    except (ValidationError, json.JSONDecodeError, KeyError) as exc:
        print(f"  [analyzer] bad model output for {sku} ({exc}); using fallback",
              file=sys.stderr)
        return _fallback(sku)
    except Exception as exc:  # network/model errors — keep the batch alive
        print(f"  [analyzer] error for {sku} ({exc}); using fallback", file=sys.stderr)
        return _fallback(sku)


def manual_overrides(product_json: str) -> dict:
    """Hand-edited keys in product.json that the model never writes."""
    if not os.path.exists(product_json):
        return {}
    raw = json.load(open(product_json, encoding="utf-8"))
    return {k: raw[k] for k in MANUAL_KEYS if raw.get(k)}


def analyze_folder(sku_folder: str, use_ollama: bool = True) -> ProductProfile:
    sku = os.path.basename(os.path.normpath(sku_folder))
    imgs = images_in(sku_folder)
    print(f"[{sku}] {len(imgs)} photo(s) -> {OLLAMA_MODEL if use_ollama else 'fallback'}")
    out = os.path.join(sku_folder, "product.json")
    manual = manual_overrides(out)
    profile = analyze(sku, imgs, use_ollama=use_ollama, known_title=manual.get("title_override", ""),
                      known_product=manual.get("product_name", ""),
                      known_category=" / ".join(x for x in (manual.get("category"), manual.get("sub")) if x),
                      variants=manual.get("variants"))
    if manual.get("title_override"):
        profile.title = manual["title_override"]
    data = {**json.loads(profile.model_dump_json()), **manual}
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"  -> {out}")
    return profile


def main():
    ap = argparse.ArgumentParser(description="Analyze product photos -> product.json (local Qwen3-VL).")
    ap.add_argument("folder", nargs="?", help="a single SKU folder (e.g. input/SCOOTER-LED-PINK)")
    ap.add_argument("--all", action="store_true", help="every SKU folder under input/")
    ap.add_argument("--no-ollama", action="store_true", help="skip the model; deterministic fallback")
    args = ap.parse_args()

    if args.all:
        folders = [os.path.join(INPUT_DIR, d) for d in sorted(os.listdir(INPUT_DIR))
                   if os.path.isdir(os.path.join(INPUT_DIR, d))]
    elif args.folder:
        folders = [args.folder]
    else:
        ap.error("give a SKU folder or --all")

    for f in folders:
        analyze_folder(f, use_ollama=not args.no_ollama)
    return 0


if __name__ == "__main__":
    sys.exit(main())
