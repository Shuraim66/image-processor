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
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont, ImageFilter

import typeset

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


@lru_cache(maxsize=256)
def _font(spec, px):
    """Load a bundled face at `px` (pre-supersample).

    `spec` is a filename, or (filename, instance) for a variable font such as
    Baloo 2 — PIL loads the default instance otherwise, which is far too light
    for a headline. Cached because _fit_font() searches by re-measuring, so an
    uncached load re-reads the same file from disk dozens of times per element.
    """
    name, variation = spec if isinstance(spec, tuple) else (spec, None)
    font = None
    for d in _FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            font = ImageFont.truetype(p, px * SS)
            break
    if font is None:
        font = ImageFont.truetype(name, px * SS)  # let PIL raise a clear error
    if variation:
        font.set_variation_by_name(variation)
    return font


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
def place_product(bg, cutout, cx, base_y, target_h, max_w=None):
    """Scale cutout into a target_h x max_w box, shadow it, sit it on base_y.

    Returns (bg, (x, y, w, h)) so callers can lay text out around the product
    instead of guessing where it ended up. Capping the width matters: a wide
    product scaled by height alone spills into the text column.
    """
    scale = target_h / cutout.height
    if max_w:
        scale = min(scale, max_w / cutout.width)
    prod = cutout.resize((max(1, int(cutout.width * scale)),
                          max(1, int(cutout.height * scale))), Image.LANCZOS)
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
    return bg, (px, py, prod.width, prod.height)


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #
def _text_size(font, text):
    b = font.getbbox(text)
    return b[2] - b[0], b[3] - b[1], b[0], b[1]


def sticker_text(base, xy, text, font, fill, outline=(255, 255, 255),
                 outline_w=10, shadow=(0, 0, 0, 70), stroke=None, stroke_w=4):
    """Big wordmark with a thick outline halo and a soft drop shadow.

    `stroke` adds a second, darker ring outside the halo. Without it a wordmark
    tinted from the product can sit on a background tinted from the same product
    and all but disappear; the dark ring keeps it readable on any ground,
    including the photographic scenes the lifestyle slots composite onto.
    """
    ow = outline_w * SS
    sw = stroke_w * SS if stroke else 0
    tw, th, ox, oy = _text_size(font, text)
    pad = ow + sw + 20 * SS
    layer = Image.new("RGBA", (tw + 2 * pad, th + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    px, py = pad - ox, pad - oy
    # shadow
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((px, py + 6 * SS), text, font=font, fill=shadow)
    sh = sh.filter(ImageFilter.GaussianBlur(6 * SS))
    layer = Image.alpha_composite(layer, sh)
    d = ImageDraw.Draw(layer)
    import math
    # rings, outermost first: dark stroke, then the light halo, then the fill
    for radius, colour in ((ow + sw, stroke), (ow, outline)):
        if colour is None:
            continue
        for ang in range(0, 360, 12):
            dx = int(radius * math.cos(math.radians(ang)))
            dy = int(radius * math.sin(math.radians(ang)))
            d.text((px + dx, py + dy), text, font=font, fill=colour)
    d.text((px, py), text, font=font, fill=fill)
    base.alpha_composite(layer, (xy[0] - pad, xy[1] - pad))
    return tw, th


def banner(base, xy, text, font, fill, text_fill=(255, 255, 255),
           pad_x=26, pad_y=12, radius=26, angle=0, anchor="left"):
    """Rounded 'brush' banner with centered text (supports '\\n'); optional rotation.

    `anchor` says what xy means: 'left' the top-left corner, 'right' the
    top-RIGHT so the banner grows leftward, 'center' the horizontal midpoint.
    The banner is only measurable once rendered, so anchoring has to happen here
    rather than at the call site — which is why a title placed at 0.5W with the
    default anchor sat off-centre and, with a wide display face, ran off-canvas.
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
    elif anchor == "center":
        x -= lay.size[0] // 2
    base.alpha_composite(lay, (x, y))
    return lay.size


# --------------------------------------------------------------------------- #
# Icons (simple vector glyphs drawn on a colored circle)
# --------------------------------------------------------------------------- #
def _icon_circle(d, box, color):
    d.ellipse(box, fill=color)


# --------------------------------------------------------------------------- #
# Glyphs. Each draws white marks on a filled circle, in a local frame centred
# at (x, y) with radius r. `bg` is the circle colour, for knocked-out details.
#
# The set is wide on purpose: with only four glyphs the model had to contort
# real features to fit them, so a plush was given a wheel for "EASY TO MOVE"
# and a toy laptop a wheel for "SMOOTH INTERACTION".
# --------------------------------------------------------------------------- #
def _g_shield(d, x, y, r, w, bg, lw):
    d.polygon([(x, y - r * .55), (x + r * .45, y - r * .25), (x + r * .45, y + r * .15),
               (x, y + r * .6), (x - r * .45, y + r * .15), (x - r * .45, y - r * .25)],
              fill=w)
    d.line([(x - r * .18, y + r * .02), (x - r * .02, y + r * .22),
            (x + r * .28, y - r * .22)], fill=bg, width=lw)


def _g_arrows(d, x, y, r, w, bg, lw):
    d.line([(x, y - r * .55), (x, y + r * .55)], fill=w, width=lw)
    d.polygon([(x, y - r * .62), (x - r * .22, y - r * .3), (x + r * .22, y - r * .3)], fill=w)
    d.polygon([(x, y + r * .62), (x - r * .22, y + r * .3), (x + r * .22, y + r * .3)], fill=w)


def _g_wheel(d, x, y, r, w, bg, lw):
    import math
    d.ellipse([x - r * .55, y - r * .55, x + r * .55, y + r * .55], outline=w, width=lw)
    d.ellipse([x - r * .14, y - r * .14, x + r * .14, y + r * .14], fill=w)
    for a in range(0, 360, 45):
        d.line([(x, y), (x + r * .5 * math.cos(math.radians(a)),
                         y + r * .5 * math.sin(math.radians(a)))], fill=w, width=lw)


def _g_smiley(d, x, y, r, w, bg, lw):
    d.ellipse([x - r * .55, y - r * .55, x + r * .55, y + r * .55], outline=w, width=lw)
    for ex in (-.22, .22):
        d.ellipse([x + r * ex - r * .07, y - r * .2 - r * .07,
                   x + r * ex + r * .07, y - r * .2 + r * .07], fill=w)
    d.arc([x - r * .3, y - r * .25, x + r * .3, y + r * .3], 20, 160, fill=w, width=lw)


def _g_bulb(d, x, y, r, w, bg, lw):
    """Lights, LEDs, bright ideas."""
    import math
    d.ellipse([x - r * .34, y - r * .52, x + r * .34, y + r * .16], fill=w)
    d.rectangle([x - r * .16, y + r * .12, x + r * .16, y + r * .42], fill=w)
    d.line([(x - r * .16, y + r * .26), (x + r * .16, y + r * .26)], fill=bg, width=max(2, lw // 2))
    for a in (-60, -20, 20, 60):
        rad = math.radians(a - 90)
        d.line([(x + r * .52 * math.cos(rad), y + r * .52 * math.sin(rad)),
                (x + r * .74 * math.cos(rad), y + r * .74 * math.sin(rad))],
               fill=w, width=lw)


def _g_music(d, x, y, r, w, bg, lw):
    """Sound, music, sing-along."""
    for dx in (-r * .3, r * .3):
        d.ellipse([x + dx - r * .2, y + r * .16, x + dx + r * .1, y + r * .46], fill=w)
        d.line([(x + dx + r * .1, y + r * .31), (x + dx + r * .1, y - r * .42)],
               fill=w, width=lw)
    d.polygon([(x - r * .2, y - r * .42), (x + r * .4, y - r * .52),
               (x + r * .4, y - r * .28), (x - r * .2, y - r * .18)], fill=w)


def _g_battery(d, x, y, r, w, bg, lw):
    """Battery powered, long play time."""
    d.rounded_rectangle([x - r * .5, y - r * .28, x + r * .38, y + r * .28],
                        radius=r * .1, fill=w)
    d.rectangle([x + r * .38, y - r * .12, x + r * .54, y + r * .12], fill=w)
    d.rectangle([x - r * .38, y - r * .16, x + r * .1, y + r * .16], fill=bg)


def _g_book(d, x, y, r, w, bg, lw):
    """Learning, educational, activities."""
    d.polygon([(x - r * .52, y - r * .34), (x - r * .04, y - r * .22),
               (x - r * .04, y + r * .46), (x - r * .52, y + r * .34)], fill=w)
    d.polygon([(x + r * .52, y - r * .34), (x + r * .04, y - r * .22),
               (x + r * .04, y + r * .46), (x + r * .52, y + r * .34)], fill=w)


def _g_heart(d, x, y, r, w, bg, lw):
    """Soft, cuddly, much-loved."""
    d.ellipse([x - r * .46, y - r * .38, x - r * .02, y + r * .06], fill=w)
    d.ellipse([x + r * .02, y - r * .38, x + r * .46, y + r * .06], fill=w)
    d.polygon([(x - r * .44, y - r * .1), (x + r * .44, y - r * .1), (x, y + r * .5)], fill=w)


def _g_star(d, x, y, r, w, bg, lw):
    """Favourite, premium, top rated."""
    import math
    pts = []
    for i in range(10):
        rad = math.radians(-90 + i * 36)
        rr = r * (.56 if i % 2 == 0 else .24)
        pts.append((x + rr * math.cos(rad), y + rr * math.sin(rad)))
    d.polygon(pts, fill=w)


def _g_gift(d, x, y, r, w, bg, lw):
    """Gift ready, boxed."""
    d.rectangle([x - r * .48, y - r * .12, x + r * .48, y + r * .48], fill=w)
    d.rectangle([x - r * .54, y - r * .34, x + r * .54, y - r * .1], fill=w)
    d.rectangle([x - r * .09, y - r * .34, x + r * .09, y + r * .48], fill=bg)
    d.ellipse([x - r * .34, y - r * .56, x - r * .04, y - r * .3], outline=w, width=lw)
    d.ellipse([x + r * .04, y - r * .56, x + r * .34, y - r * .3], outline=w, width=lw)


def _g_droplet(d, x, y, r, w, bg, lw):
    """Washable, water play, bath safe."""
    d.polygon([(x, y - r * .58), (x + r * .38, y + r * .1), (x - r * .38, y + r * .1)], fill=w)
    d.ellipse([x - r * .38, y - r * .18, x + r * .38, y + r * .5], fill=w)


def _g_plant(d, x, y, r, w, bg, lw):
    """Growing, nature, garden."""
    d.line([(x, y + r * .52), (x, y - r * .3)], fill=w, width=lw)
    d.ellipse([x - r * .52, y - r * .34, x - r * .02, y + r * .04], fill=w)
    d.ellipse([x + r * .02, y - r * .5, x + r * .52, y - r * .12], fill=w)


def _g_ruler(d, x, y, r, w, bg, lw):
    """Size, dimensions, measure."""
    d.rectangle([x - r * .56, y - r * .2, x + r * .56, y + r * .2], fill=w)
    for i in (-.34, -.1, .14, .38):
        d.line([(x + r * i, y - r * .2), (x + r * i, y + r * .02)],
               fill=bg, width=max(2, lw // 2))


ICON_DRAWERS = {
    "shield": _g_shield, "arrows": _g_arrows, "wheel": _g_wheel, "smiley": _g_smiley,
    "bulb": _g_bulb, "music": _g_music, "battery": _g_battery, "book": _g_book,
    "heart": _g_heart, "star": _g_star, "gift": _g_gift, "droplet": _g_droplet,
    "plant": _g_plant, "ruler": _g_ruler,
}


def draw_feature_icon(base, cx, cy, r, kind, circle_color):
    lay = Image.new("RGBA", (r * 2 + 8 * SS, r * 2 + 8 * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    o = 4 * SS
    _icon_circle(d, [o, o, o + 2 * r, o + 2 * r], circle_color)
    draw = ICON_DRAWERS.get(kind, _g_smiley)
    draw(d, o + r, o + r, r, (255, 255, 255, 255), circle_color, max(3, r // 8))
    base.alpha_composite(lay, (cx - r - o, cy - r - o))


# --------------------------------------------------------------------------- #
# Compose
# --------------------------------------------------------------------------- #
def _fit_font(fontname, lines, max_w, start_px, min_px=16, max_h=None):
    """Largest font (<= start_px) that fits inside max_w, and max_h if given.

    The height ceiling matters now that display faces vary: a condensed face
    like Anton satisfies a width budget at a point size that would make a short
    wordmark absurdly tall, so width alone is no longer a sufficient test.
    """
    if isinstance(lines, str):
        lines = [lines]
    px = start_px
    while px > min_px:
        f = _font(fontname, px)
        boxes = [f.getbbox(ln) for ln in lines]
        if (max(b[2] for b in boxes) <= max_w
                and (max_h is None or max(b[3] - b[1] for b in boxes) <= max_h)):
            return f
        px -= 2
    return _font(fontname, min_px)


def fit_wrapped(fontspec, text, max_w, start_px, min_px=16, max_lines=2):
    """Wrap `text` to max_w and shrink until it fits in max_lines. -> (font, lines).

    A caption is a sentence, not a label: measuring it as one line and centring
    that meant anything longer than the canvas simply ran off both edges.
    """
    words = text.split()
    px = start_px
    while True:
        font = _font(fontspec, px)
        lines, cur = [], ""
        for word in words:
            trial = f"{cur} {word}".strip()
            if not cur or font.getbbox(trial)[2] <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        if (len(lines) <= max_lines
                and all(font.getbbox(ln)[2] <= max_w for ln in lines)) or px <= min_px:
            return font, lines
        px -= 2


def display_font(content, lines, max_w, max_h):
    """The category's display face, fitted to the space it has."""
    fonts = typeset.fonts_for(content.get("category"))
    return _fit_font(fonts["display"], lines, max_w, fonts["hero_px"], 40,
                     max_h=max_h)


def _centred(base, layer, y):
    """Composite a rendered layer horizontally centred at height y."""
    base.alpha_composite(layer, ((W - layer.size[0]) // 2, y))


def _logo_at(bg, x_frac, y_frac, w_frac=0.13):
    if not os.path.exists(LOGO_PATH):
        return 0
    logo = Image.open(LOGO_PATH).convert("RGBA")
    lw = int(W * w_frac)
    logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
    bg.alpha_composite(logo, (int(W * x_frac), int(W * y_frac)))
    return logo.height


def round_badge(bg, cx, cy, r, lines, theme):
    """Circular corner badge — the '6 PIECES SET' motif from catalog posters."""
    d = ImageDraw.Draw(bg)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=theme["accent"])
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255),
              width=max(2, r // 18))
    f = _fit_font("Montserrat-ExtraBold.otf", lines, int(r * 1.5), 34, 14)
    asc, desc = f.getmetrics()
    lh = asc + desc
    ty = cy - (len(lines) * lh) // 2
    for ln in lines:
        w = f.getbbox(ln)[2]
        d.text((cx - w // 2, ty), ln, font=f, fill=(255, 255, 255))
        ty += lh


def _badge_lines(content):
    """Short stack for the corner badge, from whichever bit of copy is tersest.

    A badge is a glance, not a sentence: 'STEM GROW GAME' reads at thumbnail
    size, 'GROW YOUR OWN PLANTS' shrinks to nothing inside the same circle. So
    take the shorter of callout and ribbon and cap it at three words.
    """
    candidates = [c.strip() for c in (content.get("callout"), content.get("ribbon"))
                  if c and c.strip()]
    if not candidates:
        return None
    words = min(candidates, key=len).replace("&", "").upper().split()[:3]
    if not words:
        return None
    if len(words) == 3 and sum(len(w) for w in words[:2]) <= 9:
        return [f"{words[0]} {words[1]}", words[2]]      # 2 lines reads bigger
    return words


def overlay_poster_text(bg, content, theme):
    """Poster composition: logo and badge in the top corners, then a centred
    eyebrow / wordmark / subtitle stack above a product that runs across the
    bottom. Suits wide products — boxed sets, playsets, ride-ons — which look
    cramped squeezed beside a text column.
    """
    _logo_at(bg, 0.04, 0.035, 0.13)

    badge = _badge_lines(content)
    if badge:
        round_badge(bg, int(W * 0.883), int(W * 0.108), int(W * 0.082),
                    badge, theme)

    # eyebrow
    f_eye = _fit_font("Montserrat-ExtraBold.otf", content["tagline_top"],
                      int(W * 0.60), 44, 22)
    lay = Image.new("RGBA", (W, int(W * 0.10)), (0, 0, 0, 0))
    bw, _bh = banner(lay, (0, 0), content["tagline_top"], f_eye, theme["primary"])
    _centred(bg, lay.crop((0, 0, bw, _bh)), int(W * 0.215))

    # wordmark — the loudest element on the image
    name = content["name"]
    f_word = display_font(content, name, int(W * 0.86), int(W * 0.115))
    tw, th, ox, oy = _text_size(f_word, name)
    sticker_text(bg, ((W - tw) // 2, int(W * 0.30)), name, f_word,
                 fill=theme["primary"], outline=(255, 255, 255), outline_w=11,
                 stroke=theme["ink"], stroke_w=5)

    # subtitle
    sub_y = int(W * 0.30) + th + int(W * 0.035)
    f_sub = _fit_font("Montserrat-Bold.otf", content["tagline_sub"],
                      int(W * 0.72), 46, 22)
    d = ImageDraw.Draw(bg)
    sw = f_sub.getbbox(content["tagline_sub"])[2]
    d.text(((W - sw) // 2, sub_y), content["tagline_sub"], font=f_sub,
           fill=theme["ink"])
    return bg


def overlay_clean(bg, content, theme):
    """No copy at all — just the brand mark, small, in the corner.

    A catalog hero sells by showing the product well, not by shouting over it.
    Banners, a wordmark and four bullets belong on the feature card, which is a
    different slot; putting them on every image is what made the whole set read
    as one template.
    """
    _logo_at(bg, 0.855, 0.038, 0.105)
    return bg


def overlay_hero_text(bg, content, theme):
    """Draw the headline banners, sticker wordmark, feature bullets, corner
    ribbon, side callout and brand logo. All text auto-shrinks to its zone so it
    never overlaps the product (centred right) or runs off-canvas."""
    x0, y0 = int(W * 0.05), int(W * 0.06)
    LEFT_W = int(W * 0.40)          # text column keeps clear of the product

    # --- headline banners (top-left) ---
    f_ban = _fit_font("Montserrat-ExtraBold.otf",
                      [content["tagline_top"], content["tagline_sub"]],
                      LEFT_W - 60 * SS, 46, 24)
    w1, h1 = banner(bg, (x0, y0), content["tagline_top"], f_ban, theme["primary"])
    banner(bg, (x0 + 12 * SS, y0 + h1 + 8 * SS), content["tagline_sub"], f_ban,
           theme["accent"])

    # --- sticker wordmark (fit to the left column) ---
    f_word = display_font(content, content["name"], LEFT_W, int(W * 0.13))
    sticker_text(bg, (x0, int(W * 0.24)), content["name"], f_word,
                 fill=theme["primary"], outline=(255, 255, 255), outline_w=10,
                 stroke=theme["ink"], stroke_w=4)

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


# A product wider than this relative to its height gets the poster treatment;
# anything taller reads better in the side-by-side column layout.
POSTER_ASPECT = 1.05


def choose_layout(cutout_path):
    """Pick a composition from the product's own proportions.

    Wide products (boxed sets, playsets, the plant dome) are squeezed to nothing
    beside a text column, and tall ones (scooters, figures) leave a poster's
    width empty. Deciding from the cutout means no per-SKU configuration.
    """
    with Image.open(cutout_path) as img:
        w, h = img.size
    return "poster" if h and (w / h) > POSTER_ASPECT else "side"


LAYOUTS = {
    #            cx     base_y  target_h  max_w   text renderer
    "side":   (0.71,   0.86,   0.66,     0.48,   overlay_hero_text),
    "poster": (0.50,   1.02,   0.58,     0.92,   overlay_poster_text),
    # No text, so the product gets the whole frame.
    "clean":  (0.50,   0.88,   0.64,     0.78,   overlay_clean),
}


def render_hero(cutout_path, content, out_path, background=None, layout=None):
    """Render a hero. If `background` (a PIL image) is given it's used as the
    scene (e.g. a Draw Things lifestyle background); otherwise a procedural
    studio background is generated. The real product cutout is always composited
    on top — the scene is never trusted to contain the product.

    `layout` is "side", "poster", or None to choose from the product's shape.
    """
    theme = {**THEME, **content.get("theme", {})}
    layout = layout or choose_layout(cutout_path)
    if layout not in LAYOUTS:
        raise ValueError(f"unknown layout {layout!r}; have {sorted(LAYOUTS)}")
    cx_f, base_f, targ_f, maxw_f, draw_text = LAYOUTS[layout]
    cx, base_y = int(W * cx_f), int(W * base_f)

    if background is None:
        bg = make_background(theme)
    else:
        bg = background.convert("RGBA").resize((W, W), Image.LANCZOS)

    bg = add_podium(bg, cx, base_y)
    cutout = Image.open(cutout_path).convert("RGBA")
    bg, _ = place_product(bg, cutout, cx, base_y,
                          target_h=int(W * targ_f), max_w=int(W * maxw_f))

    draw_text(bg, content, theme)
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
