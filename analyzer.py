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
INPUT_DIR = "input"
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
    "You are an expert e-commerce creative director and copywriter for a "
    "children's toy store called The Toy Gift Shop. You are given MULTIPLE photos "
    "of ONE product (angles, packaging, close-ups). Study all of them together — "
    "read any text on the packaging — and produce complete listing content as JSON.\n\n"
    "Rules:\n"
    "- name: short punchy product name in CAPS (1-2 words) for a big hero wordmark.\n"
    "- title: full, specific marketplace product title.\n"
    "- tagline_top / tagline_sub: a two-line hook (2-3 words each).\n"
    "- description: 3-5 vivid sentences.\n"
    "- bullet_points: exactly 5 concise selling points.\n"
    "- features: EXACTLY 4. Each has 'label' (two short CAPS lines joined by \\n) and "
    "'icon' chosen ONLY from: shield (safety/sturdy), arrows (adjustable/size), "
    "wheel (movement/smooth), smiley (fun/age).\n"
    "- whats_included: what's in the box (from the packaging if visible).\n"
    "- seo_title (<=60 chars), meta_description (<=155 chars), tags (8-13 keywords), "
    "alt_text (one descriptive sentence).\n"
    "- info_title: heading for a features graphic (e.g. 'WHY KIDS LOVE IT').\n"
    "- ribbon: a short badge phrase; callout: a 2-3 word highlight.\n"
    "- detail_caption: one sentence about the standout detail.\n"
    "- scene_prompts: 2 lifestyle BACKGROUND descriptions (a bright, relevant "
    "room/place for THIS product, NO people, NO text), each ending with "
    "'product photography, soft daylight, square, empty foreground surface'.\n"
    "Base everything only on what is visible. Do not invent a brand name."
)


# --------------------------------------------------------------------------- #
# Fallback (no Ollama)
# --------------------------------------------------------------------------- #
def _fallback(sku: str) -> ProductProfile:
    pretty = sku.replace("-", " ").title()
    return ProductProfile(
        sku=sku, name=sku.split("-")[0].upper(), title=pretty,
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
    return sorted(os.path.join(folder, f) for f in os.listdir(folder)
                  if f.lower().endswith(VALID_EXTS))


def analyze(sku: str, image_paths: List[str], use_ollama: bool = True) -> ProductProfile:
    if not (use_ollama and image_paths):
        return _fallback(sku)
    try:
        import ollama
        resp = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": PROMPT, "images": image_paths}],
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


def analyze_folder(sku_folder: str, use_ollama: bool = True) -> ProductProfile:
    sku = os.path.basename(os.path.normpath(sku_folder))
    imgs = images_in(sku_folder)
    print(f"[{sku}] {len(imgs)} photo(s) -> {OLLAMA_MODEL if use_ollama else 'fallback'}")
    profile = analyze(sku, imgs, use_ollama=use_ollama)
    out = os.path.join(sku_folder, "product.json")
    with open(out, "w", encoding="utf-8") as f:
        f.write(profile.model_dump_json(indent=2))
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
