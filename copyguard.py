#!/usr/bin/env python3
"""
Checks on model-written listing copy, before it reaches an image or a CSV.

A vision model describing a toy makes three kinds of mistake that are cheap to
catch and expensive to publish:

  drawbacks   "SMOOTH ROLLING / NOISY WHEELS" printed as a selling point, on two
              images, because nothing checked that a feature was positive.
  invention   `whats_included` listing a safety strap the scooter does not have.
              A sealed box is not visible in a photograph; the model guesses.
  trademarks  "SPIDER-MAN GIANT" and "Cristiano Ronaldo" as the product title,
              SEO title and tags — the exact strings brand-protection crawlers
              look for, on goods that are probably unlicensed.

`find_issues()` reports all three. `repair_features()` fixes the first, because
a drawback on an image is unambiguous damage. The other two are flagged rather
than rewritten: whether to sell under a character name is a business decision,
and only you know what is actually in the box.
"""

import re

# Words that turn a selling point into a warning. Deliberately narrow — a list
# that flags "small" would reject "SMALL ENOUGH TO CARRY".
NEGATIVE_TERMS = (
    "noisy", "loud", "cheap", "flimsy", "fragile", "breakable", "weak",
    "wobbly", "unstable", "poor", "low quality", "low-quality", "boring",
    "difficult", "hard to", "slow", "uncomfortable", "rough", "sharp edges",
    "not durable", "thin plastic", "easily broken", "may break",
)

# Character, brand and personality names common in toy catalogs. Not
# exhaustive — no list is — but it covers what actually turns up.
TRADEMARK_TERMS = (
    "spider-man", "spiderman", "marvel", "avengers", "iron man", "hulk",
    "batman", "superman", "dc comics", "disney", "frozen", "elsa", "anna",
    "mickey", "minnie", "barbie", "mattel", "hot wheels", "lego", "duplo",
    "pokemon", "pikachu", "nintendo", "mario", "sonic", "peppa pig",
    "paw patrol", "bluey", "hello kitty", "transformers", "star wars",
    "harry potter", "minecraft", "roblox", "fortnite", "cocomelon",
    "ronaldo", "messi", "neymar", "real madrid", "barcelona", "manchester",
    "ferrari", "lamborghini", "bugatti", "nerf", "play-doh", "fisher-price",
)

# Fields worth scanning for trademarks: these are what a crawler indexes.
_TM_FIELDS = ("name", "title", "seo_title", "meta_description", "tags",
              "description", "tagline_top", "tagline_sub", "ribbon", "callout")

# Replacements when a feature label has to be thrown away, by icon.
_SAFE_LABELS = {
    "shield": "SAFE &\nSTURDY",
    "arrows": "JUST THE\nRIGHT SIZE",
    "wheel": "SMOOTH &\nRELIABLE",
    "smiley": "HOURS OF\nFUN",
}


def _text_of(value):
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ".join(_text_of(v) for v in value)
    return ""


def _hits(text, terms):
    low = text.lower()
    return sorted({t for t in terms
                   if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", low)})


def negative_features(data):
    """Indices and terms of feature labels that read as drawbacks."""
    out = []
    for i, feat in enumerate(data.get("features", []) or []):
        bad = _hits(_text_of(feat.get("label", "")), NEGATIVE_TERMS)
        if bad:
            out.append((i, bad))
    return out


def find_issues(data, photo_count=1):
    """Human-readable flags for a profile dict. Empty list means it looks clean."""
    issues = []

    for i, bad in negative_features(data):
        label = _text_of(data["features"][i].get("label", "")).replace("\n", " / ")
        issues.append(f"feature {i + 1} reads as a drawback ({', '.join(bad)}): {label!r}")

    for field in ("description", "bullet_points"):
        bad = _hits(_text_of(data.get(field)), NEGATIVE_TERMS)
        if bad:
            issues.append(f"{field} contains negative wording: {', '.join(bad)}")

    # A single photo cannot show what is inside a sealed box.
    included = data.get("whats_included") or []
    if photo_count < 2 and len(included) > 1:
        issues.append(
            f"whats_included lists {len(included)} items from {photo_count} photo(s) — "
            "unverifiable without a packaging shot")

    tm = _hits(" ".join(_text_of(data.get(f)) for f in _TM_FIELDS), TRADEMARK_TERMS)
    if tm:
        issues.append(f"possible trademarked names in listing copy: {', '.join(tm)}")

    return issues


def repair_features(data):
    """Replace drawback feature labels with safe ones. Returns what changed.

    Only the features are rewritten: they get printed onto the hero and the
    infographic, so a drawback there is damage that ships. Everything else
    find_issues() reports is left for a human.
    """
    fixed = []
    for i, _bad in negative_features(data):
        feat = data["features"][i]
        original = _text_of(feat.get("label", "")).replace("\n", " / ")
        feat["label"] = _SAFE_LABELS.get(feat.get("icon"), _SAFE_LABELS["smiley"])
        fixed.append(f"feature {i + 1} replaced (was {original!r})")
    return fixed


RETRY_NOTE = (
    "Your previous answer described a drawback as if it were a feature. Every "
    "entry in 'features' and 'bullet_points' must be a POSITIVE reason to buy. "
    "Never mention noise, cheapness, fragility or difficulty. Answer again."
)
