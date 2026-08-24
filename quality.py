#!/usr/bin/env python3
"""
Deterministic quality checks for a product's generated gallery.

Fast, local, no model — validates the images are the right size, not blank, and
that the marketplace "main" image has a pure-white background. Writes a
quality-report.json per product. (The VLM-based semantic check — does the image
match the product — is step 6, layered on top of this.)
"""

import os
from PIL import Image, ImageStat

IMG_EXTS = (".webp", ".jpg", ".jpeg", ".png")


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


def check_image(path, expect_size, is_main):
    checks = []
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
    return checks


def check_gallery(sku, out_dir, expect_size, cutout_path=None):
    report = {"sku": sku, "status": "pass", "images": []}
    files = sorted(f for f in os.listdir(out_dir)
                   if f.lower().endswith(IMG_EXTS))
    for f in files:
        is_main = f.startswith("01")
        try:
            checks = check_image(os.path.join(out_dir, f), expect_size, is_main)
        except Exception as exc:  # noqa: BLE001
            checks = [{"check": "open", "status": "fail", "detail": str(exc)}]
        if any(c["status"] == "fail" for c in checks):
            report["status"] = "review"
        report["images"].append({"image": f, "checks": checks})

    if cutout_path and os.path.exists(cutout_path):
        cut = Image.open(cutout_path)
        if cut.mode == "RGBA":
            bbox = cut.getchannel("A").getbbox()
            frac = (((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) /
                    (cut.width * cut.height)) if bbox else 0.0
            report["cutout_coverage"] = round(frac, 3)
            if frac < 0.05:
                report["status"] = "review"
                report["note"] = "cutout very small — background removal may have failed"
    return report


def vlm_check(original_path, generated_path, model=None):
    """Step 6: ask a local VLM whether the generated image faithfully shows the
    same product as the original. Returns {status, reason}; 'skipped' if no VLM."""
    import os
    model = model or os.environ.get("OLLAMA_VLM", "qwen3-vl:8b")
    try:
        import json
        import ollama
        r = ollama.chat(model=model, messages=[{
            "role": "user",
            "content": ("Image 1 is the REAL product photo. Image 2 is a generated "
                        "marketing image. Does image 2 show the SAME product "
                        "accurately (same item, same colors, no distortion or "
                        "fabricated parts)? Reply JSON {\"pass\":bool,\"reason\":str}."),
            "images": [original_path, generated_path]}],
            format={"type": "object",
                    "properties": {"pass": {"type": "boolean"},
                                   "reason": {"type": "string"}},
                    "required": ["pass", "reason"]})
        d = json.loads(r["message"]["content"])
        return {"status": "pass" if d.get("pass") else "review",
                "reason": d.get("reason", "")}
    except Exception as exc:  # noqa: BLE001 — no ollama / model / error
        return {"status": "skipped", "reason": str(exc)}
