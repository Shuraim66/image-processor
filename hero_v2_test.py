"""One-off test: the revised, photography-only CatalogHero v2 prompt on the 3D Pen, one
billed image ($0.0515).

Follow-up to hero_test/3d-pen-v2.jpg. That first test correctly kept the "tuosiqi" logo on
the box and didn't invent a second pen or extra filament colors, but used a styled marble
and plant setting -- a different "pattern" than the plain white studio look already approved
for the rest of the catalog (hero_test/B.jpg, the Dancing Cactus). The user then compared it
to hero_test/A.jpg (the ChatGPT-prompt cactus, with a drawn headline and feature-callout
circles) and considered having CatalogHero draw that same headline/callout text -- then chose
NOT to, specifically to avoid the AI ever misspelling something or inventing a claim the box
doesn't support. So CATALOG_HERO_V2 was revised: richer styled photography is still allowed,
but zero AI-written text of any kind. This test checks that revision.

    export FAL_KEY=...        # your key
    .venv/bin/python hero_v2_test.py

Writes hero_test/3d-pen-v2b.jpg and appends one correctly-shaped row to processed_products.csv.
"""
import csv, datetime, os

import fal_listing as fl

PRODUCT = "3D-PRINTING-PEN"
SKU = "TGS-3D-PRINTING-PEN"
REFS = ["angle3.jpeg",   # first = the camera: real pen + filament + USB cable, box behind them
        "angle2.jpeg",   # clean box front -- the real tuosiqi logo and astronaut artwork
        "angle4.jpeg"]   # closer view of the actual tray contents, no box
OUT = "hero_test"
OUT_FILE = os.path.join(OUT, "3d-pen-v2b.jpg")


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
    print(f"model {fl.FAL_MODEL} | 1 image | ${price:.4f}")

    if os.path.exists(OUT_FILE):
        print(f"already there, skipping (never re-bill): {OUT_FILE}")
        return

    print("generating…")
    fl._fal_scene(refs[0], fl.CATALOG_HERO_V2, OUT_FILE, refs=refs)
    print(f"-> {OUT_FILE}")

    row = {
        "processed_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "sku": SKU,
        "provider": f"fal:{fl.FAL_MODEL}",
        "status": "test-ok",
        "fal_images_new": 1,
        "fal_images_reused": 0,
        "est_cost_usd": f"{price:.4f}",
        "output_dir": OUT_FILE,
        "error": "CatalogHero v2 prompt test (revised, photography-only, no AI text) — check vs. hero_test/3d-pen-v2.jpg",
    }
    new = not os.path.exists("processed_products.csv")
    with open("processed_products.csv", "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)
    print(f"logged 1 billed image, ${price:.4f}")


if __name__ == "__main__":
    main()
