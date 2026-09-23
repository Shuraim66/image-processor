"""One-off A/B test: two catalog-hero prompts, one product, two billed images ($0.103 total).

A = the prompt ChatGPT proposed, as written.
B = our CatalogHero prompt plus ChatGPT's "packaging may appear beside or behind" line.

    export FAL_KEY=...        # your key
    .venv/bin/python hero_prompt_test.py

Writes hero_test/A.jpg and hero_test/B.jpg and appends both to processed_products.csv.
"""
import csv, datetime, os

import fal_listing as fl

PRODUCT = "DANCING-CACTUS-TOY-WITH-HAT-AND-SCARF"
REFS = ["angle3.jpeg",   # first = the camera: product alone, front on
        "angle4.jpeg",   # same product, another angle
        "front.jpeg"]    # the box, as evidence of what it is
OUT = "hero_test"

PROMPT_A = (
    "Create ONE premium e-commerce hero image for this toy using ALL attached product photos as "
    "the source of truth. The goal is a polished, eye-catching product hero similar to the "
    "professional feature-rich hero images used by major toy e-commerce stores. IMPORTANT: "
    "PRESERVE THE REAL PRODUCT, IMPROVE THE PRESENTATION. The physical product must remain the "
    "same real product shown in the references. Preserve exact shape, proportions, colors, "
    "visible components, surface details, graphics, logos, markings, packaging, accessories "
    "actually shown and overall configuration. Do NOT redesign, replace, embellish or upgrade "
    "the toy. You have creative freedom over the presentation: product placement, camera angle, "
    "composition, perspective, background, environment, lighting, shadows, reflections, visual "
    "depth, typography, graphic layout, feature callouts and close-up detail panels. Create a "
    "strong hero composition where the REAL PRODUCT is the dominant focal point. Packaging may be "
    "shown beside or behind the product when useful. You may create tasteful visual panels showing "
    "close-up details of the real product. You may include feature callouts ONLY when supported by "
    "clearly visible evidence in the reference images. Do not invent features, specifications, "
    "functions, accessories or claims. Do not use packaging artwork as proof of a feature unless "
    "the actual product confirms it. The image should feel premium, commercial, modern, engaging, "
    "suitable for a toy store, professionally photographed and highly presentable on a Shopify "
    "product page. The final result can be visually creative and marketing-oriented, but MUST "
    "remain an honest representation of the actual product. Generate EXACTLY ONE image."
)

PACKAGING = (" The product's own packaging may appear beside or behind the product when it helps "
             "tell the story, but the product itself stays the dominant focal point.")
PROMPT_B = ("Primary e-commerce hero photograph of this exact product on a clean white to very "
            "light neutral seamless background, the product the single focal point, no props and "
            "no decorative objects." + PACKAGING + fl.PHOTOSHOOT + fl.REF_ROLE + fl.FIDELITY)


def main():
    if not os.environ.get("FAL_KEY"):
        raise SystemExit("FAL_KEY is not set in this shell — export it and run again.")
    os.makedirs(OUT, exist_ok=True)
    folder = os.path.join("input", PRODUCT)
    refs = [os.path.join(folder, r) for r in REFS]
    missing = [r for r in refs if not os.path.exists(r)]
    if missing:
        raise SystemExit(f"missing reference photos: {missing}")

    price = fl.FAL_MODELS[fl.FAL_MODEL]["usd"]
    print(f"model {fl.FAL_MODEL} | 2 images | ${price*2:.3f}")
    rows = []
    for name, prompt in (("A", PROMPT_A), ("B", PROMPT_B)):
        out = os.path.join(OUT, f"{name}.jpg")
        if os.path.exists(out):
            print(f"  {name}: already there, skipping (never re-bill)")
            continue
        print(f"  {name}: generating…")
        fl._fal_scene(refs[0], prompt, out, refs=refs)
        print(f"  {name}: {out}")
        rows.append([datetime.datetime.now().isoformat(timespec="seconds"), PRODUCT,
                     f"hero_prompt_test_{name}", fl.FAL_MODEL, 1, f"{price:.4f}",
                     "A = ChatGPT prompt as written" if name == "A" else "B = our prompt + packaging line"])

    if rows:
        new = not os.path.exists("processed_products.csv")
        with open("processed_products.csv", "a", newline="") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["at", "product", "slot", "model", "images", "usd", "note"])
            w.writerows(rows)
        print(f"logged {len(rows)} billed image(s), ${len(rows)*price:.3f}")


if __name__ == "__main__":
    main()
