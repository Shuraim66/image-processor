#!/usr/bin/env python3
"""
Per-product marketing copy for the gallery slots.

build_content(sku, image_path) returns the dict make_hero/gallery expect:
    name, tagline_top, tagline_sub, features[4]{icon,label}, info_title,
    ribbon, callout, detail_caption, scene_prompts[2], theme(optional)

Uses the FREE Gemini text/vision model when a key is present; otherwise falls
back to deterministic copy derived from the SKU so the pipeline always runs.
"""

import io
import json
import os
from PIL import Image

GEMINI_MODEL = "gemini-3.6-flash"
ICONS = ["shield", "arrows", "wheel", "smiley"]   # icons make_hero can draw

_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "tagline_top": {"type": "string"},
        "tagline_sub": {"type": "string"},
        "info_title": {"type": "string"},
        "ribbon": {"type": "string"},
        "callout": {"type": "string"},
        "detail_caption": {"type": "string"},
        "features": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "icon": {"type": "string", "enum": ICONS},
                    "label": {"type": "string"},
                },
                "required": ["icon", "label"],
            },
        },
        "scene_prompts": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "tagline_top", "tagline_sub", "features",
                 "info_title", "ribbon", "callout", "detail_caption",
                 "scene_prompts"],
}

_PROMPT = (
    "You are an e-commerce creative director for a children's toy store. Look at "
    "this product photo and return JSON for a marketing image set:\n"
    "- name: a short, punchy product name in CAPS (1-2 words, e.g. 'SCOOTY').\n"
    "- tagline_top / tagline_sub: a two-line hook (2-3 words each).\n"
    "- features: EXACTLY 4 items. Each has 'label' (2 short lines separated by \\n, "
    "in CAPS) and 'icon' chosen ONLY from: shield (safety/sturdy), arrows "
    "(adjustable/size), wheel (movement/smooth), smiley (fun/age-suitable).\n"
    "- info_title: heading for a features graphic (e.g. 'WHY KIDS LOVE IT').\n"
    "- ribbon: a short badge phrase (e.g. 'BUILT FOR FUN, MADE TO LAST!').\n"
    "- callout: a 2-3 word highlight (e.g. 'LIGHTWEIGHT & PORTABLE').\n"
    "- detail_caption: one sentence about the standout detail.\n"
    "- scene_prompts: 2 background scene descriptions for lifestyle photos, each "
    "a bright, relevant room/place for THIS product, no people, no text. "
    "End each with 'product photography, soft daylight, square, empty foreground surface'.\n"
    "Base everything only on what is visible. Do not invent a brand name."
)


def _fallback(sku):
    from process_products import sku_stem
    pretty = sku_stem(sku).replace("-", " ").title()
    short = sku_stem(sku).split("-")[0].upper()
    return {
        "name": short,
        "tagline_top": "BUILT FOR",
        "tagline_sub": "BIG SMILES!",
        "info_title": "WHY KIDS LOVE IT",
        "ribbon": "MADE TO LAST!",
        "callout": "KID FAVOURITE",
        "detail_caption": f"A closer look at the {pretty}.",
        "features": [
            {"icon": "shield", "label": "SAFE &\nSTURDY"},
            {"icon": "arrows", "label": "JUST THE\nRIGHT SIZE"},
            {"icon": "wheel",  "label": "SMOOTH &\nRELIABLE"},
            {"icon": "smiley", "label": "HOURS OF\nFUN"},
        ],
        "scene_prompts": [
            "bright modern children's playroom, product photography, soft daylight, square, empty foreground surface",
            "sunny living room with warm wood floor, product photography, soft daylight, square, empty foreground surface",
        ],
    }


def build_content(sku, image_path, use_gemini=True):
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not (use_gemini and key):
        return _fallback(sku)
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        buf = io.BytesIO()
        Image.open(image_path).convert("RGB").save(buf, "JPEG", quality=88)
        part = types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[part, _PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=_SCHEMA),
        )
        data = json.loads(resp.text)
        feats = [f for f in data.get("features", []) if f.get("icon") in ICONS][:4]
        while len(feats) < 4:
            feats.append(_fallback(sku)["features"][len(feats)])
        data["features"] = feats
        return {**_fallback(sku), **data}       # fallback fills any gaps
    except Exception as exc:
        import sys
        print(f"  [content] Gemini failed for {sku} ({exc}); using fallback copy",
              file=sys.stderr)
        return _fallback(sku)
