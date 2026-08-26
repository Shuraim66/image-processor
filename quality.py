#!/usr/bin/env python3
"""
Deterministic quality checks for a product's generated gallery.

Fast, local, no model — validates the images are the right size, not blank, and
that the marketplace "main" image has a pure-white background. Writes a
quality-report.json per product. (The VLM-based semantic check — does the image
match the product — is step 6, layered on top of this.)
"""

import hashlib
import os

import numpy as np
from PIL import Image, ImageStat

import slots

IMG_EXTS = (".webp", ".jpg", ".jpeg", ".png")

LOGO_PATH = "logo.png"

# The brand mark is a locked master asset: it is never regenerated, recoloured or
# redrawn. Pin its hash so a swapped or re-exported file is caught rather than
# silently shipped across a whole batch. Override when the logo is legitimately
# reissued.
EXPECTED_LOGO_SHA256 = os.environ.get(
    "TTGS_LOGO_SHA256",
    "0557751c3b03f7407e772857f07bd3670dc4d66668d0f400729c565b0888c1da")

# Every (x_frac, y_frac, w_frac) any layout anchors the mark at: top-right for the
# hero and card slots, top-left for the poster composition.
LOGO_ANCHORS = ((0.86, 0.035, 0.12), (0.855, 0.038, 0.105),
                (0.85, 0.04, 0.13), (0.04, 0.035, 0.13))

# Mean alpha-weighted channel difference from drawing the logo again at its anchor.
# Redrawing a mark that is already there changes almost nothing; drawing one onto
# bare background changes a lot. Measured across the catalogue: 10-34 present,
# 222-330 absent, so the gap either side of this threshold is an order of magnitude.
LOGO_RESIDUAL_MAX = 120


def _stddev(img):
    return ImageStat.Stat(img.convert("L")).stddev[0]


def _corner_means(img, s=14):
    w, h = img.size
    px = img.load()
    out = []
    for cx, cy in [(0, 0), (w - s, 0), (0, h - s), (w - s, h - s)]:
        vals = [px[cx + i, cy + j] for i in range(s) for j in range(s)]
        out.append(sum(sum(v[:3]) for v in vals) / (len(vals) * 3))
    return out


def logo_sha256():
    """SHA-256 of the brand asset, or None when it is missing."""
    if not os.path.exists(LOGO_PATH):
        return None
    with open(LOGO_PATH, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def check_watermark_asset():
    """Is the brand master itself the file we expect?"""
    got = logo_sha256()
    if got is None:
        return {"check": "watermark_asset", "status": "fail",
                "detail": f"FAIL_BRAND_ASSET: no logo at '{LOGO_PATH}'"}
    if got != EXPECTED_LOGO_SHA256:
        return {"check": "watermark_asset", "status": "fail",
                "detail": f"FAIL_BRAND_ASSET: {LOGO_PATH} is sha256:{got[:12]}…, "
                          f"expected {EXPECTED_LOGO_SHA256[:12]}…"}
    return {"check": "watermark_asset", "status": "pass",
            "detail": f"sha256:{got[:12]}…"}


def logo_residual(path):
    """How much re-drawing the brand mark at its anchor would change the image.

    Low means the mark is already there. Rather than hunt for the logo in the
    pixels — which a busy hero background defeats — this asks the one question
    that matters and answers it exactly.
    """
    im = Image.open(path).convert("RGB")
    W, H = im.size
    master = Image.open(LOGO_PATH).convert("RGBA")
    best = float("inf")
    for x_frac, y_frac, w_frac in LOGO_ANCHORS:
        lw = int(W * w_frac)
        logo = master.resize((lw, max(1, int(master.height * lw / master.width))),
                             Image.LANCZOS)
        x, y = int(W * x_frac), int(W * y_frac)
        if x + logo.width > W or y + logo.height > H:
            continue
        before = im.crop((x, y, x + logo.width, y + logo.height))
        after = before.copy()
        after.paste(logo, (0, 0), logo)
        alpha = np.asarray(logo.getchannel("A"), np.float32)[..., None] / 255.0
        weight = alpha.sum()
        if weight < 1:
            continue
        diff = np.abs(np.asarray(before, np.float32) - np.asarray(after, np.float32))
        best = min(best, float((diff * alpha).sum() / weight))
    return best


def check_watermark(path, slot):
    """Branded slots must carry the mark; marketplace slots must not.

    The absence check is not cosmetic: Google Merchant Center disapproves product
    images with a watermark or logo, so a mark creeping onto white-background
    would quietly cost the whole feed.
    """
    must_have = slot in slots.BRANDED_SLOTS
    if not must_have and slot not in slots.CLEAN_SLOTS:
        return None                                  # unknown slot, nothing to assert
    if not os.path.exists(LOGO_PATH):
        return {"check": "watermark", "status": "fail",
                "detail": f"cannot verify: no logo at '{LOGO_PATH}'"}

    r = logo_residual(path)
    present = r <= LOGO_RESIDUAL_MAX
    ok = present if must_have else not present
    want = "required" if must_have else "must stay clean for marketplace rules"
    return {"check": "watermark",
            "status": "pass" if ok else "fail",
            "detail": f"{'present' if present else 'absent'} "
                      f"(residual {r:.0f}, {want})"}


def check_image(path, slot):
    checks = []
    is_main = slot == "white-background"
    img = Image.open(path).convert("RGB")

    w, h = img.size
    square_hires = (w == h) and w >= 1000        # square + marketplace-usable
    checks.append({"check": "dimensions",
                   "status": "pass" if square_hires else "warn",
                   "detail": f"{w}x{h}" + ("" if square_hires else " (want square >=1000)")})

    sd = _stddev(img)
    checks.append({"check": "not_blank",
                   "status": "pass" if sd > 5 else "fail",
                   "detail": f"stddev={sd:.1f}"})

    if is_main:
        means = _corner_means(img)
        white = all(m > 245 for m in means)
        checks.append({"check": "pure_white_bg",
                       "status": "pass" if white else "warn",
                       "detail": f"corner_means={[round(m) for m in means]}"})

    wm = check_watermark(path, slot)
    if wm:
        checks.append(wm)
    return checks


# The product fills roughly this much of the hero canvas, so a cutout shorter
# than SIZE * this on its longest side gets upscaled and looks soft.
PRODUCT_FILL = 0.66


def check_source(cutout_path, render_size):
    """Is there enough real detail in the photo to fill the canvas sharply?"""
    with Image.open(cutout_path) as cut:
        longest = max(cut.size)
    needed = int(render_size * PRODUCT_FILL)
    scale = needed / longest
    status = "pass" if scale <= 1.0 else ("warn" if scale <= 1.35 else "fail")
    detail = f"cutout {cut.size[0]}x{cut.size[1]}, needs {needed}px -> x{scale:.2f}"
    if status != "pass":
        detail += " (source photo too small; re-shoot at full resolution)"
    return {"check": "source_resolution", "status": status, "detail": detail}


def check_gallery(sku, out_dir, cutout_path=None, copy_source="", copy_flags=(),
                  render_size=1600, order_key=None):
    report = {"sku": sku, "status": "pass", "copy_source": copy_source,
              "copy_flags": list(copy_flags), "images": []}
    if copy_flags:
        report["status"] = "review"
    if copy_source.startswith("fallback"):
        report["status"] = "review"
        report["note"] = f"copy is placeholder text ({copy_source}) — not written by the model"
    asset = check_watermark_asset()
    report["watermark_asset"] = asset
    if asset["status"] == "fail":
        report["status"] = "review"

    files = [f for f in os.listdir(out_dir) if f.lower().endswith(IMG_EXTS)]
    files.sort(key=order_key or (lambda n: n))
    for f in files:
        try:
            checks = check_image(os.path.join(out_dir, f), slots.slot_name(f))
        except Exception as exc:  # noqa: BLE001
            checks = [{"check": "open", "status": "fail", "detail": str(exc)}]
        if any(c["status"] == "fail" for c in checks):
            report["status"] = "review"
        report["images"].append({"image": f, "checks": checks})

    if cutout_path and os.path.exists(cutout_path):
        src = check_source(cutout_path, render_size)
        report["source"] = src
        if src["status"] == "fail":
            report["status"] = "review"
        cut = Image.open(cutout_path)
        if cut.mode == "RGBA":
            h = cut.getchannel("A").histogram()          # opaque-pixel fraction
            opaque = sum(h[11:])
            frac = opaque / float(sum(h)) if sum(h) else 0.0
            report["cutout_coverage"] = round(frac, 3)
            if frac < 0.05:                              # product almost entirely removed
                report["status"] = "review"
                report.setdefault("note", "cutout nearly empty — background removal may have failed")
            elif frac > 0.97:                            # nothing removed — likely kept the bg
                report["status"] = "review"
                report.setdefault("note", "cutout almost fully opaque — background may not have been removed")
    return report


def vlm_check(original_path, generated_path, model=None):
    """Step 6: ask a local VLM whether the generated image faithfully shows the
    same product as the original.

    Returns {status, reason, model}. This check is opt-in (--vlm-check), so when
    it is asked for and cannot run that is a `fail`, not a `skipped`: a silent
    "skipped" is indistinguishable from a passing product in the report, which is
    exactly how this check sat broken. `skipped` now means one thing only —
    ollama is not installed on this machine at all.
    """
    import json
    import os

    try:
        import ollama                                   # noqa: F401
    except ImportError as exc:
        return {"status": "skipped", "reason": f"ollama not installed ({exc})",
                "model": None}

    for label, path in (("reference", original_path), ("generated", generated_path)):
        if not path or not os.path.exists(path):
            return {"status": "fail",
                    "reason": f"{label} image not found: {path}", "model": None}

    try:
        import analyzer
        tag = model or analyzer.resolve_model(
            os.environ.get("OLLAMA_VLM", analyzer.OLLAMA_MODEL))
    except Exception as exc:  # noqa: BLE001 — no model pulled, daemon down
        return {"status": "fail", "reason": f"could not resolve a VLM: {exc}",
                "model": None}

    try:
        r = ollama.chat(model=tag, messages=[{
            "role": "user",
            "content": ("Image 1 is the REAL product photo. Image 2 is a generated "
                        "marketing image. Does image 2 show the SAME product "
                        "accurately (same item, same colors, no distortion or "
                        "fabricated parts)? Reply JSON {\"pass\":bool,\"reason\":str}."),
            "images": [original_path, generated_path]}],
            format={"type": "object",
                    "properties": {"pass": {"type": "boolean"},
                                   "reason": {"type": "string"}},
                    "required": ["pass", "reason"]},
            options={"num_ctx": int(os.environ.get("OLLAMA_NUM_CTX", "8192"))})
        d = json.loads(r["message"]["content"])
    except Exception as exc:  # noqa: BLE001 — inference or malformed JSON
        return {"status": "fail", "reason": f"VLM call failed: {exc}", "model": tag}

    return {"status": "pass" if d.get("pass") else "review",
            "reason": d.get("reason", ""), "model": tag}
