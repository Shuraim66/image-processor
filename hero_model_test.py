"""One-off: the same hero prompt on two cheaper models, to compare fidelity per rupee.

    export FAL_KEY=...
    .venv/bin/python hero_model_test.py        # 2 images: qwen $0.03 + muse $0.01
"""
import csv, datetime, os

import fal_listing as fl
from hero_prompt_test import PRODUCT, REFS, OUT, PROMPT_B

MODELS = ["qwen-image-edit-2511", "muse-image"]


def main():
    if not os.environ.get("FAL_KEY"):
        raise SystemExit("FAL_KEY is not set in this shell — export it and run again.")
    os.makedirs(OUT, exist_ok=True)
    folder = os.path.join("input", PRODUCT)
    refs = [os.path.join(folder, r) for r in REFS]

    total = sum(fl.FAL_MODELS[m]["usd"] for m in MODELS)
    print(f"{len(MODELS)} images | ${total:.3f}")
    rows = []
    for model in MODELS:
        out = os.path.join(OUT, f"{model}.jpg")
        if os.path.exists(out):
            print(f"  {model}: already there, skipping (never re-bill)")
            continue
        price = fl.FAL_MODELS[model]["usd"]
        print(f"  {model}: generating (${price:.4f})…")
        try:
            fl._fal_scene(refs[0], PROMPT_B, out, model=model, refs=refs)
        except Exception as e:                      # one model failing must not lose the other
            print(f"  {model}: FAILED — {type(e).__name__}: {e}")
            continue
        print(f"  {model}: {out}")
        rows.append([datetime.datetime.now().isoformat(timespec="seconds"), PRODUCT,
                     "hero_model_test", model, 1, f"{price:.4f}",
                     "same prompt B, same 3 references — model comparison"])
    if rows:
        with open("processed_products.csv", "a", newline="") as fh:
            csv.writer(fh).writerows(rows)
        print(f"logged {len(rows)} billed image(s), ${sum(float(r[5]) for r in rows):.3f}")


if __name__ == "__main__":
    main()
