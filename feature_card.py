#!/usr/bin/env python3
"""
FeatureCard V2 + titled hero — catalog infographics in The Toy Gift Shop's look.

Amazon-style layout (product title, subhead, 4 icon features, a row of real
thumbnails) dressed in the live storefront's brand: Archivo headings, DM Sans body,
navy ink, a red accent and a gold eyebrow. Text is rendered by us (always correct), thumbnails are
the product's own images (never fabricated), and each feature gets a Tabler line
icon picked from its wording.

    render_v2(hero_photo, thumbs, content, out_path)
    render_hero_title(product_photo, content, out_path)
"""

import math
import os
import re
from PIL import Image, ImageDraw, ImageFilter
import make_hero as mh
import process_products as pp

W, SS, SIZE = mh.W, mh.SS, mh.SIZE

# The live theme's own tokens (the-toy-gift-shop-cy0w57r4.myshopify.com), read from the storefront.
NAVY = (29, 39, 78)        # --ink / --primary #1D274E
SLATE = (91, 98, 128)      # --ink-2 #5B6280
RED = (218, 46, 46)        # --accent #DA2E2E
GOLD = (135, 99, 2)        # --gift-deep #876302, readable gold for text
GOLD_RULE = (253, 206, 77) # --gift #FDCE4D
BG = (244, 245, 249)       # --surface-2 #F4F5F9
SURFACE = (255, 255, 255)
LINE = (227, 230, 238)     # --line #E3E6EE
WHITE = (255, 255, 255)
NIGHT = (18, 24, 48)       # --night #121830
TINT = (231, 234, 243)     # soft navy wash behind the product
F_XB, F_B = "Archivo-Variable.ttf@ExtraBold", "Archivo-Variable.ttf@Bold"
F_SB, F_M = "DMSans-Variable.ttf@SemiBold", "DMSans-Variable.ttf@Medium"
F_ICON = "tabler-icons-outline.ttf"

# Tabler Icons (outline webfont 3.34.1) codepoints for the icons we use.
ICONS = {
    "shield-check": 0xeb22, "ruler-measure": 0xf291, "wheel": 0xfc64, "music": 0xeafc,
    "bulb": 0xea51, "battery-charging": 0xea33, "device-gamepad-2": 0xf1d2,
    "mood-kid": 0xec03, "packages": 0xf2c9, "puzzle": 0xeb10, "palette": 0xeb01,
    "brush": 0xebb8, "sparkles": 0xf6d7, "award": 0xea2c, "school": 0xecf7,
    "hand-finger": 0xee94, "lock": 0xeae2, "clock": 0xea70, "car": 0xebbb,
    "plane": 0xeb6f, "drone": 0xed79, "droplet": 0xea97, "trees": 0xec10,
    "briefcase": 0xea46, "gift": 0xeb68, "wall": 0xef7a, "cube": 0xfa97,
    "feather": 0xee8b, "volume": 0xeb51, "dice-5": 0xf08f, "robot": 0xf00b,
    "rotate-360": 0xef85, "bolt": 0xea38, "circle-check": 0xea67,
}
# First matching rule wins; checked against the feature's title + description.
ICON_RULES = [
    (r"remote|infrared|\brc\b|2\.4 ?g|controller", "device-gamepad-2"),
    (r"climb|wall", "wall"),
    (r"fly|flight|drone|hover", "drone"),
    (r"light|led|glow|flash|lamp", "bulb"),
    (r"music|sing|sound|song|melod|piano|xylophone|voice|audio", "music"),
    (r"battery|recharg|usb|charg", "battery-charging"),
    (r"safe|sturdy|durable|non-?toxic|bpa|smooth edge|certif", "shield-check"),
    (r"\bage|toddler|kid|child|baby|month|years|\d+ ?m\+|\d\+", "mood-kid"),
    (r"scale|size|\bcm\b|inch|compact|mini|large|\d:\d", "ruler-measure"),
    (r"makeup|brush|cosmetic|nail|lipstick", "brush"),
    (r"draw|paint|colou?r|art\b|marker|crayon|palette", "palette"),
    (r"learn|educat|stem|science|skill|montessori|number|letter|count|shape", "school"),
    (r"puzzle|sort|match|stack", "puzzle"),
    (r"lock|key|latch|door", "lock"),
    (r"clock|time", "clock"),
    (r"water|bath|pool|splash|float", "droplet"),
    (r"interactive|busy|button|press|touch|hands-?on|motor", "hand-finger"),
    (r"die-?cast|metal|vehicle|car\b", "car"),
    (r"collect|display|model|detail", "award"),
    (r"zip|handle|case|portable|carry|travel", "briefcase"),
    (r"wood", "trees"),
    (r"plush|soft|fabric|cotton", "feather"),
    (r"plastic|material|construction|build", "cube"),
    (r"move|moving|wheel|roll|walk|danc|motion", "wheel"),
    (r"rotat|spin|360", "rotate-360"),
    (r"includ|set\b|piece|pcs|accessor|in the box", "packages"),
    (r"robot", "robot"),
    (r"game|play|fun", "dice-5"),
    (r"design|character|unicorn|cute|animal|dinosaur|glitter", "sparkles"),
    (r"gift", "gift"),
]
LEGACY_ICONS = {"shield": "shield-check", "arrows": "ruler-measure", "wheel": "wheel",
                "smiley": "mood-kid", "gift": "gift", "bulb": "bulb", "hand": "hand-finger"}

ACRONYMS = {"RC", "LED", "USB", "STEM", "DIY", "3D", "ABS", "BPA", "AA", "AAA", "IR", "UV",
            "BMW", "GTR", "SUV", "LCD", "TV", "PC", "XL"}
SMALL = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with"}


# ---------- small helpers ----------------------------------------------------
def smart_title(text):
    """'DIE-CAST 18-PIECE SET' -> 'Die-Cast 18-Piece Set', keeping RC/LED/M3/1:18/18M+."""
    def part(p):
        letters = sum(c.isalpha() for c in p)
        if p.upper() in ACRONYMS or (any(c.isdigit() for c in p) and letters <= 2):
            return p.upper()
        return p[:1].upper() + p[1:].lower()

    def word(w, first):
        if not first and w.lower() in SMALL:
            return w.lower()
        return "-".join(part(p) for p in w.split("-"))
    words = text.split()
    return " ".join(word(w, i == 0) for i, w in enumerate(words))


def pick_icon(feature, used=()):
    """Best icon for a feature's wording, preferring one not already on the card."""
    text = f"{feature.get('title', '')} {feature.get('desc', '')}".lower()
    matches = [name for pattern, name in ICON_RULES if re.search(pattern, text)]
    fresh = [m for m in matches if m not in used]
    if fresh or matches:
        return (fresh or matches)[0]
    return LEGACY_ICONS.get(feature.get("icon"), "circle-check")


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit_wrapped(draw, text, fontname, max_w, max_lines, start_px, min_px):
    """Largest font whose word-wrap fits in max_lines; last resort truncates."""
    for px in range(start_px, min_px - 1, -2):
        f = mh._font(fontname, px)
        lines = _wrap(draw, text, f, max_w)
        if len(lines) <= max_lines:
            return f, lines
    lines = _wrap(draw, text, f, max_w)
    return f, lines[:max_lines - 1] + [lines[max_lines - 1].rstrip(",;:") + "…"]


def _tracked(draw, xy, text, font, fill, tracking):
    """Letter-spaced caps (the site's eyebrow style); returns the drawn width."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x - xy[0] - tracking


def _tracked_width(draw, text, font, tracking):
    return sum(draw.textlength(ch, font=font) for ch in text) + tracking * (len(text) - 1)


def _rounded_thumb(img, size, rad):
    img = img.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size, size], radius=rad, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _brand_background():
    bg = Image.new("RGB", (W, W), WHITE)
    grad = Image.new("L", (1, W))
    for y in range(W):
        grad.putpixel((0, y), int(255 * (1 - y / W)))
    return Image.composite(Image.new("RGB", (W, W), BG), bg, grad.resize((W, W))).convert("RGBA")


def _soft_disc(bg, box, blur):
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).ellipse(box, fill=255)
    bg.paste(Image.new("RGBA", (W, W), TINT + (255,)), (0, 0), mask.filter(ImageFilter.GaussianBlur(blur)))


def _place_cutout(bg, photo, box, shadow=True, disc=None):
    """Real product cutout fitted into box=(left, top, width, height).

    `disc` = (cx, cy, radius): also keep the cutout inside that circle, so a wide or tall
    product is framed by the brand disc instead of spilling out of it."""
    cut = pp.trim_to_content(pp.remove_background(Image.open(photo).convert("RGBA")))
    left, top, bw, bh = box
    s = min(bw / cut.width, bh / cut.height)
    if disc:
        diag = math.hypot(cut.width, cut.height) / 2
        s = min(s, disc[2] * 0.97 / diag)
    cut = cut.resize((max(1, int(cut.width * s)), max(1, int(cut.height * s))), Image.LANCZOS)
    if disc:
        px, py = int(disc[0] - cut.width / 2), int(disc[1] - cut.height / 2)
    else:
        px, py = left + (bw - cut.width) // 2, top + (bh - cut.height) // 2
    if shadow:
        sh = Image.new("RGBA", (W, W), (0, 0, 0, 0))
        sil = Image.new("RGBA", cut.size, NAVY + (0,))
        sil.putalpha(cut.getchannel("A").point(lambda a: 70 if a else 0))
        sh.paste(sil, (px + 8 * SS, py + 18 * SS), sil)
        bg.alpha_composite(sh.filter(ImageFilter.GaussianBlur(22 * SS)))
    bg.alpha_composite(cut, (px, py))
    return px, py, cut.size


def _logo(bg, x, y, width):
    if os.path.exists(mh.LOGO_PATH):
        logo = Image.open(mh.LOGO_PATH).convert("RGBA")
        logo = logo.resize((width, int(logo.height * width / logo.width)), Image.LANCZOS)
        bg.alpha_composite(logo, (x, y))


# ---------- main -------------------------------------------------------------
def render_v2(hero_photo, thumbs, content, out_path, theme=None, scene=None):
    """theme/scene are accepted for backward compatibility; the brand look is fixed."""
    bg = _brand_background()
    d = ImageDraw.Draw(bg)

    # soft brand disc behind the product (right), then the real cutout
    cx, cy, rr = int(W * 0.725), int(W * 0.385), int(W * 0.255)
    _soft_disc(bg, [cx - rr, cy - rr, cx + rr, cy + rr], 6 * SS)
    _place_cutout(bg, hero_photo, (int(W * 0.47), int(W * 0.15), int(W * 0.50), int(W * 0.48)),
                  disc=(cx, cy, rr))
    _logo(bg, int(W * 0.855), int(W * 0.035), int(W * 0.11))

    x0, col_w = int(W * 0.06), int(W * 0.38)
    y = int(W * 0.065)
    # eyebrow: gold dash + letter-spaced caps (single-line pill; tagline_top may carry a
    # \n for the older two-line banner renderer in make_hero.py, so flatten it here)
    if content.get("eyebrow"):
        eyebrow = content["eyebrow"].replace("\n", " ").upper()
        f_e = mh._fit_font(F_B, eyebrow, col_w - 60 * SS, 21, 15)
        dash = 34 * SS
        d.rounded_rectangle([x0, y + 12 * SS, x0 + dash, y + 15 * SS], radius=2 * SS, fill=GOLD_RULE)
        _tracked(d, (x0 + dash + 14 * SS, y), eyebrow, f_e, GOLD, 3.2 * SS)
        y += int(46 * SS)
    # product title: navy ExtraBold, up to 3 lines
    f_t, lines = _fit_wrapped(d, smart_title(content.get("title", "")), F_XB, col_w, 3, 58, 36)
    lh = int(f_t.size * 1.16)
    for ln in lines:
        d.text((x0, y), ln, font=f_t, fill=NAVY); y += lh
    # red accent bar (the storefront's underline swash, simplified)
    y += int(10 * SS)
    d.rounded_rectangle([x0, y, x0 + int(W * 0.055), y + 7 * SS], radius=4 * SS, fill=RED)
    y += int(30 * SS)
    # subhead
    if content.get("subhead"):
        f_s, sub = _fit_wrapped(d, content["subhead"].rstrip("."), F_M, col_w, 3, 25, 20)
        for ln in sub:
            d.text((x0, y), ln, font=f_s, fill=SLATE); y += int(f_s.size * 1.45)

    # 4 features: tinted circle + navy line icon, bold title, slate description
    feats = content.get("features", [])[:4]
    top, bottom = y + int(40 * SS), int(W * 0.685)
    step = min(int(W * 0.078), (bottom - top) // max(1, len(feats)))
    top += ((bottom - top) - step * len(feats)) // 2   # centre the block in the free space
    used = set()
    r = int(W * 0.029)
    f_ft = mh._font(F_B, 27)
    f_fd = mh._font(F_M, 22)
    f_ic = mh._font(F_ICON, 34)
    for i, ft in enumerate(feats):
        cyf = top + i * step + r
        d.ellipse([x0, cyf - r, x0 + 2 * r, cyf + r], fill=TINT)
        icon = pick_icon(ft, used); used.add(icon)
        d.text((x0 + r, cyf), chr(ICONS[icon]), font=f_ic, fill=NAVY, anchor="mm")
        tx = x0 + 2 * r + int(22 * SS)
        title, desc = smart_title(ft.get("title", "")), ft.get("desc", "")
        desc = desc[:1].upper() + desc[1:].lower() if desc.isupper() else desc
        if desc:
            d.text((tx, cyf - int(4 * SS)), title, font=f_ft, fill=NAVY, anchor="ls")
            d.text((tx, cyf + int(8 * SS)), desc, font=f_fd, fill=SLATE, anchor="lt")
        else:
            d.text((tx, cyf), title, font=f_ft, fill=NAVY, anchor="lm")

    # thumbnail row (the product's own images)
    n = len(thumbs); pad = int(W * 0.02)
    tw = int((W - 2 * x0 - 3 * pad) / 4)          # always the 4-up size; fewer never means bigger
    row_w = n * tw + (n - 1) * pad
    x_row = x0 + (W - 2 * x0 - row_w) // 2        # centre a short row
    ty = int(W * 0.715); f_c = mh._font(F_B, 17)
    for i, t in enumerate(thumbs):
        src = Image.open(t["photo"]).convert("RGB")
        l, tp, rr2, b = t["crop"]; iw, ih = src.size
        crop = src.crop((int(l * iw), int(tp * ih), int(rr2 * iw), int(b * ih)))
        cs = min(crop.size); crop = crop.crop(((crop.width - cs) // 2, (crop.height - cs) // 2,
                                               (crop.width + cs) // 2, (crop.height + cs) // 2))
        tx = x_row + i * (tw + pad)
        bg.alpha_composite(_rounded_thumb(crop, tw, int(20 * SS)), (tx, ty))
        d.rounded_rectangle([tx, ty, tx + tw, ty + tw], radius=int(20 * SS), outline=LINE, width=int(3 * SS))
        cap = t["caption"].upper(); cw = _tracked_width(d, cap, f_c, 2.5 * SS)
        _tracked(d, (tx + (tw - cw) / 2, ty + tw + int(14 * SS)), cap, f_c, SLATE, 2.5 * SS)

    bg.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS).save(out_path, quality=94)
    return out_path


def render_hero_title(product_photo, content, out_path, theme=None, scene=None):
    """Store-style titled hero: logo + badge row, eyebrow pill, big title with the
    red accent bar, subhead, product below. theme/scene kept for compatibility."""
    bg = _brand_background()
    d = ImageDraw.Draw(bg)

    _soft_disc(bg, [int(W * 0.14), int(W * 0.52), int(W * 0.86), int(W * 1.10)], 10 * SS)
    _place_cutout(bg, product_photo, (int(W * 0.10), int(W * 0.47), int(W * 0.80), int(W * 0.44)))
    _logo(bg, int(W * 0.045), int(W * 0.04), int(W * 0.13))

    if content.get("badge"):   # round red badge, top-right
        bd = int(W * 0.14); bx, by = int(W * 0.815), int(W * 0.04)
        d.ellipse([bx, by, bx + bd, by + bd], fill=RED)
        f_b = mh._font(F_XB, 26); lines = content["badge"].split()
        ty = by + bd // 2 - (len(lines) - 1) * int(17 * SS)
        for ln in lines:
            d.text((bx + bd // 2, ty), ln, font=f_b, fill=WHITE, anchor="mm"); ty += int(34 * SS)

    y = int(W * 0.215)
    if content.get("eyebrow") and content["eyebrow"].strip().lower() != content["title"].strip().lower():
        cap = content["eyebrow"].replace("\n", " ").upper()  # eyebrow is a single-line pill;
        # tagline_top may carry a \n for the older two-line banner renderer in make_hero.py
        f_e = mh._fit_font(F_B, cap, int(W * 0.6), 24, 16)
        tw = _tracked_width(d, cap, f_e, 3 * SS); bw, bh = int(tw + 60 * SS), int(56 * SS)
        bx = (W - bw) // 2
        d.rounded_rectangle([bx, y, bx + bw, y + bh], radius=bh // 2, fill=TINT)
        _tracked(d, (bx + 30 * SS, y + bh // 2 - f_e.size * 0.62), cap, f_e, NAVY, 3 * SS)
        y += bh + int(28 * SS)

    f_t, lines = _fit_wrapped(d, smart_title(content["title"]), F_XB, int(W * 0.84), 2, 104, 56)
    for ln in lines:
        d.text((W // 2, y), ln, font=f_t, fill=NAVY, anchor="mt"); y += int(f_t.size * 1.08)
    y += int(14 * SS)
    d.rounded_rectangle([(W - int(W * 0.07)) // 2, y, (W + int(W * 0.07)) // 2, y + 8 * SS],
                        radius=4 * SS, fill=RED)
    y += int(34 * SS)
    if content.get("subhead2"):
        f_s = mh._fit_font(F_SB, smart_title(content["subhead2"]), int(W * 0.8), 34, 22)
        d.text((W // 2, y), smart_title(content["subhead2"]), font=f_s, fill=SLATE, anchor="mt")

    bg.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS).save(out_path, quality=94)
    return out_path
