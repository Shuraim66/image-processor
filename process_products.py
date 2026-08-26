#!/usr/bin/env python3
"""
Cutout and canvas primitives shared by the rest of the pipeline.

This was once a standalone script that also called Gemini for copy and wrote a
WooCommerce CSV. Both are gone: `analyzer.py` writes the copy locally, and
`shopify_export.py` writes the CSV. Its old CLI also stamped the watermark onto
the plain white-background catalog image, which is precisely the image
marketplaces reject for carrying a logo — the gallery pipeline keeps that slot
clean instead.

What remains is the library the pipeline imports:

    remove_background()   rembg cutout, with the model pinned (see REMBG_MODEL)
    trim_to_content()     crop to the product, dropping haze and stray blobs
    standardize()         centre on a padded white square with a soft shadow
    find_sku_folders()    discover the product folders under input/
    raw_images_in()       a folder's photos, primary shot first
"""

import os

from PIL import Image, ImageFilter

try:                                    # optional: sharpens cutout framing
    import numpy as _np
    from scipy import ndimage as _ndimage
except ImportError:                     # pragma: no cover - degraded fallback
    _np = _ndimage = None

# --------------------------------------------------------------------------- #
# Configuration — adjust freely
# --------------------------------------------------------------------------- #
INPUT_DIR = "input"                     # directory holding the SKU sub-folders

CANVAS_SIZE = 2000                      # final image is CANVAS_SIZE x CANVAS_SIZE px
PADDING_PERCENT = 0.10                  # white border on every side (0.10 = 10%)
BACKGROUND_COLOR = (255, 255, 255)      # pure white


SHADOW_COLOR = (0, 0, 0)                # drop-shadow colour
SHADOW_OPACITY = 90                     # 0..255 alpha of the shadow
SHADOW_BLUR = 40                        # Gaussian blur radius in px
SHADOW_OFFSET = (0, 45)                 # (x, y) shadow offset in px

VALID_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")

# Background removal. rembg's own default is 'bria-rmbg', which ships under a
# CC BY-NC licence — non-commercial only, and this is a commercial shop. Pin an
# MIT-licensed BiRefNet instead.
#
# Measured on the M3 Pro across the catalogue's three hardest cutouts:
#
#   model                  time    peak    plush/scooter   clear plastic
#   birefnet-general       ~11 s   ~7 GB   correct         correct     <- default
#   birefnet-general-lite  ~5 s    ~7 GB   correct         FAILS
#   birefnet-massive       ~13 s   ~6 GB   correct         stray artifacts
#   isnet-general-use      ~1 s    ~1 GB   haloed edges    -
#
# The lite variant is twice as fast and indistinguishable on opaque toys, but on
# STEM-PLANTGROW-DOME it cut the clear dome off at the rim and kept the houseplants
# standing behind it, so the product came out as a shallow tray surrounded by
# someone else's foliage. Transparent packaging and clear plastic are common enough
# here that correctness wins; set REMBG_MODEL=birefnet-general-lite for a fast pass
# over a batch you know is all opaque.
REMBG_MODEL = os.environ.get("REMBG_MODEL", "birefnet-general")

# Cutout cleanup (see trim_to_content). ALPHA_FLOOR is the alpha below which a
# pixel is treated as background haze rather than product; BLOB_KEEP_RATIO is
# the minimum size of a blob, relative to the largest one, that is kept.
ALPHA_FLOOR = int(os.environ.get("CUTOUT_ALPHA_FLOOR", "40"))
BLOB_KEEP_RATIO = float(os.environ.get("CUTOUT_BLOB_KEEP", "0.05"))

# Gemini

# rembg session is created lazily and reused across images.
_rembg_session = None


# --------------------------------------------------------------------------- #
# Image processing
# --------------------------------------------------------------------------- #
def _get_rembg_session():
    """Create the rembg session once and reuse it (model load is expensive).

    Honors REMBG_MODEL (e.g. 'birefnet-general-lite' or 'u2netp' on a small-RAM
    machine). Never calls new_session() bare: its default is the non-commercial
    bria-rmbg. See REMBG_MODEL above."""
    global _rembg_session
    if _rembg_session is None:
        from rembg import new_session
        _rembg_session = new_session(REMBG_MODEL)
    return _rembg_session


def remove_background(image: Image.Image) -> Image.Image:
    """Return an RGBA image with the background removed."""
    from rembg import remove
    cutout = remove(image, session=_get_rembg_session())
    return cutout.convert("RGBA")


def _solid_bbox_pil(alpha: Image.Image, floor: int):
    """Threshold-only bbox. Fallback when SciPy is unavailable."""
    return alpha.point(lambda a: 255 if a > floor else 0).getbbox()


def trim_to_content(image: Image.Image, return_box: bool = False):
    """Crop to the real object and drop stray blobs around it.

    rembg does not return a clean binary mask — it leaves a haze of alpha 1-20
    across the whole frame. A plain getbbox() (which measures alpha > 0)
    therefore returns the ENTIRE image, so the object gets scaled down to fit
    its own leftover background and ends up small and off-centre in every slot.

    Instead: threshold the alpha, keep only blobs of a meaningful size (so a
    floor line, a price tag or a neighbouring toy stops inflating the box),
    zero everything outside them, and crop to what is left. Anti-aliased edges
    survive because the keep-mask is dilated a few pixels before it is applied.
    """
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    alpha = image.getchannel("A")

    def _out(img, box):
        return (img, box) if return_box else img

    if _np is None or _ndimage is None:      # SciPy/NumPy missing — threshold only
        bbox = _solid_bbox_pil(alpha, ALPHA_FLOOR)
        return _out(image.crop(bbox) if bbox else image, bbox)

    a = _np.asarray(alpha)
    mask = a > ALPHA_FLOOR
    if not mask.any():
        bbox = image.getbbox()               # nothing solid — keep old behaviour
        return _out(image.crop(bbox) if bbox else image, bbox)

    labels, count = _ndimage.label(mask)
    sizes = _ndimage.sum_labels(mask, labels, index=range(1, count + 1))
    cutoff = sizes.max() * BLOB_KEEP_RATIO
    keep_ids = [i + 1 for i, s in enumerate(sizes) if s >= cutoff]
    keep = _np.isin(labels, keep_ids)

    # Grow the keep-mask so the object's soft edge (alpha below the floor but
    # touching the solid core) is not clipped into a hard, jagged outline.
    grow = max(2, min(image.size) // 400)
    keep = _ndimage.binary_dilation(keep, iterations=grow)

    trimmed = image.copy()
    trimmed.putalpha(Image.fromarray(_np.where(keep, a, 0).astype("uint8")))
    bbox = trimmed.getchannel("A").getbbox()
    return _out(trimmed.crop(bbox) if bbox else trimmed, bbox)


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


# --------------------------------------------------------------------------- #
def find_sku_folders(root: str) -> list[str]:
    if not os.path.isdir(root):
        raise FileNotFoundError(f"Input directory '{root}' does not exist.")
    return sorted(
        name for name in os.listdir(root)
        if os.path.isdir(os.path.join(root, name))
    )


# Photos whose name starts with one of these are the product's main shot. Every
# rendered image is built from raw_images_in()[0], and plain alphabetical order
# put "angle2.jpg" ahead of "front.jpg" — so the main catalog shot was silently
# coming from a secondary angle on every multi-photo product.
PRIMARY_STEMS = ("front", "main", "hero", "01", "1_")


def raw_images_in(folder: str) -> list[str]:
    """Photos for a SKU, primary shot first, the rest in filename order."""
    names = sorted(f for f in os.listdir(folder)
                   if f.lower().endswith(VALID_EXTENSIONS))
    names.sort(key=lambda f: not f.lower().startswith(PRIMARY_STEMS))
    return [os.path.join(folder, f) for f in names]


