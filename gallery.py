#!/usr/bin/env python3
"""
Listing-gallery slots that build on make_hero.py's helpers (free / template).

Produces the non-hero, non-lifestyle slots of the 7-image set:
  5. feature infographic   render_infographic()
  6. size & age card       render_size_card()
  7. detail close-up       render_detail()

Slots 1-2 come from process_products.py (white catalog) and make_hero.py (hero);
slots 3-4 (lifestyle scenes) come from the ComfyUI background engine.
"""

import os
from PIL import Image, ImageDraw, ImageFilter
import make_hero as mh

W = mh.W          # supersampled work size
SS = mh.SS
SIZE = mh.SIZE


def _light_bg(theme):
    """Clean, brand-tinted background (softer than the hero's bg)."""
    bg = mh.make_background(theme)
    white = Image.new("RGBA", (W, W), (255, 255, 255, 130))
    return Image.alpha_composite(bg, white)   # wash it lighter for info slots


def _logo(bg, x_frac=0.85, y_frac=0.04, w_frac=0.12):
    if os.path.exists(mh.LOGO_PATH):
        logo = Image.open(mh.LOGO_PATH).convert("RGBA")
        lw = int(W * w_frac)
        logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
        bg.alpha_composite(logo, (int(W * x_frac), int(W * y_frac)))


def _dotted_line(d, p0, p1, color, r=4 * SS, gap=22 * SS):
    import math
    x0, y0 = p0; x1, y1 = p1
    dist = math.hypot(x1 - x0, y1 - y0)
    n = max(1, int(dist // gap))
    for i in range(n + 1):
        t = i / n
        x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        d.ellipse([x - r, y - r, x + r, y + r], fill=color)


# --------------------------------------------------------------------------- #
# Slot 5 — feature infographic
# --------------------------------------------------------------------------- #
def render_infographic(cutout_path, content, out_path):
    theme = {**mh.THEME, **content.get("theme", {})}
    bg = _light_bg(theme)

    # title
    f_title = mh._font("Montserrat-ExtraBold.otf", 52)
    mh.banner(bg, (int(W * 0.5), int(W * 0.05)),
              content.get("info_title", "WHY YOU'LL LOVE IT"),
              f_title, theme["ink"], anchor="left")

    # product centred
    cx, base_y = int(W * 0.5), int(W * 0.82)
    cutout = Image.open(cutout_path).convert("RGBA")
    bg = mh.place_product(bg, cutout, cx, base_y, target_h=int(W * 0.52))

    # four features: two left, two right, with dotted connectors
    f_feat = mh._font("Montserrat-Bold.otf", 34)
    r = int(W * 0.033)
    feats = content["features"][:4]
    slots = [(0.07, 0.40, "L"), (0.07, 0.62, "L"),
             (0.79, 0.40, "R"), (0.79, 0.62, "R")]
    for feat, (fx, fy, side) in zip(feats, slots):
        icx, icy = int(W * fx) + r, int(W * fy)
        col = theme["primary"] if (fx < 0.5) else theme["accent"]
        d = ImageDraw.Draw(bg)
        anchor = (icx + r, icy) if side == "L" else (icx - r, icy)
        _dotted_line(d, anchor, (cx + (-int(W*0.16) if side=="L" else int(W*0.16)), icy),
                     (*theme["ink"], 120))
        mh.draw_feature_icon(bg, icx, icy, r, feat["icon"], col)
        lines = feat["label"].split("\n")
        tx = icx + 2 * r if side == "L" else icx - 2 * r
        ty = icy - (len(lines) * 42 * SS) // 2
        for ln in lines:
            wln = f_feat.getbbox(ln)[2]
            d.text((tx if side == "L" else tx - wln, ty), ln, font=f_feat, fill=theme["ink"])
            ty += 44 * SS

    _logo(bg, x_frac=0.86, y_frac=0.035)
    bg.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS).save(out_path, quality=94)
    return out_path


# --------------------------------------------------------------------------- #
# Slot 6 — size & age card
# --------------------------------------------------------------------------- #
def render_size_card(cutout_path, specs, out_path):
    """specs = {height, length, badges:[...], theme?} — PLACEHOLDER numbers until
    you supply real supplier dimensions per SKU."""
    theme = {**mh.THEME, **specs.get("theme", {})}
    bg = _light_bg(theme)

    f_title = mh._font("Montserrat-ExtraBold.otf", 52)
    mh.banner(bg, (int(W * 0.5), int(W * 0.05)), specs.get("title", "SIZE & SPECS"),
              f_title, theme["ink"])

    cx, base_y = int(W * 0.52), int(W * 0.74)
    cutout = Image.open(cutout_path).convert("RGBA")
    scale = int(W * 0.5) / cutout.height
    prod = cutout.resize((int(cutout.width * scale), int(W * 0.5)), Image.LANCZOS)
    px, py = cx - prod.width // 2, base_y - prod.height
    bg.alpha_composite(prod, (px, py))

    d = ImageDraw.Draw(bg)
    f_dim = mh._font("Montserrat-Bold.otf", 38)
    ink = theme["ink"]
    aw = 6 * SS

    def arrow(p0, p1):
        d.line([p0, p1], fill=ink, width=aw)
        import math
        for end, other in ((p0, p1), (p1, p0)):
            ang = math.atan2(other[1]-end[1], other[0]-end[0])
            for da in (-0.5, 0.5):
                d.line([end, (end[0]+22*SS*math.cos(ang+da),
                              end[1]+22*SS*math.sin(ang+da))], fill=ink, width=aw)

    # height (left), length (bottom)
    hx = px - int(W * 0.06)
    arrow((hx, py), (hx, py + prod.height))
    d.text((hx - int(W*0.11), (py + py + prod.height)//2 - 20*SS),
           specs.get("height", "≈ 65 cm"), font=f_dim, fill=ink)
    ly = py + prod.height + int(W * 0.03)
    arrow((px, ly), (px + prod.width, ly))
    lw = f_dim.getbbox(specs.get("length", "≈ 55 cm"))[2]
    d.text((cx - lw//2, ly + 10*SS), specs.get("length", "≈ 55 cm"), font=f_dim, fill=ink)

    # spec chips row
    f_chip = mh._font("Montserrat-ExtraBold.otf", 30)
    badges = specs.get("badges", ["AGE 3+", "MAX 50 KG", "FOLDABLE", "LED WHEELS"])
    n = len(badges); chip_w = int(W * 0.2); gapx = int(W * 0.015)
    total = n * chip_w + (n - 1) * gapx
    sx = (W - total) // 2; cy = int(W * 0.9)
    for i, b in enumerate(badges):
        x = sx + i * (chip_w + gapx)
        col = theme["primary"] if i % 2 == 0 else theme["accent"]
        d.rounded_rectangle([x, cy, x + chip_w, cy + int(W*0.06)], radius=18*SS, fill=col)
        bw = f_chip.getbbox(b)[2]
        d.text((x + (chip_w - bw)//2, cy + int(W*0.014)), b, font=f_chip, fill=(255,255,255))

    _logo(bg, x_frac=0.86, y_frac=0.035)
    bg.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS).save(out_path, quality=94)
    return out_path


# --------------------------------------------------------------------------- #
# Slot 7 — detail close-up
# --------------------------------------------------------------------------- #
def render_detail(original_path, crop_frac, label, content, out_path):
    """crop_frac = (left, top, right, bottom) as fractions of the original photo."""
    theme = {**mh.THEME, **content.get("theme", {})}
    bg = _light_bg(theme)

    src = Image.open(original_path).convert("RGB")
    w, h = src.size
    l, t, rr, b = crop_frac
    crop = src.crop((int(l*w), int(t*h), int(rr*w), int(b*h)))
    # square-ish card
    card = int(W * 0.62)
    cs = min(crop.size)
    crop = crop.crop(((crop.width-cs)//2, (crop.height-cs)//2,
                      (crop.width+cs)//2, (crop.height+cs)//2)).resize((card, card), Image.LANCZOS)
    # rounded frame with border
    mask = Image.new("L", (card, card), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, card, card], radius=40*SS, fill=255)
    fx, fy = (W - card)//2, int(W*0.2)
    # soft shadow behind card
    sh = Image.new("RGBA", (W, W), (0,0,0,0))
    ImageDraw.Draw(sh).rounded_rectangle([fx, fy, fx+card, fy+card], radius=40*SS,
                                         fill=(30,45,80,90))
    sh = sh.filter(ImageFilter.GaussianBlur(26*SS)); bg.alpha_composite(sh)
    bg.paste(crop, (fx, fy), mask)
    d = ImageDraw.Draw(bg)
    d.rounded_rectangle([fx, fy, fx+card, fy+card], radius=40*SS,
                        outline=theme["primary"], width=10*SS)

    # label banner + caption
    f_lab = mh._font("Montserrat-ExtraBold.otf", 48)
    mh.banner(bg, (int(W*0.5), int(W*0.055)), label, f_lab, theme["accent"])
    if content.get("detail_caption"):
        f_cap = mh._font("Montserrat-SemiBold.otf", 32)
        cap = content["detail_caption"]
        cw = f_cap.getbbox(cap)[2]
        d.text(((W - cw)//2, fy + card + int(W*0.03)), cap, font=f_cap, fill=theme["ink"])

    _logo(bg, x_frac=0.86, y_frac=0.035)
    bg.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS).save(out_path, quality=94)
    return out_path


if __name__ == "__main__":
    content = mh.demo_content()
    content["info_title"] = "WHY KIDS LOVE IT"
    content["detail_caption"] = "Flashing LED wheels light up as they roll"
    cut = "hero/SCOOTER-LED-PINK_cutout.png"
    render_infographic(cut, content, "hero/SCOOTER-LED-PINK_infographic.jpg")
    render_size_card(cut, {
        "height": "≈ 66 cm", "length": "≈ 56 cm",
        "badges": ["AGE 3+", "MAX 50 KG", "FOLDABLE", "LED WHEELS"],
        "theme": content["theme"],
    }, "hero/SCOOTER-LED-PINK_size.jpg")
    render_detail("input/SCOOTER-LED-PINK/front.jpg", (0.30, 0.62, 0.85, 1.0),
                  "LIGHT-UP WHEELS", content, "hero/SCOOTER-LED-PINK_detail.jpg")
    print("wrote infographic, size, detail")
