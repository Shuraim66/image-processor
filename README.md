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
python analyzer.py --all         # multi-photo → output/<SKU>/product.json
# no model handy? add --no-ollama for deterministic fallback copy
```

### 3. Size data (optional, per SKU)
```bash
python specs.py             # what is measured, what will skip the size card
python specs.py --read      # read printed sizes off packaging photos
python specs.py --template  # blank specs.csv rows to fill from a supplier sheet
```
Products with no real measurements **skip slot 06** and ship a six-image gallery.
Nothing invents a number: a card reading `≈ — cm` looks like a specification.

### 4. Background plates (once)
```bash
python scenes.py            # placeholder plates -> backgrounds/<category>_a|b.jpg
python scenes.py --list     # which category each SKU resolves to
```
Replace these with real Draw Things scenes under the same filenames when you
have them — see `DRAWTHINGS_SETUP.md`.

### 5. Full listing gallery (reads product.json)
```bash
python gallery_pipeline.py --sku SCOOTER-LED-PINK
# all SKUs: drop --sku ;  regenerate copy: --reanalyze ;  no model: --no-ollama
# analysis failures skip the SKU; pass --allow-fallback for placeholder copy
python gallery_pipeline.py --resume        # skip what the manifest says is built
python gallery_pipeline.py --out-dir /Volumes/Drive/toys   # anywhere you like
```
**`input/` is only ever read.** Every generated file — images, `product.json`,
cutout cache, manifest — goes under `output/`, so the folder you drop photos
into stays exactly as you left it and the output tree is safe to delete.
Progress is recorded in `output/_manifest.json` after every product, so an
interrupted batch resumes instead of restarting. Anything the copy checks or the
image checks flag is listed at the end under "Needs review".
Colours come from the product's own pixels and the hero picks its composition
from the product's shape — wide products get the poster layout, tall ones the
side-by-side. Pin `theme` in `product.json` to override the palette.

### 6. Shopify CSV
```bash
python shopify_export.py --price 29.99 --status draft
# writes shopify_import.csv (product row + one row per gallery image)
# products the copy checks flagged are held back; --include-flagged overrides
```
Image Src holds local `output/` paths, which is fine for reviewing the CSV.
Shopify's own importer fetches images over HTTP, so add
`--image-base-url https://your-cdn.example.com/toys/` once they are hosted.
Writes `gallery_out/<SKU>/01_main … 07_detail`:

| # | slot | source |
|---|------|--------|
| 01 | pure-white main | catalog |
| 02 | branded hero | template |
| 03/04 | lifestyle scenes | **background provider** |
| 05 | feature infographic | template (14-icon set, chosen per product) |
| 06 | size & age card | `specs.json` / `specs.csv` — skipped if unmeasured |
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
input/<SKU>/*.jpg     raw product photos you supply — never written to
output/<SKU>/         generated: 01_main … 07_detail, product.json, quality-report.json
output/_cutouts/      cutout cache      output/_manifest.json   build record
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
copyguard.py          drawback / invention / trademark checks on copy
specs.py              size data, packaging reader, missing-data report
providers.py          background providers
```

## Running a large batch

At roughly 55 s of analysis plus 30 s of rendering per product, a thousand
products is a ~24 h job. Two things matter more than parallelism:

- **Analyze first, render second.** `python analyzer.py --all`, then
  `gallery_pipeline.py`. Ollama and rembg both want the whole machine; running
  them at once just makes both slower.
- **Watch memory, not cores.** A rembg worker peaks around 3.5 GB, so `--jobs`
  is capped by RAM, not by core count — on 18 GB, more than two or three workers
  swaps and the batch gets *slower* than serial. `--jobs` clamps itself and says
  so. `REMBG_MODEL=birefnet-general-lite` (or `u2netp`) cuts the per-worker
  footprint and is the real lever on a small machine.

## Notes
- Fonts are bundled, so rendering works on macOS/Linux without system fonts.
  Anton, Baloo 2, Fredoka and Montserrat are SIL OFL; Luckiest Guy is Apache 2.0.
  Each product's display face follows its scene category — see `typeset.py`.
- Size data lives in `specs.json` (checked in) and `specs.csv` (local, gitignored).
- Never commit API keys; pass `GEMINI_API_KEY` via the environment.
- The `main` catalog image is kept pure white (no watermark) for marketplace rules.
- `OLLAMA_VLM` must name a tag you actually pulled; the analyzer reports which it used.
