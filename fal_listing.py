#!/usr/bin/env python3
"""
fal.ai Qwen-Image-Edit listing generator — the `--bg-provider fal` path.

fal renders the REAL product into each scene (keeps branding), so this uses a
product-in-scene slot recipe rather than the bare-background providers:
    CatalogHero, WhiteBG, Packshot, Detail, Lifestyle  +  FeatureCard (V2)
CatalogHero/Lifestyle/Detail also get a watermarked copy. Copy comes from
product.json (the analyzer). Needs FAL_KEY in the environment.

Existing slot PNGs are reused (no re-billing) — delete them to regenerate.
"""

import os
import urllib.request
from PIL import Image
import make_hero as mh
import feature_card as fc

SUF = (" Keep the product exactly the same — same shape, colors and printed "
       "branding. Square 1:1. No people. No added text or logos.")
SLOT_PROMPTS = {
    "CatalogHero": "Professional e-commerce hero shot of this product, centered on a "
                   "soft podium in a bright clean studio with a subtle warm gradient "
                   "background, premium product photography." + SUF,
    "WhiteBG": "This product isolated on a pure solid white background hex FFFFFF, even "
               "soft studio lighting, crisp e-commerce catalog packshot with a soft "
               "shadow beneath. Square 1:1. No people, no text.",
    "Packshot": "This product shown with its packaging or accessories on a clean light "
                "surface, soft studio lighting, e-commerce packshot. Keep everything "
                "exactly as in the photo. Square 1:1. No people, no added text.",
    "Detail": "Extreme close-up macro shot of this product highlighting its texture and "
              "branding details, shallow depth of field, soft studio lighting." + SUF,
    "Lifestyle": "This product in a warm, cozy, relevant real-life setting with soft "
                 "natural light and a softly blurred background, lifestyle product "
                 "photography." + SUF,
}
WATERMARK_SLOTS = ["CatalogHero", "Lifestyle", "Detail"]


def _square(path):
    im = Image.open(path).convert("RGB")
    s = max(im.size)
    c = Image.new("RGB", (s, s), (255, 255, 255))
    c.paste(im, ((s - im.width) // 2, (s - im.height) // 2))
    return c


def _fal_scene(ref_path, prompt, out_path):
    if os.path.exists(out_path):          # reuse — never re-bill
        return
    import fal_client
    tmp = out_path + ".in.jpg"
    _square(ref_path).save(tmp, quality=92)
    try:
        url = fal_client.upload_file(tmp)
    finally:
        os.remove(tmp)
    r = fal_client.subscribe("fal-ai/qwen-image-edit",
                             arguments={"image_url": url, "prompt": prompt,
                                        "image_size": "square_hd"})
    urllib.request.urlretrieve(r["images"][0]["url"], out_path)


def _content(profile):
    """Map an analyzer product.json profile -> FeatureCard V2 content."""
    feats = []
    for f in profile.get("features", [])[:4]:
        lines = f.get("label", "").split("\n")
        feats.append({"icon": f.get("icon", "smiley"), "title": lines[0],
                      "desc": lines[1].capitalize() if len(lines) > 1 else ""})
    return {
        "name": profile.get("name", ""),
        "headline_top": profile.get("tagline_top") or "MADE FOR",
        "headline_accent": profile.get("tagline_sub") or "YOU",
        "subhead": (profile.get("description", "") or "").split(". ")[0][:120],
        "features": feats,
    }


def build(sku, raws, profile, out_dir, ext="png"):
    if not raws:
        print(f"  ! {sku}: no photos", flush=True)
        return out_dir
    os.makedirs(out_dir, exist_ok=True)
    O = out_dir + "/"

    def ref(i):
        return raws[min(i, len(raws) - 1)]
    slot_ref = {"CatalogHero": ref(0), "WhiteBG": ref(0), "Packshot": ref(2),
                "Detail": ref(1), "Lifestyle": ref(0)}
    for slot, prompt in SLOT_PROMPTS.items():
        _fal_scene(slot_ref[slot], prompt, O + slot + ".png")
        print(f"  -> {slot}")

    # FeatureCard V2 (classic scene backdrop + verified copy + real thumbnails)
    thumbs = [{"photo": O + "CatalogHero.png", "crop": (0, 0, 1, 1), "caption": "CLASSIC LOOK"},
              {"photo": O + "Detail.png", "crop": (0, 0, 1, 1), "caption": "CLOSE-UP"},
              {"photo": O + "Lifestyle.png", "crop": (0, 0, 1, 1), "caption": "IN USE"},
              {"photo": O + "WhiteBG.png", "crop": (0, 0, 1, 1), "caption": "CLEAN LOOK"}]
    fc.render_v2(O + "WhiteBG.png", thumbs, _content(profile), O + "FeatureCard.png",
                 scene=O + "CatalogHero.png")
    print("  -> FeatureCard")

    # watermark the marketing shots (WhiteBG stays clean for the marketplace main)
    SIZE = mh.SIZE
    for n in WATERMARK_SLOTS:
        im = Image.open(O + n + ".png").convert("RGBA").resize((SIZE, SIZE))
        if os.path.exists(mh.LOGO_PATH):
            logo = Image.open(mh.LOGO_PATH).convert("RGBA")
            lw = int(SIZE * 0.14)
            logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
            m = int(SIZE * 0.03)
            im.alpha_composite(logo, (SIZE - lw - m, SIZE - logo.height - m))
        im.convert("RGB").save(O + n + "_wm.png", quality=94)
    return out_dir
