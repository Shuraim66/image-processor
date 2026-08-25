#!/usr/bin/env python3
"""
Multi-photo product analyzer — local Qwen3-VL via Ollama.

Sends ALL of a product's photos together to a local vision model and returns a
validated ProductProfile (Pydantic), saved as product.json. Replaces the cloud
Gemini call: fully local, no API key, no quota.

    ollama pull qwen3-vl:8b            # once, on the Mac\n    export OLLAMA_VLM=qwen3-vl:8b-instruct-q4_K_M   # or pin your tag
    python analyzer.py input/SCOOTER-LED-PINK
    python analyzer.py --all           # every SKU under input/

Fails loudly if the model is unavailable; pass --allow-fallback to write\nplaceholder copy instead. Every profile records which model wrote it.
"""

import argparse
import json
import os
import sys
from functools import lru_cache
from typing import Any, Dict, List

from pydantic import BaseModel, Field, ValidationError

import copyguard

OLLAMA_MODEL = os.environ.get("OLLAMA_VLM", "qwen3-vl:8b")
INPUT_DIR = "input"
VALID_EXTS = (".jpg", ".jpeg", ".png", ".webp")
ICONS = ["shield", "arrows", "wheel", "smiley"]     # icons the templates can draw


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
class Feature(BaseModel):
    icon: str = Field(description="one of: shield, arrows, wheel, smiley")
    label: str = Field(description="two short CAPS lines separated by \\n")


class ProductProfile(BaseModel):
    sku: str = ""
    source: str = ""                # model tag that wrote this, or "fallback:<why>"
    name: str                       # short punchy name for the hero wordmark (CAPS)
    title: str                      # full marketplace product title
    tagline_top: str
    tagline_sub: str
    description: str                # 3-5 sentence marketplace description
    bullet_points: List[str]        # 5 selling points
    features: List[Feature]         # exactly 4, icons from ICONS
    whats_included: List[str]
    seo_title: str
    meta_description: str
    tags: List[str]
    alt_text: str
    info_title: str                 # heading for the feature graphic
    ribbon: str                     # short badge phrase
    callout: str                    # 2-3 word highlight
    detail_caption: str
    scene_prompts: List[str]        # 2 lifestyle background prompts
    theme: Dict[str, Any] = Field(default_factory=dict)   # pin colours here to
    # override the palette derived from the product's own pixels (see palette.py)
    review_flags: List[str] = Field(default_factory=list)  # copyguard findings


PROMPT = (
    "You are an expert e-commerce creative director and copywriter for a "
    "children's toy store called The Toy Gift Shop. You are given MULTIPLE photos "
    "of ONE product (angles, packaging, close-ups). Study all of them together — "
    "read any text on the packaging — and produce complete listing content as JSON.\n\n"
    "Rules:\n"
    "- name: short punchy product name in CAPS (1-2 words) for a big hero wordmark. "
    "It MUST correctly name the actual product type you see (e.g. SCOOTER, PLANE, "
    "PLUSH) — never mislabel it (a scooter is NOT a skateboard).\n"
    "- title: full, specific marketplace product title.\n"
    "- tagline_top / tagline_sub: a two-line hook (2-3 words each, in CAPS).\n"
    "- description: 3-5 vivid sentences.\n"
    "- bullet_points: exactly 5 concise selling points.\n"
    "- features: EXACTLY 4. Each has 'label' (two short CAPS lines joined by \\n) and "
    "'icon' chosen ONLY from: shield (safety/sturdy), arrows (adjustable/size), "
    "wheel (movement/smooth), smiley (fun/age). Every label must be a POSITIVE "
    "selling point, never a drawback.\n"
    "- whats_included: ONLY what you can actually see or read on visible "
    "packaging. If no packaging or box contents are visible, return exactly one "
    "item naming the product itself. Never guess at accessories.\n"
    "- seo_title (<=60 chars), meta_description (<=155 chars), tags (8-13 RELEVANT keywords only, no unrelated terms), "
    "alt_text (one descriptive sentence).\n"
    "- info_title: heading for a features graphic (e.g. 'WHY KIDS LOVE IT').\n"
    "- ribbon: a short badge phrase (CAPS); callout: a 2-3 word highlight (CAPS).\n"
    "- detail_caption: one sentence about the standout detail.\n"
    "- scene_prompts: 2 lifestyle BACKGROUND descriptions (a bright, relevant "
    "room/place for THIS product, NO people, NO text), each ending with "
    "'product photography, soft daylight, square, empty foreground surface'.\n"
    "Base everything only on what is visible. Do not invent a brand name, and "
    "do NOT reproduce a character, franchise, club or celebrity name even if you "
    "can see one — describe the product generically (a 'superhero plush', a "
    "'footballer figure') so the listing does not trade on someone else's mark."
)


class AnalyzerError(RuntimeError):
    """Analysis could not be completed and fallback copy was not permitted."""


@lru_cache(maxsize=8)
def resolve_model(name: str = OLLAMA_MODEL) -> str:
    """Return an Ollama tag that is actually installed, or raise.

    Tag names are exact in Ollama: asking for 'qwen3-vl:8b' when only
    'qwen3-vl:8b-instruct-q4_K_M' is pulled is a hard error, not a near miss.
    Rather than let that surface as generic filler copy on every product, match
    on the model family and say plainly which tag was chosen.
    """
    import ollama
    installed = [m.model for m in ollama.list().models]
    if name in installed:
        return name
    family = name.split(":")[0]
    matches = sorted((t for t in installed if t.split(":")[0] == family), key=len)
    if matches:
        print(f"  [analyzer] '{name}' is not installed; using '{matches[0]}'. "
              f"Set OLLAMA_VLM to silence this.", file=sys.stderr)
        return matches[0]
    raise AnalyzerError(
        f"no Ollama model matching '{name}' is installed "
        f"(found: {', '.join(installed) or 'none'}). "
        f"Run 'ollama pull {name}' or set OLLAMA_VLM to an installed tag.")


# --------------------------------------------------------------------------- #
# Fallback (no Ollama)
# --------------------------------------------------------------------------- #
def _fallback(sku: str, why: str = "unspecified") -> ProductProfile:
    pretty = sku.replace("-", " ").title()
    return ProductProfile(
        sku=sku, source=f"fallback:{why}",
        name=sku.split("-")[0].upper(), title=pretty,
        tagline_top="BUILT FOR", tagline_sub="BIG SMILES!",
        description=f"The {pretty} is a fun, well-made toy kids will love.",
        bullet_points=[f"{pretty} — great gift", "Fun and durable",
                       "Bright, kid-friendly design", "Easy to use",
                       "Ages 3+"],
        features=[Feature(icon="shield", label="SAFE &\nSTURDY"),
                  Feature(icon="arrows", label="JUST THE\nRIGHT SIZE"),
                  Feature(icon="wheel", label="SMOOTH &\nRELIABLE"),
                  Feature(icon="smiley", label="HOURS OF\nFUN")],
        whats_included=["1x " + pretty],
        seo_title=pretty[:60], meta_description=f"Buy the {pretty} at The Toy Gift Shop."[:155],
        tags=["toy", "kids", "gift", "fun"], alt_text=f"{pretty} product photo.",
        info_title="WHY KIDS LOVE IT", ribbon="MADE TO LAST!", callout="KID FAVOURITE",
        detail_caption=f"A closer look at the {pretty}.",
        scene_prompts=[
            "bright modern children's playroom, product photography, soft daylight, square, empty foreground surface",
            "sunny living room with warm wood floor, product photography, soft daylight, square, empty foreground surface",
        ],
    )


def _normalize(data: dict, sku: str) -> dict:
    data["sku"] = sku
    feats = [f for f in data.get("features", []) if f.get("icon") in ICONS][:4]
    fb = _fallback(sku, "padding").features
    while len(feats) < 4:
        f = fb[len(feats)]
        feats.append({"icon": f.icon, "label": f.label})
    data["features"] = feats
    return data


# --------------------------------------------------------------------------- #
# Analyze
# --------------------------------------------------------------------------- #
def images_in(folder: str) -> List[str]:
    return sorted(os.path.join(folder, f) for f in os.listdir(folder)
                  if f.lower().endswith(VALID_EXTS))


def _request_schema() -> dict:
    """The schema the model is asked to fill — bookkeeping fields removed so it
    does not waste tokens inventing an sku or a source it cannot know."""
    schema = ProductProfile.model_json_schema()
    for field in ("sku", "source", "theme", "review_flags"):
        schema.get("properties", {}).pop(field, None)
        if field in schema.get("required", []):
            schema["required"].remove(field)
    return schema


def analyze(sku: str, image_paths: List[str], use_ollama: bool = True,
            allow_fallback: bool = False) -> ProductProfile:
    """Analyze a product's photos into a validated profile.

    On failure this raises AnalyzerError unless `allow_fallback` is set. That is
    deliberate: silently substituting generic copy is invisible at one product
    and catastrophic at a thousand, where it would fill a live storefront with
    "a fun, well-made toy kids will love" and nothing would flag it.
    """
    if not use_ollama:
        return _fallback(sku, "requested")       # explicit --no-ollama
    if not image_paths:
        if allow_fallback:
            print(f"  [analyzer] no photos for {sku}; using fallback", file=sys.stderr)
            return _fallback(sku, "no-photos")
        raise AnalyzerError(f"no photos to analyze in the {sku} folder")

    try:
        import ollama
        model = resolve_model()
        resp = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": PROMPT, "images": image_paths}],
            format=_request_schema(),                    # structured output
            options={"temperature": 0.4,
                     "num_ctx": int(os.environ.get("OLLAMA_NUM_CTX", "8192"))},
        )
        data = _normalize(json.loads(resp["message"]["content"]), sku)

        # A drawback described as a feature gets printed onto two images, so it
        # is worth one corrective round-trip before falling back to repair.
        if copyguard.negative_features(data):
            retry = ollama.chat(
                model=model,
                messages=[{"role": "user",
                           "content": PROMPT + "\n\n" + copyguard.RETRY_NOTE,
                           "images": image_paths}],
                format=_request_schema(),
                options={"temperature": 0.2,
                         "num_ctx": int(os.environ.get("OLLAMA_NUM_CTX", "8192"))},
            )
            data = _normalize(json.loads(retry["message"]["content"]), sku)

        for note in copyguard.repair_features(data):
            print(f"  [analyzer] {sku}: {note}", file=sys.stderr)

        data["source"] = model
        data["review_flags"] = copyguard.find_issues(data, len(image_paths))
        for flag in data["review_flags"]:
            print(f"  [analyzer] {sku}: {flag}", file=sys.stderr)
        return ProductProfile(**data)
    except AnalyzerError:
        if not allow_fallback:
            raise
        print(f"  [analyzer] {sku}: model unavailable; using fallback", file=sys.stderr)
        return _fallback(sku, "no-model")
    except Exception as exc:  # noqa: BLE001 — import/network/parse/validation
        if not allow_fallback:
            raise AnalyzerError(f"{sku}: analysis failed ({type(exc).__name__}: {exc})") from exc
        print(f"  [analyzer] {sku}: analysis failed ({exc}); using fallback", file=sys.stderr)
        return _fallback(sku, "error")


def analyze_folder(sku_folder: str, use_ollama: bool = True,
                   allow_fallback: bool = False) -> ProductProfile:
    sku = os.path.basename(os.path.normpath(sku_folder))
    imgs = images_in(sku_folder)
    print(f"[{sku}] {len(imgs)} photo(s) -> {OLLAMA_MODEL if use_ollama else 'fallback'}")
    profile = analyze(sku, imgs, use_ollama=use_ollama, allow_fallback=allow_fallback)
    out = os.path.join(sku_folder, "product.json")
    with open(out, "w", encoding="utf-8") as f:
        f.write(profile.model_dump_json(indent=2))
    flags = f"  {len(profile.review_flags)} flag(s)" if profile.review_flags else ""
    print(f"  -> {out}  [{profile.source}]{flags}")
    return profile


def main():
    ap = argparse.ArgumentParser(description="Analyze product photos -> product.json (local Qwen3-VL).")
    ap.add_argument("folder", nargs="?", help="a single SKU folder (e.g. input/SCOOTER-LED-PINK)")
    ap.add_argument("--all", action="store_true", help="every SKU folder under input/")
    ap.add_argument("--no-ollama", action="store_true", help="skip the model; deterministic fallback")
    ap.add_argument("--allow-fallback", action="store_true",
                    help="write placeholder copy instead of failing when analysis breaks "
                         "(off by default so a batch cannot silently fill with filler)")
    args = ap.parse_args()

    if args.all:
        folders = [os.path.join(INPUT_DIR, d) for d in sorted(os.listdir(INPUT_DIR))
                   if os.path.isdir(os.path.join(INPUT_DIR, d))]
    elif args.folder:
        folders = [args.folder]
    else:
        ap.error("give a SKU folder or --all")

    failed, fell_back = [], []
    for f in folders:
        try:
            profile = analyze_folder(f, use_ollama=not args.no_ollama,
                                     allow_fallback=args.allow_fallback)
        except AnalyzerError as exc:
            print(f"  ! {exc}", file=sys.stderr)
            failed.append(os.path.basename(os.path.normpath(f)))
            continue
        if profile.source.startswith("fallback"):
            fell_back.append(profile.sku)

    print(f"\nAnalyzed {len(folders) - len(failed)}/{len(folders)}.")
    if fell_back:
        print(f"Placeholder copy (review before publishing): {', '.join(fell_back)}",
              file=sys.stderr)
    if failed:
        print(f"Failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
