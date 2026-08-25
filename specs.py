#!/usr/bin/env python3
"""
Per-SKU size and badge data, and an honest answer when there isn't any.

The size card is the one slot that cannot be derived from a photograph. Until
now a product with no measurements still got a card, drawn with "≈ — cm" and
dimension arrows spanning nothing — worse than no card at all, because it looks
like a specification.

So: a dimension counts as known only if it contains a digit. Products without
one skip slot 06 entirely and end up with a six-image gallery. Nothing invents a
number, and `--missing` tells you which products are worth measuring.

Data comes from two files, merged, later winning:

    specs.json    checked in; per-SKU entries plus the _default block
    specs.csv     optional, gitignored — sku,height,length[,source]
                  easier to fill in bulk from a supplier sheet

    python specs.py                 # what is known, what is not
    python specs.py --template      # write specs.csv rows for the gaps
    python specs.py --read          # read printed sizes off packaging photos
"""

import argparse
import csv
import json
import os
import sys

JSON_PATH = "specs.json"
CSV_PATH = "specs.csv"
CSV_COLUMNS = ("sku", "height", "length", "source")


def _known(value):
    """A measurement is real only if it has a number in it."""
    return bool(value) and any(ch.isdigit() for ch in str(value))


def load(json_path=JSON_PATH, csv_path=CSV_PATH):
    """Merge specs.json with the optional specs.csv overlay."""
    with open(json_path, encoding="utf-8") as fh:
        specs = json.load(fh)

    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                sku = (row.get("sku") or "").strip()
                if not sku:
                    continue
                entry = specs.setdefault(sku, {})
                for field in ("height", "length", "source"):
                    value = (row.get(field) or "").strip()
                    if value:
                        entry[field] = value
    return specs


def for_sku(specs, sku):
    return {**specs.get("_default", {}), **specs.get(sku, {})}


def has_dimensions(entry):
    """True when both measurements are real numbers, not placeholders."""
    return _known(entry.get("height")) and _known(entry.get("length"))


def audit(specs, skus):
    """-> (known, missing) lists of SKUs."""
    known, missing = [], []
    for sku in skus:
        (known if has_dimensions(for_sku(specs, sku)) else missing).append(sku)
    return known, missing


READ_PROMPT = (
    "Look at these photos of one product. Do the packaging or the product show "
    "PRINTED dimensions — a size in cm, mm or inches? Answer JSON with "
    "'visible', the exact 'text' you read, and 'height_cm'/'length_cm' as "
    "numbers. If you cannot READ an actual printed measurement, set visible "
    "false and both numbers null. Never estimate, guess, or infer a size from "
    "how big the object looks.")

READ_SCHEMA = {
    "type": "object",
    "properties": {"visible": {"type": "boolean"}, "text": {"type": "string"},
                   "height_cm": {"type": ["number", "null"]},
                   "length_cm": {"type": ["number", "null"]}},
    "required": ["visible", "text", "height_cm", "length_cm"],
}


def read_packaging(sku, input_dir="input"):
    """Read printed dimensions off a product's photos. -> dict or None.

    Grounded rather than guessed: the model is told to return null unless it can
    actually read a measurement, so a product photographed without its box
    yields nothing instead of a plausible invention. This is why a packaging
    shot belongs in the standard shot list — it is the only route to
    measurements that scales past a few dozen products.
    """
    import ollama                       # optional: only needed for --read
    import analyzer

    images = analyzer.images_in(os.path.join(input_dir, sku))
    if not images:
        return None
    resp = ollama.chat(
        model=analyzer.resolve_model(),
        messages=[{"role": "user", "content": READ_PROMPT, "images": images}],
        format=READ_SCHEMA,
        options={"temperature": 0.0,
                 "num_ctx": int(os.environ.get("OLLAMA_NUM_CTX", "8192"))},
    )
    found = json.loads(resp["message"]["content"])
    if not found.get("visible") or found.get("height_cm") is None \
            or found.get("length_cm") is None:
        return None
    return {"height": f"≈ {round(found['height_cm'])} cm",
            "length": f"≈ {round(found['length_cm'])} cm",
            "source": f"packaging: {found.get('text', '')[:60]}"}


def write_csv_rows(rows, csv_path=CSV_PATH):
    """Append rows to specs.csv, creating it with a header if needed."""
    exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def _skus(input_dir="input"):
    return sorted(d for d in os.listdir(input_dir)
                  if os.path.isdir(os.path.join(input_dir, d)))


def main():
    ap = argparse.ArgumentParser(description="Report and template per-SKU size data.")
    ap.add_argument("--template", action="store_true",
                    help=f"append rows for unmeasured SKUs to {CSV_PATH}")
    ap.add_argument("--read", action="store_true",
                    help="use the local VLM to read printed sizes off packaging "
                         "photos for unmeasured SKUs, and record what it finds")
    args = ap.parse_args()

    specs = load()
    skus = _skus()
    known, missing = audit(specs, skus)

    for sku in skus:
        entry = for_sku(specs, sku)
        if has_dimensions(entry):
            src = f"  [{entry['source']}]" if entry.get("source") else ""
            print(f"  ok      {sku:26s} {entry['height']} x {entry['length']}{src}")
        else:
            print(f"  skip 06 {sku:26s} no dimensions")
    print(f"\n{len(known)} measured, {len(missing)} will skip the size card.")

    if args.read and missing:
        print(f"\nReading packaging on {len(missing)} unmeasured product(s)...")
        found = []
        for sku in missing:
            try:
                entry = read_packaging(sku)
            except Exception as exc:  # noqa: BLE001 — no model, network, parse
                print(f"  ! {sku}: {exc}", file=sys.stderr)
                continue
            if entry:
                found.append({"sku": sku, **entry})
                print(f"  read    {sku:26s} {entry['height']} x {entry['length']}")
            else:
                print(f"  none    {sku:26s} no printed size in the photos")
        if found:
            write_csv_rows(found)
            print(f"\nWrote {len(found)} measurement(s) to {CSV_PATH}. "
                  f"Check them against the products before publishing.")
        else:
            print("\nNothing readable. Add a packaging shot to the shot list — "
                  "it is the only route to sizes that scales.", file=sys.stderr)
        return 0

    if args.template and missing:
        write_csv_rows([{"sku": s, "height": "", "length": "", "source": ""}
                        for s in missing])
        print(f"Appended {len(missing)} blank row(s) to {CSV_PATH} — "
              f"fill in height and length like '≈ 66 cm'.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
