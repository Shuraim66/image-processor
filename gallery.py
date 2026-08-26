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
    title = content.get("info_title", "WHY YOU'LL LOVE IT")
    f_title = mh.display_font(content, title, int(W * 0.52), int(W * 0.05))
    mh.banner(bg, (int(W * 0.5), int(W * 0.05)), title,
              f_title, theme["ink"], anchor="center")

    # Product centred, width-capped so it cannot grow into the label columns.
    cx, base_y = int(W * 0.5), int(W * 0.78)
    cutout = Image.open(cutout_path).convert("RGBA")
    bg, (px, py, pw, ph) = mh.place_product(bg, cutout, cx, base_y,
                                            target_h=int(W * 0.52),
                                            max_w=int(W * 0.30))

    # Four features: two left, two right, with dotted connectors. Labels are
    # fitted to the gap that is actually left between their icon and the
    # product, so a long feature name shrinks instead of running over the toy.
    r = int(W * 0.030)
    gutter = int(W * 0.02)
    feats = content["features"][:4]
    # Mirrored about the centre: the right icons previously sat 0.03W further in
    # than the left ones, so right-hand labels got a narrower budget and shrank
    # more, which read as a rendering fault rather than a choice.
    slots = [(0.045, 0.40, "L"), (0.045, 0.62, "L"),
             (0.895, 0.40, "R"), (0.895, 0.62, "R")]
    for feat, (fx, fy, side) in zip(feats, slots):
        icx, icy = int(W * fx) + r, int(W * fy)
        col = theme["primary"] if side == "L" else theme["accent"]
        d = ImageDraw.Draw(bg)
        lines = feat["label"].split("\n")

        if side == "L":
            tx = icx + 2 * r
            avail = max(int(W * 0.08), px - tx - gutter)
        else:
            tx = icx - 2 * r
            avail = max(int(W * 0.08), tx - (px + pw) - gutter)

        ff = mh._fit_font("Montserrat-Bold.otf", lines, avail, 34, 22)
        text_w = max(ff.getbbox(ln)[2] for ln in lines)

        # Connector runs from the END of the label to the product, not from the
        # icon — drawn from the icon it passed straight through the words.
        pad = int(W * 0.012)
        if side == "L":
            start, end = tx + text_w + pad, px - gutter // 2
        else:
            start, end = tx - text_w - pad, px + pw + gutter // 2
        if abs(end - start) > pad:
            _dotted_line(d, (start, icy), (end, icy), (*theme["ink"], 120))

        mh.draw_feature_icon(bg, icx, icy, r, feat["icon"], col)

        asc, desc = ff.getmetrics()
        lh = asc + desc
        ty = icy - (len(lines) * lh) // 2
        for ln in lines:
            wln = ff.getbbox(ln)[2]
            d.text((tx if side == "L" else tx - wln, ty), ln, font=ff, fill=theme["ink"])
            ty += lh

    _logo(bg, x_frac=0.86, y_frac=0.035)
    bg.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS).save(out_path, quality=94)
    return out_path


# --------------------------------------------------------------------------- #
# Slot 3 — every angle
# --------------------------------------------------------------------------- #
def render_angles(cutout_paths, content, out_path, title="EVERY ANGLE"):
    """A grid of the product's other shots, cut out and set on cards.

    The one slot that answers "what does it actually look like from the side" —
    and the reason to shoot more than one photo. Two shots go side by side, three
    or four into a 2x2; each card is sized to its own cutout so a tall product
    and a wide one both sit properly in their cell.
    """
    theme = {**mh.THEME, **content.get("theme", {})}
    bg = _light_bg(theme)

    f_title = mh.display_font(content, title, int(W * 0.52), int(W * 0.05))
    mh.banner(bg, (int(W * 0.5), int(W * 0.05)), title, f_title, theme["ink"],
              anchor="center")

    paths = cutout_paths[:4]
    if not paths:
        raise ValueError("render_angles needs at least one cutout")
    cols = 1 if len(paths) == 1 else 2
    rows = 1 if len(paths) <= 2 else 2

    top, span = int(W * 0.17), int(W * 0.74)
    cell_w, cell_h = span // cols, span // rows
    pad = int(W * 0.018)
    d = ImageDraw.Draw(bg)

    for i, path in enumerate(paths):
        cx = (W - cols * cell_w) // 2 + (i % cols) * cell_w
        cy = top + (i // cols) * cell_h
        card = [cx + pad, cy + pad, cx + cell_w - pad, cy + cell_h - pad]

        shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(card, radius=int(W * 0.02),
                                                 fill=(30, 45, 80, 60))
        bg.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(int(W * 0.008))))
        d.rounded_rectangle(card, radius=int(W * 0.02), fill=(255, 255, 255, 235))

        inner_w = int((card[2] - card[0]) * 0.80)
        inner_h = int((card[3] - card[1]) * 0.80)
        with Image.open(path) as raw:
            shot = raw.convert("RGBA")
        scale = min(inner_w / shot.width, inner_h / shot.height)
        shot = shot.resize((max(1, int(shot.width * scale)),
                            max(1, int(shot.height * scale))), Image.LANCZOS)
        bg.alpha_composite(shot, (int((card[0] + card[2]) / 2 - shot.width / 2),
                                  int((card[1] + card[3]) / 2 - shot.height / 2)))

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

    title = specs.get("title", "SIZE & SPECS")
    f_title = mh.display_font(specs, title, int(W * 0.52), int(W * 0.05))
    mh.banner(bg, (int(W * 0.5), int(W * 0.05)), title, f_title, theme["ink"],
              anchor="center")

    cx, base_y = int(W * 0.52), int(W * 0.74)
    cutout = Image.open(cutout_path).convert("RGBA")
    scale = min(int(W * 0.5) / cutout.height, int(W * 0.5) / cutout.width)
    prod = cutout.resize((max(1, int(cutout.width * scale)),
                          max(1, int(cutout.height * scale))), Image.LANCZOS)
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
def auto_detail_crop(original_path, product_box, window=0.42):
    """Pick the most detailed square inside the product. -> crop fractions.

    The alternative was a per-SKU constant, which meant a crop tuned for a
    scooter's wheels pointed at bare table on everything else. Scoring by
    gradient energy inside the product's own bounding box lands on whatever
    actually has texture — a face, a lit panel, a printed logo.
    """
    import numpy as np

    with Image.open(original_path) as img:
        w, h = img.size
        grey = np.asarray(img.convert("L").resize((160, 160), Image.BILINEAR), float)

    gy, gx = np.gradient(grey)
    energy = np.hypot(gx, gy)

    l, t, r, b = product_box if product_box else (0, 0, w, h)
    # product box in the 160x160 scoring space, clamped to something usable
    sl, st = int(l / w * 160), int(t / h * 160)
    sr, sb = max(sl + 8, int(r / w * 160)), max(st + 8, int(b / h * 160))

    side = max(8, int(min(sr - sl, sb - st) * window))
    best, best_at = -1.0, (sl, st)
    for yy in range(st, max(st + 1, sb - side), max(2, side // 4)):
        for xx in range(sl, max(sl + 1, sr - side), max(2, side // 4)):
            score = energy[yy:yy + side, xx:xx + side].mean()
            if score > best:
                best, best_at = score, (xx, yy)

    x0, y0 = best_at
    return (x0 / 160, y0 / 160, (x0 + side) / 160, (y0 + side) / 160)


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
    f_lab = mh.display_font(content, label, int(W * 0.52), int(W * 0.05))
    mh.banner(bg, (int(W*0.5), int(W*0.055)), label, f_lab, theme["accent"],
              anchor="center")
    if content.get("detail_caption"):
        f_cap, cap_lines = mh.fit_wrapped("Montserrat-SemiBold.otf",
                                          content["detail_caption"],
                                          int(W * 0.84), 34, 18, max_lines=2)
        asc, desc = f_cap.getmetrics()
        ty = fy + card + int(W * 0.03)
        for ln in cap_lines:
            cw = f_cap.getbbox(ln)[2]
            d.text(((W - cw) // 2, ty), ln, font=f_cap, fill=theme["ink"])
            ty += asc + desc

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
