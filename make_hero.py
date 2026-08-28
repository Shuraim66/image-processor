#!/usr/bin/env python3
"""
Marketing hero-image generator (free / procedural).

Composites a transparent product cutout onto a procedural studio background and
overlays headline banners, a sticker wordmark, icon feature bullets, corner
ribbons and the brand logo — the "Fun Ride Every Day / SCOOTY" style layout.

No paid AI: backgrounds are drawn, text is rendered from a per-product content
dict (which the free Gemini *text* model can fill in — see build_content()).

    python make_hero.py                      # renders the built-in demo
    from make_hero import render_hero        # use in a batch pipeline
"""

import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
SIZE = 1600                 # final square hero size (px)
SS = 2                      # supersample factor for crisp edges
LOGO_PATH = "logo.png"

# Fonts are bundled in the repo (assets/fonts) so rendering is OS-portable.
# Fall back to common system locations if the bundle is missing.
_HERE = os.path.dirname(os.path.abspath(__file__))
_FONT_DIRS = [
    os.path.join(_HERE, "assets", "fonts"),
    "/usr/share/fonts/opentype/montserrat",                     # Linux
    "/Library/Fonts", os.path.expanduser("~/Library/Fonts"),    # macOS
]

# default brand palette (overridable per product via content["theme"])
THEME = {
    "primary": (27, 77, 177),      # blue
    "accent":  (232, 53, 43),      # red
    "ink":     (16, 48, 110),      # dark navy
    "bg_top":  (232, 244, 255),    # soft sky
    "bg_bot":  (255, 255, 255),    # white
}

W = SIZE * SS


def _font(name, px):
    for d in _FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return ImageFont.truetype(p, px * SS)
    return ImageFont.truetype(name, px * SS)  # let PIL raise a clear error


# --------------------------------------------------------------------------- #
# Background
# --------------------------------------------------------------------------- #
def make_background(theme):
    """Soft vertical gradient + bokeh + a radial glow and podium ellipse."""
    top, bot = theme["bg_top"], theme["bg_bot"]
    bg = Image.new("RGB", (W, W), bot)
    grad = Image.new("L", (1, W))
    for y in range(W):
        grad.putpixel((0, y), int(255 * (1 - y / W)))
    grad = grad.resize((W, W))
    bg = Image.composite(Image.new("RGB", (W, W), top), bg, grad)

    # soft bokeh circles (very light)
    bok = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bok)
    spots = [(0.18, 0.16, 150), (0.82, 0.12, 120), (0.9, 0.5, 170),
             (0.12, 0.62, 130), (0.72, 0.78, 110), (0.3, 0.32, 90)]
    for fx, fy, r in spots:
        x, y, r = fx * W, fy * W, r * SS
        bd.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 70))
    bok = bok.filter(ImageFilter.GaussianBlur(60 * SS))
    bg = Image.alpha_composite(bg.convert("RGBA"), bok).convert("RGB")

    # central radial glow behind the product
    glow = Image.new("L", (W, W), 0)
    gd = ImageDraw.Draw(glow)
    gx, gy, gr = int(W * 0.58), int(W * 0.5), int(W * 0.42)
    gd.ellipse([gx - gr, gy - gr, gx + gr, gy + gr], fill=90)
    glow = glow.filter(ImageFilter.GaussianBlur(120 * SS))
    bg = Image.composite(Image.new("RGB", (W, W), (255, 255, 255)), bg, glow)
    return bg.convert("RGBA")


def add_podium(bg, cx, base_y):
    """A light elliptical podium with a soft contact shadow under the product."""
    d = ImageDraw.Draw(bg)
    pw, ph = int(W * 0.5), int(W * 0.09)
    # contact shadow (darker, tight)
    sh = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse(
        [cx - pw // 2, base_y - ph // 2, cx + pw // 2, base_y + ph // 2],
        fill=(40, 60, 100, 60))
    sh = sh.filter(ImageFilter.GaussianBlur(28 * SS))
    bg.alpha_composite(sh)
    # podium highlight (soft, wide blur so no hard ring shows)
    pod = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(pod).ellipse(
        [cx - pw // 2, base_y - ph // 2, cx + pw // 2, base_y + ph // 2],
        fill=(255, 255, 255, 80))
    pod = pod.filter(ImageFilter.GaussianBlur(35 * SS))
    bg.alpha_composite(pod)
    return bg


# --------------------------------------------------------------------------- #
# Product
# --------------------------------------------------------------------------- #
def place_product(bg, cutout, cx, base_y, target_h):
    """Scale cutout to target_h, drop a soft shadow, sit it on base_y."""
    scale = target_h / cutout.height
    prod = cutout.resize((max(1, int(cutout.width * scale)), target_h), Image.LANCZOS)
    px = cx - prod.width // 2
    py = base_y - prod.height + int(0.02 * W)  # slight overlap into podium

    # drop shadow from the alpha
    shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    sil = Image.new("RGBA", prod.size, (20, 30, 60, 0))
    sil.putalpha(prod.getchannel("A").point(lambda a: 110 if a > 0 else 0))
    shadow.paste(sil, (px + int(0.015 * W), py + int(0.02 * W)), sil)
    shadow = shadow.filter(ImageFilter.GaussianBlur(22 * SS))
    bg.alpha_composite(shadow)

    bg.alpha_composite(prod.convert("RGBA"), (px, py))
    return bg


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #
def _text_size(font, text):
    b = font.getbbox(text)
    return b[2] - b[0], b[3] - b[1], b[0], b[1]


def sticker_text(base, xy, text, font, fill, outline=(255, 255, 255),
                 outline_w=10, shadow=(0, 0, 0, 70)):
    """Big wordmark with a thick outline halo and a soft drop shadow."""
    ow = outline_w * SS
    tw, th, ox, oy = _text_size(font, text)
    pad = ow + 20 * SS
    layer = Image.new("RGBA", (tw + 2 * pad, th + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    px, py = pad - ox, pad - oy
    # shadow
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((px, py + 6 * SS), text, font=font, fill=shadow)
    sh = sh.filter(ImageFilter.GaussianBlur(6 * SS))
    layer = Image.alpha_composite(layer, sh)
    d = ImageDraw.Draw(layer)
    # outline ring
    import math
    for ang in range(0, 360, 24):
        dx = int(ow * math.cos(math.radians(ang)))
        dy = int(ow * math.sin(math.radians(ang)))
        d.text((px + dx, py + dy), text, font=font, fill=outline)
    d.text((px, py), text, font=font, fill=fill)
    base.alpha_composite(layer, (xy[0] - pad, xy[1] - pad))
    return tw, th


def banner(base, xy, text, font, fill, text_fill=(255, 255, 255),
           pad_x=26, pad_y=12, radius=26, angle=0, anchor="left"):
    """Rounded 'brush' banner with centered text (supports '\\n'); optional rotation.

    anchor='right' treats xy as the top-RIGHT corner so the banner grows leftward
    and stays on-canvas.
    """
    lines = text.split("\n")
    asc, desc = font.getmetrics()
    line_h = asc + desc
    widths = [font.getbbox(ln)[2] for ln in lines]
    tw, th = max(widths), line_h * len(lines)
    bw, bh = tw + 2 * pad_x * SS, th + 2 * pad_y * SS
    lay = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    d.rounded_rectangle([0, 0, bw, bh], radius=radius * SS, fill=fill)
    ty = pad_y * SS
    for ln, w in zip(lines, widths):
        d.text(((bw - w) // 2, ty), ln, font=font, fill=text_fill)  # centered
        ty += line_h
    if angle:
        lay = lay.rotate(angle, expand=True, resample=Image.BICUBIC)
    x, y = xy
    if anchor == "right":
        x -= lay.size[0]
    base.alpha_composite(lay, (x, y))
    return lay.size


# --------------------------------------------------------------------------- #
# Icons (simple vector glyphs drawn on a colored circle)
# --------------------------------------------------------------------------- #
def _icon_circle(d, box, color):
    d.ellipse(box, fill=color)


def draw_feature_icon(base, cx, cy, r, kind, circle_color):
    lay = Image.new("RGBA", (r * 2 + 8 * SS, r * 2 + 8 * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    o = 4 * SS
    _icon_circle(d, [o, o, o + 2 * r, o + 2 * r], circle_color)
    cxl, cyl = o + r, o + r
    w = (255, 255, 255, 255)
    lw = max(3, r // 8)
    if kind == "shield":
        d.polygon([(cxl, cyl - r * 0.55), (cxl + r * 0.45, cyl - r * 0.25),
                   (cxl + r * 0.45, cyl + r * 0.15), (cxl, cyl + r * 0.6),
                   (cxl - r * 0.45, cyl + r * 0.15), (cxl - r * 0.45, cyl - r * 0.25)],
                  fill=w)
        d.line([(cxl - r * 0.18, cyl + r * 0.02), (cxl - r * 0.02, cyl + r * 0.22),
                (cxl + r * 0.28, cyl - r * 0.22)], fill=circle_color, width=lw)
    elif kind == "arrows":  # adjustable height: up/down arrow
        d.line([(cxl, cyl - r * 0.55), (cxl, cyl + r * 0.55)], fill=w, width=lw)
        d.polygon([(cxl, cyl - r * 0.62), (cxl - r * 0.22, cyl - r * 0.3),
                   (cxl + r * 0.22, cyl - r * 0.3)], fill=w)
        d.polygon([(cxl, cyl + r * 0.62), (cxl - r * 0.22, cyl + r * 0.3),
                   (cxl + r * 0.22, cyl + r * 0.3)], fill=w)
    elif kind == "wheel":
        d.ellipse([cxl - r * 0.55, cyl - r * 0.55, cxl + r * 0.55, cyl + r * 0.55],
                  outline=w, width=lw)
        d.ellipse([cxl - r * 0.14, cyl - r * 0.14, cxl + r * 0.14, cyl + r * 0.14], fill=w)
        import math
        for a in range(0, 360, 45):
            d.line([(cxl, cyl),
                    (cxl + r * 0.5 * math.cos(math.radians(a)),
                     cyl + r * 0.5 * math.sin(math.radians(a)))], fill=w, width=lw)
    elif kind == "smiley":
        d.ellipse([cxl - r * 0.55, cyl - r * 0.55, cxl + r * 0.55, cyl + r * 0.55],
                  outline=w, width=lw)
        for ex in (-0.22, 0.22):
            d.ellipse([cxl + r * ex - r * 0.07, cyl - r * 0.2 - r * 0.07,
                       cxl + r * ex + r * 0.07, cyl - r * 0.2 + r * 0.07], fill=w)
        d.arc([cxl - r * 0.3, cyl - r * 0.25, cxl + r * 0.3, cyl + r * 0.3],
              20, 160, fill=w, width=lw)
    base.alpha_composite(lay, (cx - r - o, cy - r - o))


# --------------------------------------------------------------------------- #
# Compose
# --------------------------------------------------------------------------- #
def _fit_font(fontname, lines, max_w, start_px, min_px=16):
    """Largest font (<= start_px) whose widest line fits within max_w px."""
    if isinstance(lines, str):
        lines = [lines]
    px = start_px
    while px > min_px:
        f = _font(fontname, px)
        if max(f.getbbox(ln)[2] for ln in lines) <= max_w:
            return f
        px -= 2
    return _font(fontname, min_px)


def overlay_hero_text(bg, content, theme):
    """Draw the headline banners, sticker wordmark, feature bullets, corner
    ribbon, side callout and brand logo. All text auto-shrinks to its zone so it
    never overlaps the product (centred right) or runs off-canvas."""
    x0, y0 = int(W * 0.05), int(W * 0.06)
    LEFT_W = int(W * 0.42)          # text column keeps clear of the product

    # --- headline banners (top-left) ---
    f_ban = _fit_font("Montserrat-ExtraBold.otf",
                      [content["tagline_top"], content["tagline_sub"]],
                      LEFT_W - 60 * SS, 46, 24)
    w1, h1 = banner(bg, (x0, y0), content["tagline_top"], f_ban, theme["primary"])
    banner(bg, (x0 + 12 * SS, y0 + h1 + 8 * SS), content["tagline_sub"], f_ban,
           theme["accent"])

    # --- sticker wordmark (fit to the left column) ---
    f_word = _fit_font("Montserrat-Black.otf", content["name"], LEFT_W, 150, 54)
    sticker_text(bg, (x0, int(W * 0.24)), content["name"], f_word,
                 fill=theme["primary"], outline=(255, 255, 255), outline_w=12)

    # --- feature bullets (left column) ---
    r = int(W * 0.032)
    label_x = x0 + 2 * r + 22 * SS
    label_max = LEFT_W - (label_x - x0)         # width left for the label text
    fy = int(W * 0.46)
    gap = int(W * 0.105)
    for i, feat in enumerate(content["features"][:4]):
        cyc = fy + i * gap
        col = theme["primary"] if i % 2 == 0 else theme["accent"]
        draw_feature_icon(bg, x0 + r, cyc, r, feat["icon"], col)
        d = ImageDraw.Draw(bg)
        lines = feat["label"].split("\n")
        ff = _fit_font("Montserrat-Bold.otf", lines, label_max, 34, 18)
        lh = ff.getmetrics(); lh = lh[0] + lh[1]
        ty = cyc - (len(lines) * lh) // 2
        for ln in lines:
            d.text((label_x, ty), ln, font=ff, fill=theme["ink"])
            ty += lh

    # --- corner ribbon (bottom-left) ---
    f_rib = _fit_font("Montserrat-ExtraBold.otf", content["ribbon"], int(W * 0.5), 36, 20)
    banner(bg, (int(W * 0.03), int(W * 0.88)), content["ribbon"], f_rib,
           theme["accent"], radius=22, angle=6)

    # --- side callout burst (right, anchored + fitted so it never clips) ---
    if content.get("callout"):
        call = content["callout"].replace(" & ", "\n& ")
        f_call = _fit_font("Montserrat-ExtraBold.otf", call.split("\n"),
                           int(W * 0.30), 34, 20)
        banner(bg, (int(W * 0.965), int(W * 0.30)), call, f_call,
               theme["primary"], radius=22, angle=-8, anchor="right")

    # --- brand logo (top-right) ---
    if os.path.exists(LOGO_PATH):
        logo = Image.open(LOGO_PATH).convert("RGBA")
        lw = int(W * 0.13)
        logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
        bg.alpha_composite(logo, (int(W * 0.85), int(W * 0.04)))
    return bg


def render_hero(cutout_path, content, out_path, background=None):
    """Render a hero. If `background` (a PIL image) is given it's used as the
    scene (e.g. a Draw Things lifestyle background); otherwise a procedural
    studio background is generated. The real product cutout is always composited
    on top — the scene is never trusted to contain the product."""
    theme = {**THEME, **content.get("theme", {})}
    cx, base_y = int(W * 0.60), int(W * 0.86)

    if background is None:
        bg = make_background(theme)
    else:
        bg = background.convert("RGBA").resize((W, W), Image.LANCZOS)

    bg = add_podium(bg, cx, base_y)
    cutout = Image.open(cutout_path).convert("RGBA")
    bg = place_product(bg, cutout, cx, base_y, target_h=int(W * 0.66))

    overlay_hero_text(bg, content, theme)
    final = bg.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS)
    final.save(out_path, quality=94)
    return out_path


# --------------------------------------------------------------------------- #
# Per-product content (hand-authored demo; a batch pipeline fills this from the
# free Gemini text model — headline, name, 4 features, ribbon, callout).
# --------------------------------------------------------------------------- #
def demo_content():
    return {
        "name": "SCOOTY",
        "tagline_top": "FUN RIDE",
        "tagline_sub": "EVERY DAY!",
        "ribbon": "BUILT FOR FUN, MADE TO LAST!",
        "callout": "LIGHTWEIGHT & PORTABLE",
        "features": [
            {"icon": "shield", "label": "SAFE &\nSTURDY"},
            {"icon": "arrows", "label": "ADJUSTABLE\nHEIGHT"},
            {"icon": "wheel",  "label": "SMOOTH &\nSTABLE RIDE"},
            {"icon": "smiley", "label": "PERFECT FOR\nKIDS 3+ YEARS"},
        ],
        "theme": {"primary": (27, 77, 177), "accent": (232, 53, 43)},
    }


if __name__ == "__main__":
    out = render_hero("hero/SCOOTER-LED-PINK_cutout.png", demo_content(),
                      "hero/SCOOTER-LED-PINK_hero.jpg")
    print("wrote", out)


def derive_theme(image_path):
    """Derive a palette (primary, accent, ink) from the product's own colors so
    overlaid text matches the product. Two-tier: prefer vivid colors, but fall
    back to muted/warm tones (e.g. a brown/black tumbler) before the brand THEME,
    so neutral products still get a matching warm palette instead of blue/red."""
    import colorsys
    im = Image.open(image_path).convert("RGB").resize((140, 140))
    q = im.quantize(colors=16).convert("RGB")
    colors = sorted(q.getcolors(140 * 140) or [], reverse=True)
    hsv = [(cnt, rgb, colorsys.rgb_to_hsv(*[c / 255 for c in rgb])) for cnt, rgb in colors]

    def pick(min_s):   # chromatic pixels, excluding near-white and near-black
        return [x for x in hsv if x[2][1] > min_s and 0.16 < x[2][2] < 0.95]

    cand = pick(0.28) or pick(0.10)     # vivid first, then muted
    if not cand:
        return dict(THEME)

    ph, ps, pv = cand[0][2]
    # deepen a light/washed primary so banners stay readable with white text
    ts, tv = max(ps, 0.38), min(pv, 0.62)
    primary = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(ph, ts, tv))
    # accent: a distinct hue if the product has one, else a warmer deeper shade
    accent = None
    for _, _, (h, s, v) in cand[1:]:
        if min(abs(h - ph), 1 - abs(h - ph)) > 0.08:
            accent = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h, max(s, 0.4), min(v, 0.6)))
            break
    if accent is None:
        accent = tuple(int(c * 255) for c in
                       colorsys.hsv_to_rgb((ph + 0.05) % 1.0, min(1, ts + 0.12), max(0.32, tv - 0.14)))
    ink = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(ph, min(0.6, ts), 0.22))
    return {**THEME, "primary": primary, "accent": accent, "ink": ink}


def product_style(image_path):
    """Classify a product as 'playful' (vivid, colorful toy -> funky fonts) or
    'clean' (muted/neutral, grown-up item like a tumbler -> simple fonts),
    from the saturation of its dominant colour."""
    import colorsys
    im = Image.open(image_path).convert("RGB").resize((140, 140))
    q = im.quantize(colors=16).convert("RGB")
    best = 0.0
    for cnt, rgb in (q.getcolors(140 * 140) or []):
        h, s, v = colorsys.rgb_to_hsv(*[c / 255 for c in rgb])
        if 0.2 < v < 0.95:
            best = max(best, s)
    return "playful" if best > 0.45 else "clean"
