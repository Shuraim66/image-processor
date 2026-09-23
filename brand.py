"""Store branding for marketing images.

The chip (logo + address in a navy pill, bottom left) plus a faint tiled wordmark.
Marketplace rule: the plain white main image stays CLEAN — Google Shopping and Meta
catalogue feeds reject product images carrying a watermark or logo. Only the marketing
shots (scene hero, cards, angles) get branded.
"""
import os

from PIL import Image, ImageDraw

import feature_card as fc
import make_hero as mh

SITE = "thetoygiftshop.com"
TILE_OPACITY = 26          # 0-255 over the picture; faint on purpose
CHIP_HEIGHT = 0.055        # fraction of the image width
MARGIN = 0.035


def _logo():
    return Image.open(mh.LOGO_PATH).convert("RGBA") if os.path.exists(mh.LOGO_PATH) else None


def tile_wordmark(im, opacity=TILE_OPACITY):
    """Shop name repeated across the picture — survives a crop, spoils a straight lift."""
    w = im.width
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    font = mh._font(fc.F_B, int(w * 0.021))
    step_y, step_x = int(w * 0.17), int(w * 0.36)
    for i, y in enumerate(range(0, im.height, step_y)):
        for x in range(-w, w * 2, step_x):
            d.text((x + (i % 2) * int(w * 0.18), y), "THE TOY GIFT SHOP", font=font,
                   fill=(255, 255, 255, opacity))
    im.alpha_composite(layer)


def chip(im):
    """Navy pill with the logo and the shop address, bottom left."""
    w = im.width
    h = int(w * CHIP_HEIGHT)
    font = mh._font(fc.F_M, int(h * 0.28))    # tied to h, not w, so it shrinks with CHIP_HEIGHT
    text_w = ImageDraw.Draw(im).textlength(SITE, font=font)
    logo = _logo()
    lw = int(h * 0.72)
    pad = int(h * 0.30)
    chip_w = int(lw + pad * 3 + text_w) if logo else int(pad * 2 + text_w)
    pill = Image.new("RGBA", (chip_w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(pill)
    d.rounded_rectangle([0, 0, chip_w, h], radius=h // 2, fill=fc.NAVY + (238,))
    x = pad
    if logo:
        l = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
        pill.alpha_composite(l, (pad, (h - l.height) // 2))
        x = pad * 2 + lw
    d.text((x, h / 2), SITE, font=font, fill=(255, 255, 255), anchor="lm")
    m = int(w * MARGIN)
    im.alpha_composite(pill, (m, im.height - h - m))


def corner_logo(im, opacity=0.9, width=0.12):
    logo = _logo()
    if not logo:
        return
    w = im.width
    lw = int(w * width)
    l = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
    l.putalpha(l.getchannel("A").point(lambda v: int(v * opacity)))
    im.alpha_composite(l, (w - lw - int(w * MARGIN), int(w * MARGIN)))


def apply(src, out=None, corner=True):
    """Brand one image: faint tile + chip (+ corner logo). Returns the written path."""
    im = Image.open(src).convert("RGBA")
    tile_wordmark(im)
    chip(im)
    if corner:
        corner_logo(im)
    out = out or src
    im.convert("RGB").save(out, quality=94)
    return out
