#!/usr/bin/env python3
"""
FeatureCard V2 — a GPT-style feature infographic, built truthfully.

Matches the dense GPT layout (headline + subhead + 4 icon features + a row of
detail thumbnails + a trust bar) but: text is rendered by us (always correct),
thumbnails are REAL crops of the product's own photos (never fabricated), and
colors auto-match the product via make_hero.derive_theme.

    render_v2(hero_photo, thumbs, content, out_path)
"""

import math
import os
from PIL import Image, ImageDraw, ImageFilter
import make_hero as mh
import process_products as pp

W, SS, SIZE = mh.W, mh.SS, mh.SIZE


# ---------- small helpers ----------------------------------------------------
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


def _icon(d, cx, cy, r, kind, col):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    w = (255, 255, 255, 255); lw = max(3, r // 9)
    if kind == "bulb":
        d.ellipse([cx - r*0.4, cy - r*0.5, cx + r*0.4, cy + r*0.3], outline=w, width=lw)
        d.rectangle([cx - r*0.18, cy + r*0.2, cx + r*0.18, cy + r*0.45], fill=w)
    elif kind == "shield":
        d.polygon([(cx, cy-r*0.55), (cx+r*0.45, cy-r*0.25), (cx+r*0.45, cy+r*0.15),
                   (cx, cy+r*0.6), (cx-r*0.45, cy+r*0.15), (cx-r*0.45, cy-r*0.25)], fill=w)
        d.line([(cx-r*0.18, cy+r*0.02), (cx-r*0.02, cy+r*0.22), (cx+r*0.28, cy-r*0.22)],
               fill=col, width=lw)
    elif kind == "smiley":
        d.ellipse([cx-r*0.55, cy-r*0.55, cx+r*0.55, cy+r*0.55], outline=w, width=lw)
        for ex in (-0.22, 0.22):
            d.ellipse([cx+r*ex-r*0.07, cy-r*0.2-r*0.07, cx+r*ex+r*0.07, cy-r*0.2+r*0.07], fill=w)
        d.arc([cx-r*0.3, cy-r*0.25, cx+r*0.3, cy+r*0.3], 20, 160, fill=w, width=lw)
    elif kind == "gift":
        d.rectangle([cx-r*0.42, cy-r*0.15, cx+r*0.42, cy+r*0.45], outline=w, width=lw)
        d.line([(cx, cy-r*0.15), (cx, cy+r*0.45)], fill=w, width=lw)
        d.line([(cx-r*0.45, cy), (cx+r*0.45, cy)], fill=w, width=lw)
    elif kind == "hand":
        d.rounded_rectangle([cx-r*0.3, cy-r*0.4, cx+r*0.3, cy+r*0.45], radius=r*0.15,
                            outline=w, width=lw)
    else:  # dot
        d.ellipse([cx-r*0.2, cy-r*0.2, cx+r*0.2, cy+r*0.2], fill=w)


def _rounded_thumb(img, size, rad):
    img = img.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size, size], radius=rad, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


# ---------- main -------------------------------------------------------------
def render_v2(hero_photo, thumbs, content, out_path, theme=None, scene=None):
    theme = theme or mh.derive_theme(hero_photo)
    prim, acc, ink = theme["primary"], theme["accent"], theme["ink"]

    if scene:
        # "classic" backdrop: heavily blur a scene render into an abstract warm
        # wash (its product dissolves) so text stays readable on top.
        sc = Image.open(scene).convert("RGB").resize((W, W)).filter(ImageFilter.GaussianBlur(70 * SS))
        wash = Image.new("RGB", (W, W), (250, 248, 245))
        bg = Image.blend(sc, wash, 0.58).convert("RGBA")
    else:
        # themed soft gradient
        bg = Image.new("RGB", (W, W), (250, 249, 252))
        grad = Image.new("L", (1, W))
        for y in range(W):
            grad.putpixel((0, y), int(70 * (1 - y / W)))
        tint = Image.new("RGB", (W, W), tuple(min(255, c + 40) for c in prim))
        bg = Image.composite(tint, bg, grad.resize((W, W))).convert("RGBA")
    d = ImageDraw.Draw(bg)

    # hero product (real cutout) — fit inside a box on the RIGHT so wide products
    # never intrude on the headline/features column on the left.
    cut = pp.trim_to_content(pp.remove_background(Image.open(hero_photo).convert("RGBA")))
    zone_l, zone_t = int(W * 0.47), int(W * 0.14)
    box_w, box_h = int(W * 0.51), int(W * 0.50)   # large right zone the product fills
    scale = min(box_w / cut.width, box_h / cut.height)
    cut = cut.resize((max(1, int(cut.width * scale)), max(1, int(cut.height * scale))), Image.LANCZOS)
    hx = zone_l + (box_w - cut.width) // 2
    hy = zone_t + (box_h - cut.height) // 2
    sh = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    sil = Image.new("RGBA", cut.size, ink + (0,)); sil.putalpha(cut.getchannel("A").point(lambda a: 90 if a else 0))
    sh.paste(sil, (hx + 10*SS, hy + 16*SS), sil); bg.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18*SS)))
    bg.alpha_composite(cut, (hx, hy))

    x0 = int(W * 0.05); LEFT = int(W * 0.40)   # text column, kept clear of the product
    y = int(W * 0.05)
    # product name eyebrow (Montserrat)
    if content.get("name"):
        f_n = mh._fit_font("Montserrat-ExtraBold.otf", content["name"].upper(), LEFT, 32, 18)
        d.text((x0, y), content["name"].upper(), font=f_n, fill=acc); y += int(48*SS)
    # headline (2 lines) — Poppins ExtraBold: strong, clean, friendly, versatile
    f_h = mh._fit_font("Poppins-ExtraBold.ttf", [content["headline_top"], content["headline_accent"]],
                       LEFT, 84, 40)
    lh = int(sum(f_h.getmetrics()) * 0.98)
    d.text((x0, y), content["headline_top"], font=f_h, fill=ink)
    d.text((x0, y + lh), content["headline_accent"], font=f_h, fill=acc)
    y += 2*lh + int(20*SS)
    # subhead (Poppins — a second family for contrast)
    f_s = mh._font("Poppins-SemiBold.ttf", 30)
    for ln in _wrap(d, content["subhead"], f_s, LEFT):
        d.text((x0, y), ln, font=f_s, fill=ink); y += int(40*SS)

    # 4 features (left), evenly spaced with breathing room
    f_ft = mh._font("Montserrat-ExtraBold.otf", 30)
    f_fd = mh._font("Montserrat-SemiBold.otf", 24)
    r = int(W * 0.028); fy = int(W * 0.37); step = int(W * 0.088)
    tx = x0 + 2*r + 22*SS
    for i, ft in enumerate(content["features"][:4]):
        cy = fy + i * step; col = prim if i % 2 == 0 else acc
        _icon(d, x0 + r, cy, r, ft["icon"], col)
        d.text((tx, cy - int(36*SS)), ft["title"], font=f_ft, fill=col)
        for j, ln in enumerate(_wrap(d, ft["desc"], f_fd, LEFT - (2*r + 22*SS))):
            d.text((tx, cy + int((4 + j*30)*SS)), ln, font=f_fd, fill=ink)

    # thumbnail row (real crops)
    n = len(thumbs); pad = int(W*0.02); tw = int((W - 2*x0 - (n-1)*pad) / n)
    ty = int(W * 0.69); f_c = mh._font("Montserrat-Bold.otf", 24)
    for i, t in enumerate(thumbs):
        src = Image.open(t["photo"]).convert("RGB")
        l, tp, rr, b = t["crop"]; iw, ih = src.size
        crop = src.crop((int(l*iw), int(tp*ih), int(rr*iw), int(b*ih)))
        cs = min(crop.size); crop = crop.crop(((crop.width-cs)//2, (crop.height-cs)//2,
                                               (crop.width+cs)//2, (crop.height+cs)//2))
        thumb = _rounded_thumb(crop, tw, int(24*SS))
        tx = x0 + i*(tw+pad); bg.alpha_composite(thumb, (tx, ty))
        d.rounded_rectangle([tx, ty, tx+tw, ty+tw], radius=int(24*SS), outline=prim, width=int(4*SS))
        cw = d.textlength(t["caption"], font=f_c)
        d.text((tx + (tw-cw)//2, ty + tw + int(8*SS)), t["caption"], font=f_c, fill=ink)

    # trust bar (optional)
    if content.get("trust"):
        by0 = int(W * 0.90); d.rectangle([0, by0, W, W], fill=prim)
        f_b = mh._font("Montserrat-ExtraBold.otf", 28)
        m = len(content["trust"]); seg = W / m
        for i, tb in enumerate(content["trust"]):
            bw = d.textlength(tb, font=f_b)
            d.text((seg*i + (seg-bw)//2, by0 + int(0.03*W)), tb, font=f_b, fill=(255, 255, 255))

    # logo watermark
    if os.path.exists(mh.LOGO_PATH):
        logo = Image.open(mh.LOGO_PATH).convert("RGBA"); lw = int(W*0.11)
        logo = logo.resize((lw, int(logo.height*lw/logo.width)), Image.LANCZOS)
        bg.alpha_composite(logo, (int(W*0.86), int(W*0.035)))

    bg.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS).save(out_path, quality=94)
    return out_path


def render_hero_title(product_photo, content, out_path, theme=None, scene=None):
    """Store-style titled hero: eyebrow pill + big outlined 'sticker' title +
    subhead centered on top, product below, logo top-left + round badge top-right.
    Colors auto-match the product."""
    theme = theme or mh.derive_theme(product_photo)
    prim, acc, ink = theme["primary"], theme["accent"], theme["ink"]

    if scene and os.path.exists(scene):
        sc = Image.open(scene).convert("RGB").resize((W, W)).filter(ImageFilter.GaussianBlur(70 * SS))
        bg = Image.blend(sc, Image.new("RGB", (W, W), (250, 249, 246)), 0.5).convert("RGBA")
    else:
        bg = Image.new("RGB", (W, W), (250, 249, 246))
        grad = Image.new("L", (1, W))
        for yy in range(W):
            grad.putpixel((0, yy), int(60 * (1 - yy / W)))
        tint = Image.new("RGB", (W, W), tuple(min(255, c + 65) for c in prim))
        bg = Image.composite(tint, bg, grad.resize((W, W))).convert("RGBA")
    d = ImageDraw.Draw(bg)

    # product cutout, bottom-centre
    cut = pp.trim_to_content(pp.remove_background(Image.open(product_photo).convert("RGBA")))
    s = min(int(W * 0.80) / cut.width, int(W * 0.50) / cut.height)
    cut = cut.resize((max(1, int(cut.width * s)), max(1, int(cut.height * s))), Image.LANCZOS)
    px, py = (W - cut.width) // 2, int(W * 0.97) - cut.height
    sh = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    sil = Image.new("RGBA", cut.size, ink + (0,)); sil.putalpha(cut.getchannel("A").point(lambda a: 80 if a else 0))
    sh.paste(sil, (px + 8 * SS, py + 14 * SS), sil); bg.alpha_composite(sh.filter(ImageFilter.GaussianBlur(20 * SS)))
    bg.alpha_composite(cut, (px, py))

    y = int(W * 0.20)   # title block sits BELOW the logo/badge row (no overlap)
    # eyebrow pill (centred)
    if content.get("eyebrow"):
        f_e = mh._font("Montserrat-ExtraBold.otf", 30)
        tw = d.textlength(content["eyebrow"], font=f_e); bw, bh = int(tw + 56 * SS), int(66 * SS)
        bx = (W - bw) // 2
        d.rounded_rectangle([bx, y, bx + bw, y + bh], radius=bh // 2, fill=acc)
        d.text((bx + (bw - tw) // 2, y + int(15 * SS)), content["eyebrow"], font=f_e, fill=(255, 255, 255))
        y += bh + int(22 * SS)
    # big outlined sticker title (centred, rounded Baloo)
    title = content["title"].upper()
    f_t = mh._fit_font("Baloo2-ExtraBold.ttf", title, int(W * 0.86), 100, 44)
    tw, th, ox, oy = mh._text_size(f_t, title)
    mh.sticker_text(bg, ((W - tw) // 2, y), title, f_t, fill=prim, outline=(255, 255, 255), outline_w=14)
    y += th + int(46 * SS)
    # subhead (centred)
    if content.get("subhead2"):
        f_s = mh._font("Poppins-ExtraBold.ttf", 34); sw = d.textlength(content["subhead2"], font=f_s)
        d.text(((W - sw) // 2, y), content["subhead2"], font=f_s, fill=ink)

    # logo top-left
    if os.path.exists(mh.LOGO_PATH):
        logo = Image.open(mh.LOGO_PATH).convert("RGBA"); lw = int(W * 0.13)
        logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
        bg.alpha_composite(logo, (int(W * 0.045), int(W * 0.04)))
    # round badge top-right
    if content.get("badge"):
        bd = int(W * 0.145); bx, by = int(W * 0.81), int(W * 0.035)
        d.ellipse([bx, by, bx + bd, by + bd], fill=prim)
        f_b = mh._font("Montserrat-ExtraBold.otf", 27); lines = content["badge"].split()
        ty = by + bd // 2 - len(lines) * int(19 * SS)
        for ln in lines:
            lw2 = d.textlength(ln, font=f_b); d.text((bx + (bd - lw2) // 2, ty), ln, font=f_b, fill=(255, 255, 255)); ty += int(38 * SS)

    bg.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS).save(out_path, quality=94)
    return out_path
