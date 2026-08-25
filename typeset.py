#!/usr/bin/env python3
"""
Per-category typography.

A doll and a drone should not speak in the same voice. Each scene category
(see scenes.py) gets its own display face for the wordmark and the slot titles —
the loudest type on the image — while every utility role keeps Montserrat.

Varying the display face and holding the utility face constant is deliberate:
it gives each listing a recognisable character without letting feature labels,
dimensions and badges drift in legibility from product to product.

Faces are bundled in assets/fonts so rendering does not depend on system fonts:

    Anton          SIL OFL      condensed, heavy — sport and wheels
    Baloo 2        SIL OFL      bouncy and soft — plush, baby, night lights
    Fredoka        SIL OFL      rounded geometric — nature and growing
    Luckiest Guy   Apache 2.0   cartoon poster — the general toy voice
    Montserrat     SIL OFL      utility: banners, labels, specs (already bundled)

Licences ship alongside the fonts in assets/fonts/.
"""

MONTSERRAT_BLACK = "Montserrat-Black.otf"

# category -> (display face spec, starting size for the hero wordmark)
# A face spec is a filename, or (filename, variable-instance name).
# Sizes differ because the faces do: Anton is condensed and reads small at a
# given point size, Luckiest Guy is wide and reads large.
FONT_SETS = {
    "outdoor":  {"display": "Anton-Regular.ttf",                 "hero_px": 200},
    "nursery":  {"display": ("Baloo2[wght].ttf", "ExtraBold"),   "hero_px": 170},
    "garden":   {"display": ("Fredoka[wdth,wght].ttf", "Bold"),  "hero_px": 165},
    "playroom": {"display": "LuckiestGuy-Regular.ttf",           "hero_px": 150},
    "desk":     {"display": MONTSERRAT_BLACK,                    "hero_px": 155},
}

DEFAULT_SET = FONT_SETS["playroom"]

# Utility roles are the same everywhere, so specs and feature labels read
# identically across the catalog.
BANNER = "Montserrat-ExtraBold.otf"
LABEL = "Montserrat-Bold.otf"
CAPTION = "Montserrat-SemiBold.otf"


def fonts_for(category):
    """Display face + starting size for a category, falling back to the default."""
    chosen = FONT_SETS.get(category or "", DEFAULT_SET)
    return {"display": chosen["display"], "hero_px": chosen["hero_px"],
            "banner": BANNER, "label": LABEL, "caption": CAPTION}
