# image-processor

Toy product photo pipeline for **The Toy Gift Shop** — turns raw product photos
into clean catalog images, a WooCommerce CSV, and a full 7-image marketing
listing gallery per product. Background removal and all graphics run **locally
and free**; the only paid/optional piece is AI lifestyle backgrounds.

## Quick start (clone & run)

```bash
git clone https://github.com/Shuraim66/image-processor.git
cd image-processor
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

First run downloads the rembg background-removal model (~1 GB) once.

### 1. Catalog images + WooCommerce CSV
```bash
export GEMINI_API_KEY=...            # free text tier (optional)
python process_products.py
```
Reads `input/<SKU>/*.jpg`, writes white-background images to `output/` and
`woocommerce_import.csv` (SEO title + description via Gemini).
`--dry-run` skips the API (images only, no cost).

### 2. Analyze photos → product.json (local, no API)
```bash
ollama pull qwen3-vl:8b          # once
python analyzer.py --all         # multi-photo → input/<SKU>/product.json
# no model handy? add --no-ollama for deterministic fallback copy
```

### 3. Background plates (once)
```bash
python scenes.py            # placeholder plates -> backgrounds/<category>_a|b.jpg
python scenes.py --list     # which category each SKU resolves to
```
Replace these with real Draw Things scenes under the same filenames when you
have them — see `DRAWTHINGS_SETUP.md`.

### 4. Full 7-image listing gallery (reads product.json)
```bash
python gallery_pipeline.py --sku SCOOTER-LED-PINK
# all SKUs: drop --sku ;  regenerate copy: --reanalyze ;  no model: --no-ollama
# analysis failures skip the SKU; pass --allow-fallback for placeholder copy
```
Colours come from the product's own pixels and the hero picks its composition
from the product's shape — wide products get the poster layout, tall ones the
side-by-side. Pin `theme` in `product.json` to override the palette.

### 5. Shopify CSV
```bash
python shopify_export.py --price 29.99 --status draft \
    --image-base-url https://your-cdn.example.com/toys/
# writes shopify_import.csv (product row + one row per gallery image)
```
Writes `gallery_out/<SKU>/01_main … 07_detail`:

| # | slot | source |
|---|------|--------|
| 01 | pure-white main | catalog |
| 02 | branded hero | template |
| 03/04 | lifestyle scenes | **background provider** |
| 05 | feature infographic | template |
| 06 | size & age card | `specs.json` |
| 07 | detail close-up | template |

## Background providers (slots 3 & 4)

`--bg-provider`:
- **folder** (default) — reads plates from `backgrounds/`, most specific first:
  `<SKU>_a.*`, then `<category>_a.*`, then `_a.*` (missing → procedural).
- **procedural** — soft studio gradient, free, offline.
- **drawthings** — generates scenes automatically via a local Draw Things gRPC
  server. See `DRAWTHINGS_SETUP.md`; run `bash setup_drawthings.sh` first
  (fetches the official gRPC stubs — no protoc). Falls back to procedural if the
  server is unreachable.

## Layout
```
input/<SKU>/*.jpg     raw product photos (one folder per SKU)
logo.png              brand watermark / badge (transparent)
specs.json            per-SKU size-card data (dimensions, badges)
assets/fonts/         bundled faces + licences (OS-portable rendering)
backgrounds/          scene plates, one pair per category (see scenes.py)
process_products.py   catalog + CSV, cutout trimming
gallery_pipeline.py   7-slot gallery orchestrator
make_hero.py          hero templates (side + poster)
gallery.py            infographic / size / detail slots
analyzer.py           local VLM -> product.json
palette.py            per-product colours from the cutout
scenes.py             scene categories + placeholder plates
typeset.py            per-category display typography
providers.py          background providers
```

## Notes
- Fonts are bundled, so rendering works on macOS/Linux without system fonts.
  Anton, Baloo 2, Fredoka and Montserrat are SIL OFL; Luckiest Guy is Apache 2.0.
  Each product's display face follows its scene category — see `typeset.py`.
- `specs.json` numbers are placeholders — fill in real supplier dimensions.
- Never commit API keys; pass `GEMINI_API_KEY` via the environment.
- The `main` catalog image is kept pure white (no watermark) for marketplace rules.
- `OLLAMA_VLM` must name a tag you actually pulled; the analyzer reports which it used.
