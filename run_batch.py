"""Full approved batch run: all 87 products, CatalogHero v2 + Lifestyle where planned.

Approved by the user 2026-09-23: $7.26 for 141 paid images (82 CatalogHero + 59 Lifestyle).
Already-satisfied paid slots (3D Pen, Dancing Cactus, Toy Story, Oreo, half of the swim cap)
are skipped for free by _fal_scene's own existence guard -- nothing here re-bills them.

RESUME_FROM: products [0:RESUME_FROM] were already fully processed in the first run (before
the download-retry fix landed and the batch was stopped) -- skip them here so we don't waste
CPU re-rendering FeatureCard/Hero_titled/branding for already-finished products. Their paid
slots are safe either way (the existence guard prevents re-billing), this is purely a time
optimization. Any product that failed (content policy, etc.) is flagged and skipped over --
per the user, those get handled manually at the end, not retried automatically here.

Logs one row per product with new paid images to processed_products.csv, matching its real
9-column schema exactly (see the two malformed-row fixes earlier this session).

    export FAL_KEY=...
    .venv/bin/python run_batch.py
"""
import csv, datetime, json, os, sys, traceback

import fal_listing as fl
import process_products as pp

LOG_FIELDS = ["processed_at", "sku", "provider", "status", "fal_images_new",
              "fal_images_reused", "est_cost_usd", "output_dir", "error"]

RESUME_FROM = 19  # 0-indexed: skip the first 19 rows of catalog_products.csv, already done


def log_row(fh, **kw):
    row = {k: kw.get(k, "") for k in LOG_FIELDS}
    csv.DictWriter(fh, fieldnames=LOG_FIELDS).writerow(row)
    fh.flush()


def main():
    if not os.environ.get("FAL_KEY"):
        raise SystemExit("FAL_KEY is not set in this shell — export it and run again.")

    with open("catalog_products.csv") as f:
        products = list(csv.DictReader(f))[RESUME_FROM:]

    new_file = not os.path.exists("processed_products.csv")
    logf = open("processed_products.csv", "a", newline="")
    if new_file:
        csv.DictWriter(logf, fieldnames=LOG_FIELDS).writeheader()

    total_before = fl.fal_cost
    ok, failed = 0, []

    for i, r in enumerate(products, RESUME_FROM + 1):
        sku = r["sku"]
        folder = os.path.join("input", r["handle"].upper())
        out_dir = os.path.join(folder, "output")
        raws = pp.raw_images_in(folder)
        profile = json.load(open(os.path.join(folder, "product.json"), encoding="utf-8"))

        calls_before, cost_before = fl.fal_calls, fl.fal_cost
        try:
            fl.build(profile["sku"], raws, profile, out_dir)
            status, error = "ok", ""
            ok += 1
        except Exception as e:
            status, error = "failed", f"{type(e).__name__}: {e}"
            failed.append(sku)
            print(f"!!! FLAGGED FOR MANUAL FOLLOW-UP: {sku}: {error}", flush=True)
            traceback.print_exc()
        new_calls = fl.fal_calls - calls_before
        new_cost = fl.fal_cost - cost_before

        print(f"[{i}/{len(products) + RESUME_FROM}] {sku}: {new_calls} new paid image(s), "
              f"${new_cost:.4f} -- {status}", flush=True)

        if new_calls or status == "failed":
            log_row(logf, processed_at=datetime.datetime.now().isoformat(timespec="seconds"),
                     sku=sku, provider=f"fal:{fl.FAL_MODEL}", status=status,
                     fal_images_new=new_calls, fal_images_reused=0,
                     est_cost_usd=f"{new_cost:.4f}" if new_cost else "",
                     output_dir=out_dir, error=error)

    logf.close()
    total_new = fl.fal_cost - total_before
    print(f"\nDone. {ok}/{len(products)} products processed OK this run.")
    if failed:
        print(f"FLAGGED for manual follow-up ({len(failed)}): {failed}")
    print(f"New spend this run: ${total_new:.4f}")


if __name__ == "__main__":
    main()
