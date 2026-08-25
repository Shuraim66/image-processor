#!/usr/bin/env python3
"""
Per-product colour palette, derived from the product's own pixels.

Every gallery slot reads its colours from `content["theme"]`, but nothing ever
filled that in — so a pink scooter, a green plant dome and a red-and-blue plush
all shipped in the same corporate blue and red. This module builds a theme from
the cutout itself, so the graphics belong to the product they sell.

    from palette import extract_theme
    theme = extract_theme("gallery_out/_cutouts/SCOOTER-LED-PINK.png")
    # {'primary': (196, 64, 122), 'accent': (64, 150, 120), ...}

Deterministic: same cutout in, same palette out.
"""

import colorsys

import numpy as np
from PIL import Image
from scipy.cluster.vq import kmeans2

# Legibility rails. White text sits on `primary` and `accent`, so each is taken
# as bright as it can be while still carrying white type; `ink` is body text on
# a near-white wash, so it is measured against white the other way round.
BADGE_S = 0.80                  # saturation for primary/accent — a real colour
BADGE_CONTRAST = 3.6            # white-on-colour, above the 3:1 large-text bar
INK_S, INK_CONTRAST = 0.62, 9.0  # dark text on the near-white info background
BG_TINT_S, BG_TINT_V = 0.09, 1.0
MIN_HUE_GAP = 40 / 360          # accent must differ from primary by this much

SAMPLE_PX = 20000               # pixels fed to k-means; plenty, and fast
CLUSTERS = 5


def _opaque_pixels(path):
    """RGB of the pixels that are actually product, subsampled."""
    img = Image.open(path).convert("RGBA")
    arr = np.asarray(img)
    solid = arr[arr[..., 3] > 200][:, :3].astype(np.float64)
    if len(solid) == 0:
        return solid
    if len(solid) > SAMPLE_PX:
        step = len(solid) // SAMPLE_PX
        solid = solid[::step][:SAMPLE_PX]
    return solid


def _clusters(pixels):
    """Colour clusters, most populous first, as (hsv, share) pairs."""
    k = min(CLUSTERS, len(pixels))
    centroids, labels = kmeans2(pixels, k, minit="++", seed=0)
    counts = np.bincount(labels, minlength=k)
    order = np.argsort(counts)[::-1]
    out = []
    for i in order:
        if counts[i] == 0:
            continue
        r, g, b = np.clip(centroids[i], 0, 255) / 255.0
        out.append((colorsys.rgb_to_hsv(r, g, b), counts[i] / len(pixels)))
    return out


def _relative_luminance(rgb):
    """WCAG relative luminance, for contrast ratios."""
    chan = []
    for c in (c / 255.0 for c in rgb):
        chan.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2]


def _contrast_with_white(rgb):
    return 1.05 / (_relative_luminance(rgb) + 0.05)


def _rgb(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, min(1.0, max(0.0, s)),
                                  min(1.0, max(0.0, v)))
    return (int(r * 255), int(g * 255), int(b * 255))


def _legible(h, s, min_contrast):
    """Brightest colour at this hue that still contrasts with white.

    Searching rather than hard-coding a value means a yellow product gets a
    deep amber and a navy product stays navy — both legible — instead of every
    hue being flattened to the same muddy mid-tone.
    """
    for step in range(95, 14, -2):
        rgb = _rgb(h, s, step / 100)
        if _contrast_with_white(rgb) >= min_contrast:
            return rgb
    return _rgb(h, s, 0.15)


def _pick_hues(clusters):
    """Choose a headline hue and a contrasting accent hue.

    Prefers colourful clusters — a plush that is 60% grey packaging should not
    hand us a grey brand colour — but falls back to the largest cluster so a
    genuinely monochrome product still gets a usable palette.
    """
    colourful = [(hsv, share) for hsv, share in clusters
                 if hsv[1] > 0.25 and 0.12 < hsv[2] < 0.97]
    ranked = colourful or clusters
    if not ranked:
        return 0.60, 0.02                      # nothing usable — brand blue-ish
    primary_h = ranked[0][0][0]

    for hsv, _ in ranked[1:]:
        gap = abs(hsv[0] - primary_h)
        gap = min(gap, 1 - gap)                # hues wrap at 1.0
        if gap > MIN_HUE_GAP:
            return primary_h, hsv[0]
    return primary_h, primary_h + 0.5          # no second colour — complement


def extract_theme(cutout_path):
    """Return the theme dict make_hero/gallery consume, or {} if it can't."""
    pixels = _opaque_pixels(cutout_path)
    if len(pixels) < CLUSTERS:
        return {}

    primary_h, accent_h = _pick_hues(_clusters(pixels))
    return {
        "primary": _legible(primary_h, BADGE_S, BADGE_CONTRAST),
        "accent":  _legible(accent_h, BADGE_S, BADGE_CONTRAST),
        "ink":     _legible(primary_h, INK_S, INK_CONTRAST),
        "bg_top":  _rgb(primary_h, BG_TINT_S, BG_TINT_V),
        "bg_bot":  (255, 255, 255),
    }


def as_theme(raw):
    """Coerce a theme loaded from JSON into what PIL wants (tuples, not lists)."""
    return {k: tuple(v) if isinstance(v, (list, tuple)) else v
            for k, v in (raw or {}).items()}


if __name__ == "__main__":
    import glob
    import os
    import sys

    paths = sys.argv[1:] or sorted(glob.glob("gallery_out/_cutouts/*.png"))
    for p in paths:
        theme = extract_theme(p)
        swatches = " ".join(f"{k}={theme[k]}" for k in ("primary", "accent", "ink"))
        print(f"{os.path.basename(p):32s} {swatches}")
