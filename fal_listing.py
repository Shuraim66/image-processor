#!/usr/bin/env python3
"""
fal.ai image-edit listing generator — the `--bg-provider fal` path.

fal re-stages the REAL product photos into catalog images (keeps branding). Each
slot is made from the photo that suits it, chosen from the labels photo_tags.py
stores in product.json — so an opened case, a back view or the real box each get
their own image instead of the whole set re-using one photo:
    CatalogClean best photo of the product itself, on plain white (the Shopify main)
    CatalogHero  another angle if there is one, on a studio podium
    Angle        a further distinct view (back/side), on white     — if photographed
    Open         opened, with its real contents, on white          — if photographed
    Box          the real retail packaging, on white               — if photographed
    Detail       a real close-up                                   — if photographed
    Lifestyle    the product where it's actually used (lifestyle_scene)
  + FeatureCard (thumbnails = the extra views) + Hero_titled, rendered locally.
Marketing shots also get a watermarked copy. Copy comes from product.json.
Needs FAL_KEY in the environment.

Every slot only re-stages what is in its photo — no invented packaging,
accessories or parts (the old Packshot slot did exactly that, so it's gone).

Optional hand-edited keys in product.json (kept across --reanalyze):
    "hero_photo": "angle2.jpeg"      photo to use as the main reference
    "lifestyle_scene": "on a ..."    overrides the automatic Lifestyle setting
    "slot_photos": {"Open": "angle4.jpeg"}   pin any slot to a specific photo
    "photos": {"angle4.jpeg": "product_angle", ...}   fix a wrong photo label

Existing slot PNGs are reused (no re-billing) — delete them to regenerate.
Preview which photo each slot will use (free):  python fal_listing.py --plan --sku <SKU>
"""

import argparse
import functools
import json
import math
import os
import re
import time
import httpx
from PIL import Image, ImageFilter, ImageOps
import brand
import make_hero as mh
import feature_card as fc
import process_products as pp

# Fidelity rules from the store's image spec: re-photograph the real product, never redesign it.
FIDELITY = (" The product must stay exactly as in the reference photos: same shape, proportions, "
            "colors and colour placement, materials, surface finish, visible components, buttons, "
            "switches, wheels, handles, seams, logos and printed markings, and the same number of "
            "pieces. Never invent buttons, switches, accessories, controls, batteries, ports, "
            "screens, lights, LEDs, remote controls or any feature that is not visible in the "
            "photos, and never add objects, packaging or props that are not there. If a detail is "
            "unclear, keep it as the photo shows it. Generate exactly one image, square 1:1, "
            "no people, no added text, captions or logos.")
STUDIO = " Realistic soft shadow under the product, accurate perspective, professional studio lighting."

# Everything in a reference photo is not one object. A wall-climbing RC toy is photographed
# beside its handheld controller, a bubble machine beside its bottle of solution — and the old
# Lifestyle prompt put BOTH on the wall. Each object has to sit where that object really sits.
PHYSICS = (" Treat the reference photo as a group of separate real objects, not one fused object. "
           "The main product is the subject and is placed as the scene describes. Every other "
           "object visible with it — a handheld remote control or controller, a bottle of liquid, "
           "a charger, cable, lanyard, stand, spare parts, accessories or the packaging — must rest "
           "where that kind of object really rests: on the nearest flat surface such as a table, "
           "desk, shelf or floor, upright and supported. Never mount, stick, float, tilt or attach "
           "an accessory to a wall, a window or mid-air, never repeat the main product, and never "
           "show anything balancing in a way that would fall over. Keep every object's real-world "
           "size relative to the others and to the room.")

# The call sends several photos of the same product (MAX_REFS). Without being told, the model
# reads them as one pool and re-shoots whatever view is most common — the GT-R's rear-view
# "Angle" came back as another front three-quarter. So the view-specific slots have to name
# which image defines the camera, and demote the rest to identity evidence.
REF_ROLE = (" IMPORTANT: the FIRST reference image defines the camera: reproduce its viewpoint, "
            "the side of the product facing the camera, and which parts are open, closed or "
            "visible. The other reference images are supplied only as evidence of the same "
            "product's colours, markings and construction — never copy their camera angle, "
            "their framing or the state they show the product in.")

PHOTOSHOOT = (
    " Re-photograph this exact object as a professional product photographer would in a studio, "
    "replacing the phone snapshot's lighting entirely: a large soft key light from the front "
    "upper left with gentle fill from the right, no bare-flash hotspot, no blown-out white "
    "patches and no dark muddy shadows on the product. Neutral white balance — greys read "
    "neutral grey and whites read white, with the phone photo's blue, green or yellow cast "
    "removed. Crisp focus across the whole object, true edges, and the real material read: "
    "plastic looks like plastic, metal like metal, fabric like fabric, glossy surfaces keep "
    "clean soft reflections rather than glare. The object fills about 85 percent of the frame, "
    "centred, upright and level, with a soft realistic contact shadow directly beneath it."
)

# v2, replacing the old CatalogHero formula (PHOTOSHOOT + REF_ROLE + FIDELITY) after the 3D Pen
# test: that version let the model treat a packaging logo (tuosigu, printed on the box) as
# layout material and promote it into a top-left store-logo position. This version keeps the
# product/packaging/branding distinction explicit, adds a priority order for conflicting
# evidence across multiple reference photos, and states outright that a packaging illustration
# of a product is not photographic evidence that the physical item is included.
CATALOG_HERO_V2 = """CATALOG HERO — PRIMARY SHOPIFY PRODUCT IMAGE

Create ONE premium, highly presentable e-commerce hero image for this product using ALL attached reference photos.

The reference photos are the SOURCE OF TRUTH for the real physical product and everything physically included with it.

The goal is:

PRESERVE THE REAL PRODUCT.
IMPROVE THE PRESENTATION.

--------------------------------------------------
1. PRODUCT FIDELITY
--------------------------------------------------

Preserve the actual physical product shown in the reference images.

Keep accurate:
- shape
- proportions
- colors
- color placement
- materials
- surface finish
- physical details
- buttons
- switches
- wheels
- handles
- joints
- seams
- printed markings
- stickers
- decals
- logos
- included pieces
- packaging
- wrappers
- trays
- accessories
- quantity/configuration

Do not redesign the product.

Do not make the product look more advanced, expensive, futuristic, detailed, colorful, metallic, oversized, or premium than the real item.

Do not add physical features or components that are not supported by the reference photos or verified product information.

--------------------------------------------------
2. PRODUCTS INSIDE BOXES / WRAPPERS / PACKAGING
--------------------------------------------------

Some reference photos may show the product:
- inside a cardboard box
- inside a transparent plastic tray
- inside a blister pack
- inside a plastic bag
- wrapped in film
- partially covered by packaging
- surrounded by accessories inside the package

When the actual physical product is visibly identifiable, you MAY present that same real product outside or partially outside the packaging for a better hero composition.

For example:
- remove a visible toy from a transparent tray
- arrange visible accessories neatly beside the main product
- place the visible toy beside its box
- show the actual contents as a professional product presentation

However:

DO NOT invent hidden parts.

DO NOT reconstruct unseen components from imagination.

DO NOT assume that an item shown only in package artwork is physically included unless the references or verified product information establish this.

If the real product is visible through packaging, preserve its actual appearance.

If only the packaging artwork shows a product but the physical product cannot be seen, treat the artwork as packaging artwork, NOT as photographic evidence of the physical product.

--------------------------------------------------
3. PACKAGING
--------------------------------------------------

Packaging may be shown prominently when it helps communicate what is being sold.

Preserve the real packaging design, colors, graphics, age markings, logos and printed information.

Do not redesign the packaging.

Do not move packaging logos into other parts of the composition.

A logo or brand name printed on the real packaging must stay naturally associated with that packaging.

NEVER place a packaging logo:
- in the top-left corner
- in the top-right corner
- as a floating logo
- as a watermark
- as a separate header
- as a decorative badge

unless explicitly requested.

Do not invent a store logo or add "The Toy Gift Shop" branding unless explicitly requested.

--------------------------------------------------
4. CREATIVE PRESENTATION
--------------------------------------------------

AI HAS CREATIVE FREEDOM TO IMPROVE THE PRESENTATION.

You may creatively improve:
- product positioning
- camera angle
- perspective
- composition
- background
- environment
- lighting
- shadows
- reflections
- depth of field
- scale within the frame
- arrangement of visible accessories
- visual hierarchy
- close-up detail panels

Choose a visual setting that naturally suits the specific toy.

Do not force every product into the same background or layout.

--------------------------------------------------
5. THIS IS A PHOTOGRAPH, NOT A GRAPHIC DESIGN
--------------------------------------------------

This image is photography only.

Do not add a headline, product-name text, feature callouts, slogans, icons, badges, or any other typography or graphic text element to the image.

Do not compose a mini-infographic, feature card, or marketing layout.

The product name, feature callouts and other marketing text are added separately afterwards by the store's own template, from verified product data. This image must not pre-empt or duplicate that.

The only text that may appear anywhere in the image is text that is physically printed on the real product or its real packaging, reproduced exactly as it is photographed -- never redrawn, resized, recolored, or moved.

If a close-up detail inset is used, it must show a real, photographed detail of the product -- not an added caption or label.

--------------------------------------------------
6. TEXT AND BRANDING
--------------------------------------------------

Do not automatically add branding.

Do not treat a manufacturer's logo as the store's branding.

Do not create a floating company logo from packaging artwork.

Do not invent slogans or marketing claims.

Do not add any text of your own anywhere in the image.

--------------------------------------------------
7. VISUAL STYLE
--------------------------------------------------

The result should look like a premium commercial product image used by a professional toy e-commerce store.

It should be:
- attractive
- polished
- modern
- clean
- engaging
- easy to understand
- suitable for Shopify
- credible as a representation of the real product

The main physical product must remain the dominant visual subject.

--------------------------------------------------
8. MOST IMPORTANT RULE
--------------------------------------------------

CREATIVE FREEDOM APPLIES TO PRESENTATION,
NOT TO THE PRODUCT.

Think:

"Professionally photograph and present this exact product and its actual visible contents."

NOT:

"Design a new version of this product."

When uncertain:

DO NOT INVENT.
Use the reference photos as the truth.

--------------------------------------------------
9. OUTPUT
--------------------------------------------------

Generate EXACTLY ONE final image.

Do not create multiple variants.
Do not create alternative concepts.
Do not create a collage of different versions.

The final result should be one polished PRIMARY SHOPIFY PRODUCT IMAGE.

--------------------------------------------------
10. REFERENCE PRIORITY
--------------------------------------------------

When determining what the actual product looks like, use this priority:

1. Clear photographs of the actual physical product
2. Multiple photographs showing the same physical product
3. Actual accessories/components visibly shown in photographs
4. Packaging photographs
5. Product artwork/illustrations printed on packaging

Never use packaging artwork to override a clear photograph of the real product."""

# One image per mode (the store's /CatalogHero, /CatalogClean, /FeatureProduct, /Lifestyle).
# The extra catalog views re-photograph a specific real view (opened, packaging, another angle).
SLOT_PROMPTS = {
    "CatalogHero": CATALOG_HERO_V2,
    "CatalogClean": "Standard catalog photograph of this exact product on a plain pure white "
                    "background hex FFFFFF, simple centred composition, even studio lighting, no "
                    "lifestyle environment and no decorative objects." + STUDIO + REF_ROLE + FIDELITY,
    "Angle": "Catalog photograph of this exact product seen from the same viewing angle as the "
             "first reference image, on a plain pure white background hex FFFFFF, simple "
             "composition." + STUDIO + REF_ROLE + FIDELITY,
    "Open": "Catalog photograph of this exact product opened exactly as in the first reference "
            "image, with every included item in its place and nothing added, removed or "
            "rearranged, on a plain pure white background hex FFFFFF." + STUDIO + REF_ROLE + FIDELITY,
    "Box": "Catalog photograph of this exact product and/or its real retail packaging exactly as in "
           "the first reference image, on a plain pure white background hex FFFFFF, with all printed "
           "artwork and text on the packaging unchanged." + STUDIO + REF_ROLE + FIDELITY,
    "Detail": "Close-up catalog photograph framed as in the first reference image, showing the real "
              "texture and printed details of this exact product, shallow depth of "
              "field." + STUDIO + REF_ROLE + FIDELITY,
    "FeatureProduct": "Premium feature photograph of this exact product as the clear main subject, "
                      "with a more creative background, dramatic but natural lighting and a sense of "
                      "depth. The presentation may be striking; the product itself may not change."
                      + PHYSICS + FIDELITY,
    "Lifestyle": "Realistic commercial lifestyle photograph: this exact product {scene}. Natural "
                 "daylight, softly blurred background, realistic real-world scale, the product "
                 "placed naturally and never operating, glowing or transforming." + PHYSICS + FIDELITY,
}
WATERMARK_SLOTS = ["CatalogHero", "Angle", "Open", "Box", "Detail", "FeatureProduct", "Lifestyle"]
SLOT_ORDER = ["CatalogClean", "CatalogHero", "Angle", "Open", "Box", "Detail", "FeatureProduct", "Lifestyle"]
# Only these go to fal. A white-background view is background removal, not generation, so
# CatalogClean / Angle / Open / Box / Detail are cut out locally with rembg for free — and
# CatalogClean is cut from the studio CatalogHero, so it carries the re-shot lighting.
PAID_SLOTS = ("CatalogHero", "Lifestyle", "FeatureProduct")


def paid(slots):
    return [s for s in slots if s in PAID_SLOTS]
# FeatureCard thumbnails: the most informative views first
THUMB_CAPTIONS = {"Open": "OPENED", "Angle": "ANOTHER VIEW", "Box": "PACKAGING",
                  "Lifestyle": "IN USE", "Detail": "CLOSE-UP", "CatalogHero": "STUDIO",
                  "CatalogClean": "ON WHITE"}
# how many reference photos of the same product to send with each generation (the spec allows 2-8)
MAX_REFS = 3
USAGE_FILE = "_fal_usage.json"   # what each call reported back (token counts where the model gives them)
# the AI feature image is optional: the locally drawn FeatureCard is free and its text is exact
FEATURE_PRODUCT_ALL = False
MAIN_VIEWS = ["product_front", "product_angle", "product_back", "product_with_box", "product_open", "box_front"]

# Where each kind of product is really used — first match on SKU + title wins.
# (We can't put an RC car on a side table or a wall climber on a shelf.)
LIFESTYLE_SCENES = [
    (r"wall ?climb|wall ?rally|spider ?(car|climb)|climbing car",
     "clinging to a smooth, light-painted wall in a child's bedroom"),
    (r"drone|quadcopter|four ?axis|4 ?axis", "standing on the short grass of a sunny park, ready for take-off"),
    (r"\brc\b|remote control car|stunt car", "driving on a smooth paved path in a sunny park"),
    (r"die ?cast|model car|collectible|figure|figurine|naruto|ronaldo",
     "on a display shelf in a softly lit bedroom"),
    (r"scooter|bike|bicycle|tricycle|ride ?on", "standing on a sunny park footpath beside green grass"),
    (r"plane|jet|glider|catapult", "on the green lawn of a sunny backyard"),
    (r"bath|rubber ?duck|bath ?duck|water ?wheel", "floating in a bathtub filled with water in a bright bathroom"),
    (r"pool|water gun|blaster|beach|sand", "beside a paddling pool on a sunny patio"),
    (r"bubble", "on a garden table in a sunny backyard"),
    (r"makeup|cosmetic|vanity|beauty|nail|princess ?bag|lipstick",
     "on a white children's dressing table with a mirror in a pastel bedroom"),
    (r"tablet|laptop|learning|educat|book|\bstem\b|science|slime|experiment|abacus|clock|"
     r"marker|crayon|colou?ring|drawing|\bart\b|art ?set|palette|craft|\bpaint(ing)?\b",
     "on a child's study desk in a bright bedroom"),
    (r"squish|fidget", "on a pastel study desk in a bright kid's bedroom"),
    (r"\bcase\b|briefcase|lock ?box|jewel|magic ?wand", "on a white children's dressing table in a pastel bedroom"),
    (r"plush|stuffed|teddy", "sitting on a neatly made child's bed with soft pillows"),
    (r"basketball|baseball|bowling|football", "on a living-room rug in a bright family home"),
    (r"board ?game|dice|ludo|chess|marble|game set|catching", "on a wooden coffee table in a bright family living room"),
    (r"arcade|handheld|console|walkie|card ?machine|vending|keychain|camera|binocular|telescope",
     "on a child's bedroom desk in soft daylight"),
    (r"visor|fan hat|sun hat|neck fan|handheld fan|mini fan", "resting on a garden table on a bright, sunny summer patio"),
    (r"tumbler|water bottle|mug|flask|straw", "on a light oak desk in a bright home office"),
    (r"piano|xylophone|keyboard|drum|musical|busy ?board|busyboard|montessori|stacker|"
     r"baby|toddler|activity|rattle|pull ?along|caterpillar",
     "on a soft foam play mat on a bright nursery floor"),
    (r"kitchen|mixer|chef|cook", "on a child-sized play kitchen counter in a bright playroom"),
    (r"tool|drill|saw|screw", "on a child's wooden workbench in a bright playroom"),
    (r"cleaning|mop|vacuum|broom", "on a light wooden floor in a bright home hallway"),
    (r"\bcar\b|truck|vehicle|tractor|train|robot|dinosaur|animal|walking|dancing",
     "on a light wooden floor in a bright playroom"),
]
DEFAULT_SCENE = "on a light wooden floor in a bright, tidy playroom"


def lifestyle_scene(sku, profile):
    if profile.get("lifestyle_scene"):
        return profile["lifestyle_scene"]
    # hyphens -> spaces so SKU words match on their own (patterns use "die ?cast")
    text = " ".join((sku, profile.get("title", ""), profile.get("name", ""),
                     profile.get("product_name", ""))).lower().replace("-", " ")
    for pattern, scene in LIFESTYLE_SCENES:
        if re.search(pattern, text):
            return scene
    return DEFAULT_SCENE


# fal image-edit models, picked with --fal-model or FAL_IMAGE_MODEL. usd = price of one
# 1024x1024 edit from fal's pricing (2026-09-15); each endpoint names its inputs differently.
FAL_MODELS = {
    "qwen-image-edit": {
        "endpoint": "fal-ai/qwen-image-edit", "usd": 0.03,
        "args": lambda url, prompt: {"image_url": url, "prompt": prompt, "image_size": "square_hd"}},
    "qwen-image-edit-2511": {
        "endpoint": "fal-ai/qwen-image-edit-2511", "usd": 0.03,
        "args": lambda url, prompt: {"image_urls": [url], "prompt": prompt, "image_size": "square_hd"}},
    "muse-image": {
        "endpoint": "meta/muse-image/edit", "usd": 0.01,
        "args": lambda url, prompt: {"image_urls": [url], "prompt": prompt, "aspect_ratio": "1:1",
                                     "output_format": "png"}},
    # token-billed: longer prompts cost more, so this is fal's list price, not a guarantee.
    # quality must be explicit — the endpoint defaults to "high" (~4x the price)
    "gpt-image-2.5-sunburst-medium": {
        "endpoint": "openai/gpt-image-2.5/sunburst/edit", "usd": 0.0515,
        "args": lambda url, prompt: {"image_urls": [url], "prompt": prompt, "quality": "medium",
                                     "image_size": "square_hd", "output_format": "png"}},
}
FAL_MODEL = os.environ.get("FAL_IMAGE_MODEL", "gpt-image-2.5-sunburst-medium")
MAX_UPLOAD = 1536   # px; phone photos are ~16 MP squared — slower uploads, and some models bill input MP

fal_calls = 0    # billed generations this process — counted even if the download then fails
fal_cost = 0.0   # their list-price total in USD


def _square(path):
    im = Image.open(path).convert("RGB")
    s = max(im.size)
    c = Image.new("RGB", (s, s), (255, 255, 255))
    c.paste(im, ((s - im.width) // 2, (s - im.height) // 2))
    return c.resize((MAX_UPLOAD, MAX_UPLOAD), Image.LANCZOS) if s > MAX_UPLOAD else c


def _fal_scene(ref_path, prompt, out_path, model=None, refs=()):
    """refs: extra photos of the SAME product, so the model keeps one visual identity."""
    if os.path.exists(out_path):          # reuse — never re-bill
        return None
    import fal_client
    spec = FAL_MODELS[model or FAL_MODEL]
    urls = []
    for i, src in enumerate([ref_path] + [r for r in refs if r != ref_path][:MAX_REFS - 1]):
        tmp = f"{out_path}.in{i}.jpg"
        _square(src).save(tmp, quality=92)
        try:
            urls.append(fal_client.upload_file(tmp))
        finally:
            os.remove(tmp)
    url = urls[0]
    global fal_calls, fal_cost
    args = spec["args"](url, prompt)
    if "image_urls" in args and len(urls) > 1:      # models that take several references
        args["image_urls"] = urls
    r = fal_client.subscribe(spec["endpoint"], arguments=args)
    fal_calls += 1
    fal_cost += spec["usd"]                      # list price; the real charge is token-billed
    # Keep whatever the endpoint reports about the call (usage/token counts on token-billed
    # models) next to the image, so the cost of e.g. more reference photos can be measured
    # instead of guessed. fal_cost stays the list-price estimate.
    try:
        meta = {k: v for k, v in r.items() if k != "images"}
        meta["references"] = len(urls)
        meta["prompt_chars"] = len(prompt)
        log = os.path.join(os.path.dirname(out_path), USAGE_FILE)
        seen = json.load(open(log, encoding="utf-8")) if os.path.exists(log) else {}
        seen[os.path.basename(out_path)] = meta
        with open(log, "w", encoding="utf-8") as f:
            json.dump(seen, f, indent=2, default=str)
    except Exception:                            # never lose a billed image to bookkeeping
        pass
    # httpx (certifi CAs), not urllib: python.org builds ship no CA store, so urllib
    # fails TLS and the already-billed image would be lost.
    # v3b.fal.media round-robins several edge IPs; some reset the TLS handshake under
    # load while others serve fine (confirmed 2026-09-23: a batch run lost 6 billed
    # images this way, all recovered afterwards by simply retrying with a pause).
    # No delay + only 3 tries was not enough -- back off and try considerably longer
    # before giving up on an image that has already been paid for.
    img_url = r["images"][0]["url"]
    last_exc = None
    for attempt in range(8):
        try:
            resp = httpx.get(img_url, timeout=120, follow_redirects=True)
            resp.raise_for_status()
            break
        except httpx.HTTPError as exc:
            last_exc = exc
            time.sleep(min(2 * (attempt + 1), 15))
    else:
        raise RuntimeError(f"{os.path.basename(out_path)}: download failed after 8 tries "
                           f"({last_exc}); billed result at {img_url} -- it is NOT lost, "
                           f"retry the download (e.g. curl -o <path> '{img_url}')") from last_exc
    with open(out_path, "wb") as f:
        f.write(resp.content)
    return r


def _first_sentence(text, limit=150):
    """One whole sentence for the card subhead — never a phrase cut mid-word."""
    first = text.split(". ")[0].strip()
    if len(first) > limit:
        first = first[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    return first.rstrip(".") + "." if first else ""


def _content(profile):
    """Map an analyzer product.json profile -> FeatureCard V2 content."""
    feats = []
    for f in profile.get("features", [])[:4]:
        if not isinstance(f, dict):
            continue  # legacy product.json: "features" is the store's plain tag list (e.g. ["new"]), not icon/label dicts
        lines = [l.strip() for l in f.get("label", "").split("\n") if l.strip()]
        title, desc = (lines + ["", ""])[:2]
        # "DANCES &" / "WIGGLES" reads as two half-phrases on the card: join them up.
        if title.endswith(("&", "AND", "OR", "-")) or len(desc.split()) < 2:
            title, desc = (title + " " + desc).strip(), ""
        feats.append({"icon": f.get("icon", "smiley"), "title": title, "desc": desc})
    return {
        "eyebrow": profile.get("tagline_top", ""),
        "title": profile.get("title_override") or profile.get("title") or profile.get("name", ""),
        "subhead": _first_sentence(profile.get("description", "") or ""),
        "features": feats,
    }


@functools.lru_cache(maxsize=None)
def _thumb_vector(path, n=48):
    """Normalised 48x48 greyscale of the centre square — for comparing framing, not content."""
    im = ImageOps.exif_transpose(Image.open(path)).convert("L")
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2)).resize((n, n), Image.LANCZOS)
    px = list(im.filter(ImageFilter.GaussianBlur(1)).tobytes())
    mean = sum(px) / len(px)
    sd = math.sqrt(sum((x - mean) ** 2 for x in px) / len(px)) or 1.0
    return w > h, tuple((x - mean) / sd for x in px)


def _near_duplicate(a, b, min_corr=0.80):
    """Two shots of the same view (phones often take a pair) — don't spend a slot on both.
    Measured on real shoots: a repeated shot ~0.84, front vs back of a product ~0.71."""
    (land_a, va), (land_b, vb) = _thumb_vector(a), _thumb_vector(b)
    return land_a == land_b and sum(x * y for x, y in zip(va, vb)) / len(va) >= min_corr


PRODUCT_ONLY_VIEWS = ["product_front", "product_angle", "product_back"]
SOURCES_FILE = "slot_sources.json"   # {slot: photo file} for every generated image


ALWAYS_KEEP = ("CatalogHero", "CatalogClean", "Lifestyle")


def drop_duplicate_views(plan):
    """Remove slots whose source photo repeats one already planned — a second paid image of
    the same view is waste, not coverage."""
    kept, taken = {}, []
    for slot in SLOT_ORDER:
        photo = plan.get(slot)
        if photo is None:
            continue
        if slot in ALWAYS_KEEP:
            kept[slot] = photo
            if photo not in taken:
                taken.append(photo)
            continue
        if photo in taken or any(_near_duplicate(photo, t) for t in taken):
            continue
        kept[slot] = photo
        taken.append(photo)
    return kept


def plan_slots(raws, profile):
    """{slot: photo path} — which real photo each catalog image is re-staged from.

    CatalogClean and CatalogHero prefer a photo of the product with no packaging in it.
    Lifestyle REQUIRES one (a box or sleeve in a lifestyle scene looks wrong) and is
    left out when the shoot has none; a photo whose packaging wasn't checked counts
    as packaged. Packaged shots of the product go to the Box slot instead."""
    by_name = {os.path.basename(p): p for p in raws}
    tags = {n: v for n, v in (profile.get("photos") or {}).items() if n in by_name}
    packed = profile.get("photo_packaging") or {}
    used = []

    def tag(p):
        return tags.get(os.path.basename(p))

    def unpackaged(p):
        return packed.get(os.path.basename(p)) is False

    def pick(views, unpackaged_only=False, packaged_only=False, reuse=False):
        for view in views:
            for p in raws:                      # photo order: front, angle2, angle3...
                if tag(p) != view or (unpackaged_only and not unpackaged(p)) or \
                        (packaged_only and unpackaged(p)):
                    continue
                # a repeated shot carries the same label; same framing with doors open doesn't
                if not reuse and (p in used or any(tag(u) == view and _near_duplicate(p, u) for u in used)):
                    continue
                if p not in used:
                    used.append(p)
                return p
        return None

    main = by_name.get(profile.get("hero_photo") or "") or \
        pick(PRODUCT_ONLY_VIEWS, unpackaged_only=True) or pick(["product_open"], unpackaged_only=True) \
        or pick(MAIN_VIEWS) or raws[0]
    if main not in used:
        used.append(main)
    plan = {"CatalogClean": main,
            "CatalogHero": main}
    photo = pick(["product_open"], unpackaged_only=True) or pick(["product_open"])   # fullest view first
    if photo:
        plan["Open"] = photo
    photo = pick(["product_with_box", "box_front"]) or pick(PRODUCT_ONLY_VIEWS, packaged_only=True) \
        or pick(["box_back"])
    if photo:
        plan["Box"] = photo
    angle_views = ["product_back", "product_angle", "product_front"]
    photo = pick(angle_views, unpackaged_only=True) or pick(angle_views)
    if photo:
        plan["Angle"] = photo
    photo = pick(["closeup"])
    if photo:
        plan["Detail"] = photo
    life = by_name.get(profile.get("lifestyle_photo") or "")
    if not life:
        life = main if (tag(main) in PRODUCT_ONLY_VIEWS + ["product_open"] and unpackaged(main)) else \
            pick(PRODUCT_ONLY_VIEWS, unpackaged_only=True, reuse=True)
    if FEATURE_PRODUCT_ALL or profile.get("feature_product"):
        plan["FeatureProduct"] = main
    if life:
        plan["Lifestyle"] = life
    for slot, name in (profile.get("slot_photos") or {}).items():   # hand-pinned after review
        if slot in SLOT_PROMPTS and name in by_name:
            plan[slot] = by_name[name]
    return drop_duplicate_views({slot: plan[slot] for slot in SLOT_ORDER if slot in plan})


def plan_warnings(plan, profile):
    """Things a person should look at before approving a product for fal."""
    packed = profile.get("photo_packaging") or {}
    notes = []
    if "Lifestyle" not in plan:
        notes.append("No photo of the product without packaging — Lifestyle image skipped")
    if packed.get(os.path.basename(plan["CatalogClean"])) is not False:
        notes.append("Main image photo shows packaging")
    return notes


def recorded_sources(out_dir):
    path = os.path.join(out_dir, SOURCES_FILE)
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}


def slots_to_generate(plan, out_dir):
    """Slots with no image yet. A free (local) slot is also remade when it was cut from a
    different photo than planned. A PAID slot that already has an image is never remade
    automatically: the planner's choice of photo can change between versions, and that
    must not silently re-bill an image already bought. Delete the PNG to remake it."""
    sources = recorded_sources(out_dir)
    todo = []
    for slot, photo in plan.items():
        if not os.path.exists(os.path.join(out_dir, slot + ".png")):
            todo.append(slot)
        elif slot not in PAID_SLOTS and sources.get(slot, os.path.basename(photo)) != os.path.basename(photo):
            todo.append(slot)
    return todo


def build(sku, raws, profile, out_dir, ext="png"):
    if not raws:
        print(f"  ! {sku}: no photos", flush=True)
        return out_dir
    os.makedirs(out_dir, exist_ok=True)
    O = out_dir + "/"

    plan = plan_slots(raws, profile)
    scene = lifestyle_scene(sku, profile)
    todo = set(slots_to_generate(plan, out_dir))
    sources = recorded_sources(out_dir)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    others = list(dict.fromkeys(plan.values()))
    for slot, photo in sorted(plan.items(), key=lambda kv: kv[0] not in PAID_SLOTS):
        png = O + slot + ".png"
        if slot in todo and os.path.exists(png):      # made from another photo: keep it aside
            os.makedirs(O + "_replaced", exist_ok=True)
            os.replace(png, f"{O}_replaced/{slot}-{stamp}.png")
        if slot in PAID_SLOTS:
            _fal_scene(photo, SLOT_PROMPTS[slot].format(scene=scene), png, refs=others)
        elif not os.path.exists(png):
            src = O + "CatalogHero.png" if slot == "CatalogClean" and os.path.exists(O + "CatalogHero.png") else photo
            pp.process_image(src, None).save(png)
        sources[slot] = os.path.basename(photo)
        with open(O + SOURCES_FILE, "w", encoding="utf-8") as f:
            json.dump(sources, f, indent=2)
        print(f"  -> {slot} ({os.path.basename(photo)}) {'fal' if slot in PAID_SLOTS else 'local'}"
              + (f" {scene}" if slot == "Lifestyle" else ""))
    for stale in [s for s in SLOT_ORDER if s not in plan and os.path.exists(O + s + ".png")]:
        os.makedirs(O + "_replaced", exist_ok=True)     # e.g. an old Lifestyle made from a box shot
        os.replace(O + stale + ".png", f"{O}_replaced/{stale}-{stamp}.png")
        sources.pop(stale, None)
        with open(O + SOURCES_FILE, "w", encoding="utf-8") as f:
            json.dump(sources, f, indent=2)

    # FeatureCard V2 (brand catalog layout + verified copy + real thumbnails)
    hero = O + "CatalogHero.png" if os.path.exists(O + "CatalogHero.png") else O + "CatalogClean.png"
    thumbs = [{"photo": O + slot + ".png", "crop": (0, 0, 1, 1), "caption": cap}
              for slot, cap in THUMB_CAPTIONS.items() if slot in plan and slot != "CatalogHero"][:4]
    fc.render_v2(hero, thumbs, _content(profile), O + "FeatureCard.png")
    print("  -> FeatureCard")

    # Titled hero (store-style: eyebrow + big title + subhead + badge)
    fc.render_hero_title(hero,
                         {"eyebrow": profile.get("tagline_top", ""),
                          "title": profile.get("name") or sku,
                          "subhead2": profile.get("tagline_sub", ""),
                          "badge": "TOY GIFT"},
                         O + "Hero_titled.png")
    print("  -> Hero_titled")

    # brand the marketing shots: faint tiled wordmark + navy address chip + corner logo
    # (CatalogClean stays clean for the marketplace main -- Google/Meta Shopping feeds
    # reject a watermarked main image, per brand.py's own docstring)
    SIZE = mh.SIZE
    for n in (slot for slot in WATERMARK_SLOTS if slot in plan):
        im = Image.open(O + n + ".png").convert("RGBA").resize((SIZE, SIZE))
        brand.tile_wordmark(im)
        brand.chip(im)
        brand.corner_logo(im)
        im.convert("RGB").save(O + n + "_wm.png", quality=94)
    return out_dir


def main():
    import analyzer
    import process_products as pp
    ap = argparse.ArgumentParser(description="Preview the photo chosen for each fal slot (free).")
    ap.add_argument("--plan", action="store_true", required=True)
    ap.add_argument("--sku", action="append", help="product folder; repeatable (default: all)")
    args = ap.parse_args()
    total = 0
    for sku in args.sku or pp.find_sku_folders(pp.INPUT_DIR):
        folder = os.path.join(pp.INPUT_DIR, sku)
        raws = pp.raw_images_in(folder)
        if not raws:
            continue
        pj = os.path.join(folder, "product.json")
        profile = json.load(open(pj, encoding="utf-8")) if os.path.exists(pj) else {}
        profile.update(analyzer.manual_overrides(pj))
        plan = plan_slots(raws, profile)
        total += len(plan)
        tags = profile.get("photos") or {}
        print(f"[{sku}] {len(raws)} photos -> {len(plan)} fal images")
        packed = profile.get("photo_packaging") or {}
        for slot, photo in plan.items():
            n = os.path.basename(photo)
            print(f"    {slot:12s} <- {n:14s} ({tags.get(n, 'untagged')}"
                  + (", packaging" if packed.get(n) is not False else "") + ")")
        for note in plan_warnings(plan, profile):
            print(f"    ! {note}")
    spec = FAL_MODELS[FAL_MODEL]
    print(f"\n{total} fal images x ${spec['usd']} ({FAL_MODEL}) = ${total * spec['usd']:.2f} list price")


if __name__ == "__main__":
    main()
