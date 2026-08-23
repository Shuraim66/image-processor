#!/usr/bin/env python3
"""
Toy product photo pipeline.

For every SKU sub-folder of raw photos this script:
  1. Removes the background (rembg).
  2. Centres the object on a white square canvas with a fixed padding border (Pillow).
  3. Grounds it with a soft programmatic drop shadow.
  4. Overlays a semi-transparent logo watermark in the bottom-right corner.
  5. Sends the primary processed image to the Gemini API for an SEO title + description.
  6. Appends everything to a WooCommerce-ready CSV.

Input layout
------------
    input/
      CAR-RED-001/
        front.jpg
        side.jpg
        ...
      TRUCK-BLUE-002/
        ...
    logo.png

Usage
-----
    export GEMINI_API_KEY="your-key"
    python process_products.py
"""

import argparse
import csv
import io
import os
import sys
import time
import json
import traceback

from PIL import Image, ImageFilter

# --------------------------------------------------------------------------- #
# Configuration — adjust freely
# --------------------------------------------------------------------------- #
INPUT_DIR = "input"                     # directory holding the SKU sub-folders
OUTPUT_DIR = "output"                   # processed images land here
LOGO_PATH = "logo.png"                  # watermark source
CSV_PATH = "woocommerce_import.csv"     # final import file

CANVAS_SIZE = 2000                      # final image is CANVAS_SIZE x CANVAS_SIZE px
PADDING_PERCENT = 0.10                  # white border on every side (0.10 = 10%)
BACKGROUND_COLOR = (255, 255, 255)      # pure white

WATERMARK_OPACITY = 0.30                # 0.0 (invisible) .. 1.0 (opaque)
WATERMARK_SCALE = 0.18                  # logo width as a fraction of the canvas
WATERMARK_MARGIN = 0.03                 # gap from the canvas edge (fraction of canvas)

SHADOW_COLOR = (0, 0, 0)                # drop-shadow colour
SHADOW_OPACITY = 90                     # 0..255 alpha of the shadow
SHADOW_BLUR = 40                        # Gaussian blur radius in px
SHADOW_OFFSET = (0, 45)                 # (x, y) shadow offset in px

VALID_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")

# Gemini
GEMINI_MODEL = "gemini-3.6-flash"
API_CALL_DELAY = 6                      # seconds between calls (free tier: 10 req/min)
API_MAX_RETRIES = 3                     # retries per SKU on API failure
API_RETRY_BACKOFF = 10                  # seconds added per retry attempt

# rembg session is created lazily and reused across images.
_rembg_session = None


# --------------------------------------------------------------------------- #
# Image processing
# --------------------------------------------------------------------------- #
def _get_rembg_session():
    """Create the rembg session once and reuse it (model load is expensive)."""
    global _rembg_session
    if _rembg_session is None:
        from rembg import new_session
        _rembg_session = new_session()
    return _rembg_session


def remove_background(image: Image.Image) -> Image.Image:
    """Return an RGBA image with the background removed."""
    from rembg import remove
    cutout = remove(image, session=_get_rembg_session())
    return cutout.convert("RGBA")


def trim_to_content(image: Image.Image) -> Image.Image:
    """Crop transparent margins so padding is measured from the real object."""
    bbox = image.getbbox()
    return image.crop(bbox) if bbox else image


def make_shadow(cutout: Image.Image, canvas_size: int) -> Image.Image:
    """Build a full-canvas RGBA layer holding only the soft drop shadow."""
    # A silhouette coloured with SHADOW_COLOR, using the cutout's alpha as its mask.
    silhouette = Image.new("RGBA", cutout.size, SHADOW_COLOR + (0,))
    alpha = cutout.getchannel("A").point(lambda a: SHADOW_OPACITY if a > 0 else 0)
    silhouette.putalpha(alpha)

    layer = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    # Position matches where the object will sit, plus the configured offset.
    x = (canvas_size - cutout.width) // 2 + SHADOW_OFFSET[0]
    y = (canvas_size - cutout.height) // 2 + SHADOW_OFFSET[1]
    layer.paste(silhouette, (x, y), silhouette)
    return layer.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))


def _shadow_reserve() -> int:
    """Px the shadow can spread past the object (blur + offset) on any side.

    Reserved inside the padding so the drop shadow never breaks the strict
    white border. Returns 0 when the shadow is effectively disabled.
    """
    if SHADOW_OPACITY <= 0:
        return 0
    reach_x = SHADOW_BLUR + abs(SHADOW_OFFSET[0])
    reach_y = SHADOW_BLUR + abs(SHADOW_OFFSET[1])
    return max(reach_x, reach_y)


def standardize(cutout: Image.Image) -> Image.Image:
    """Centre the cutout on a padded white canvas with a drop shadow."""
    cutout = trim_to_content(cutout)

    # Resize so the object fits inside the padded area, preserving aspect ratio.
    # Reserve room for the shadow's spread so the 10% white border stays strict.
    inner = int(CANVAS_SIZE * (1 - 2 * PADDING_PERCENT)) - 2 * _shadow_reserve()
    inner = max(1, inner)
    scale = min(inner / cutout.width, inner / cutout.height)
    new_size = (max(1, int(cutout.width * scale)), max(1, int(cutout.height * scale)))
    cutout = cutout.resize(new_size, Image.LANCZOS)

    canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), BACKGROUND_COLOR + (255,))
    canvas = Image.alpha_composite(canvas, make_shadow(cutout, CANVAS_SIZE))

    x = (CANVAS_SIZE - cutout.width) // 2
    y = (CANVAS_SIZE - cutout.height) // 2
    canvas.paste(cutout, (x, y), cutout)
    return canvas


def load_watermark() -> Image.Image | None:
    """Load and pre-scale the logo at the configured opacity, or None if missing."""
    if not os.path.exists(LOGO_PATH):
        print(f"  ! logo not found at '{LOGO_PATH}' — skipping watermark", file=sys.stderr)
        return None

    logo = Image.open(LOGO_PATH).convert("RGBA")
    target_w = int(CANVAS_SIZE * WATERMARK_SCALE)
    scale = target_w / logo.width
    logo = logo.resize((target_w, max(1, int(logo.height * scale))), Image.LANCZOS)

    # Scale the existing alpha by the opacity factor (respects transparent logos).
    alpha = logo.getchannel("A").point(lambda a: int(a * WATERMARK_OPACITY))
    logo.putalpha(alpha)
    return logo


def apply_watermark(canvas: Image.Image, watermark: Image.Image | None) -> Image.Image:
    """Paste the watermark into the bottom-right corner."""
    if watermark is None:
        return canvas
    margin = int(CANVAS_SIZE * WATERMARK_MARGIN)
    x = CANVAS_SIZE - watermark.width - margin
    y = CANVAS_SIZE - watermark.height - margin
    canvas.paste(watermark, (x, y), watermark)
    return canvas


def process_image(path: str, watermark: Image.Image | None) -> Image.Image:
    """Full pipeline for a single raw photo → finished RGB canvas."""
    with Image.open(path) as img:
        cutout = remove_background(img.convert("RGBA"))
    canvas = standardize(cutout)
    canvas = apply_watermark(canvas, watermark)
    return canvas.convert("RGB")  # flatten onto white for a clean JPEG


# --------------------------------------------------------------------------- #
# Gemini metadata
# --------------------------------------------------------------------------- #
METADATA_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
    },
    "required": ["title", "description"],
}

METADATA_PROMPT = (
    "You are an e-commerce copywriter for a toy store. Look at this product photo "
    "and return a JSON object with two fields:\n"
    "  - 'title': a concise, SEO-friendly WooCommerce product title (max ~70 chars).\n"
    "  - 'description': a compelling product description of exactly three sentences.\n"
    "Base everything only on what is visible in the image. Do not invent a brand name."
)


def _make_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Set GEMINI_API_KEY (or GOOGLE_API_KEY) in your environment before running."
        )
    from google import genai
    return genai.Client(api_key=api_key)


def generate_metadata(client, image: Image.Image, sku: str) -> dict:
    """Ask Gemini for a title + description. Returns a dict; falls back on failure."""
    from google.genai import types

    # Encode the finished image as JPEG bytes for the request.
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=90)
    image_part = types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=METADATA_SCHEMA,
    )

    last_error = None
    for attempt in range(1, API_MAX_RETRIES + 1):
        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[image_part, METADATA_PROMPT],
                config=config,
            )
            data = json.loads(resp.text)
            return {
                "title": str(data.get("title", "")).strip(),
                "description": str(data.get("description", "")).strip(),
            }
        except Exception as exc:  # noqa: BLE001 — network/parse errors are all recoverable
            last_error = exc
            wait = API_RETRY_BACKOFF * attempt
            print(f"  ! Gemini attempt {attempt}/{API_MAX_RETRIES} failed for {sku}: "
                  f"{exc} — retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)

    print(f"  ! giving up on Gemini for {sku}: {last_error}", file=sys.stderr)
    return {"title": f"{sku} — Toy", "description": ""}


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def find_sku_folders(root: str) -> list[str]:
    if not os.path.isdir(root):
        raise FileNotFoundError(f"Input directory '{root}' does not exist.")
    return sorted(
        name for name in os.listdir(root)
        if os.path.isdir(os.path.join(root, name))
    )


def raw_images_in(folder: str) -> list[str]:
    return sorted(
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith(VALID_EXTENSIONS)
    )


def main(dry_run: bool = False) -> int:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        skus = find_sku_folders(INPUT_DIR)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not skus:
        print(f"No SKU sub-folders found in '{INPUT_DIR}'.", file=sys.stderr)
        return 1

    watermark = load_watermark()

    client = None
    if dry_run:
        print("Dry run: processing images only, skipping the Gemini API.")
    else:
        try:
            client = _make_gemini_client()
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["SKU", "Title", "Description", "Images"])

        for idx, sku in enumerate(skus, start=1):
            folder = os.path.join(INPUT_DIR, sku)
            raw_images = raw_images_in(folder)
            print(f"[{idx}/{len(skus)}] {sku}: {len(raw_images)} image(s)")

            if not raw_images:
                print(f"  ! no images in {folder} — skipping", file=sys.stderr)
                continue

            processed_paths = []
            primary_image = None
            for angle, raw_path in enumerate(raw_images, start=1):
                try:
                    canvas = process_image(raw_path, watermark)
                except Exception as exc:  # noqa: BLE001 — skip a bad file, keep the batch alive
                    print(f"  ! failed to process {raw_path}: {exc}", file=sys.stderr)
                    traceback.print_exc()
                    continue

                out_path = os.path.join(OUTPUT_DIR, f"{sku}_{angle}.jpg")
                canvas.save(out_path, format="JPEG", quality=92)
                processed_paths.append(out_path)
                if primary_image is None:
                    primary_image = canvas
                print(f"  -> {out_path}")

            if primary_image is None:
                print(f"  ! no image processed for {sku} — skipping metadata", file=sys.stderr)
                continue

            if dry_run:
                meta = {"title": "", "description": ""}
            else:
                meta = generate_metadata(client, primary_image, sku)
            writer.writerow([
                sku,
                meta["title"],
                meta["description"],
                ", ".join(processed_paths),
            ])
            fh.flush()  # persist progress after every SKU

            # Respect the free-tier rate limit (10 req/min ≈ one call per 6s).
            if not dry_run and idx < len(skus):
                time.sleep(API_CALL_DELAY)

    print(f"\nDone. CSV written to '{CSV_PATH}'.")
    return 0


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process toy product photos and generate a WooCommerce CSV.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process images and write the CSV, but skip the Gemini API "
             "(no metadata, no API cost). Use to preview cutouts/watermark.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    sys.exit(main(dry_run=args.dry_run))
