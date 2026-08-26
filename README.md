# image-processor

Toy product photo pipeline for **The Toy Gift Shop** — turns raw product photos
into a Shopify-ready listing gallery and import CSV. Everything runs **locally
and free** — cutouts, copy, graphics and quality checks. Nothing calls a cloud
API and nothing regenerates the product itself: the catalog images are built from
the original product pixels, and only the surroundings are created.

## Quick start (clone & run)

```bash
git clone https://github.com/Shuraim66/image-processor.git
cd image-processor
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
```

First run downloads the cutout model (BiRefNet-general, 973 MB) once, into
`~/.rembg/models/`.

### 1. Analyze photos → product.json (local, no API)
```bash
ollama pull qwen3-vl:8b          # once
python analyzer.py --all         # multi-photo → output/<SKU>/product.json
# no model handy? add --no-ollama for deterministic fallback copy
```

### 2. Size data (optional, per SKU)
```bash
python specs.py             # what is measured, what will skip the size card
python specs.py --read      # read printed sizes off packaging photos
python specs.py --template  # blank specs.csv rows to fill from a supplier sheet
```
Products with no real measurements **skip slot 06** and ship a six-image gallery.
Nothing invents a number: a card reading `≈ — cm` looks like a specification.

### 3. Background plates (once)
```bash
python scenes.py            # placeholder plates -> backgrounds/<category>_a|b.jpg
python scenes.py --list     # which category each SKU resolves to
```
Replace these with real Draw Things scenes under the same filenames when you
have them — see `DRAWTHINGS_SETUP.md`.

### 4. Full listing gallery (reads product.json)
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

### 5. Shopify CSV
```bash
python shopify_export.py --price 29.99 --status draft
# writes shopify_import.csv (product row + one row per gallery image)
# products the copy checks flagged are held back; --include-flagged overrides
```
Image Src holds local `output/` paths, which is fine for reviewing the CSV.
Shopify's own importer fetches images over HTTP, so add
`--image-base-url https://your-cdn.example.com/toys/` once they are hosted.
Writes `output/<SKU>/`, one file per slot, named for what it is:

| file | what it is |
|------|------------|
| `catalog-hero` | product on a scene, **no text on the image** |
| `white-background` | clean packshot, marketplace-safe |
| `with-packaging` | product with its retail box, when a box shot exists |
| `every-angle` | the other shots you took, on cards |
| `lifestyle-scene` | in a room, from a second angle |
| `features-and-benefits` | the branded feature card |
| `size-and-specs` | only when real measurements exist |
| `close-up-detail` | auto-aimed at the product's densest detail |

Listing order lives in `gallery_pipeline.SLOT_ORDER`, not in a numeric filename
prefix, so Shopify positions stay correct while the names stay readable.

## Background providers (slots 3 & 4)

`--bg-provider`:
- **folder** (default) — reads plates from `backgrounds/`, most specific first:
  `<SKU>_a.*`, then `<category>_a.*`, then `_a.*` (missing → procedural).
- **procedural** — soft studio gradient, free, offline.

## Layout
```
input/<SKU>/*.jpg     raw product photos you supply — never written to
output/<SKU>/         generated: 01_main … 07_detail, product.json, quality-report.json
output/_cutouts/      cutout cache      output/_manifest.json   build record
logo.png              brand watermark / badge (transparent)
specs.json            per-SKU size-card data (dimensions, badges)
assets/fonts/         bundled faces + licences (OS-portable rendering)
backgrounds/          scene plates, one pair per category (see scenes.py)
process_products.py   cutout, trimming and canvas primitives
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
- **Watch memory, not cores.** A rembg worker peaks at 6-7 GB on full-res iPhone
  photos, so `--jobs` is capped by RAM, not core count — on 18 GB that is **one
  worker**, and `--jobs` clamps itself and says so. Most of that peak is the
  full-res RGBA image rather than the model, so a smaller `REMBG_MODEL` buys
  speed, not headroom. Downscaling the source photos is the real lever.

## Notes
- Fonts are bundled, so rendering works on macOS/Linux without system fonts.
  Anton, Baloo 2, Fredoka and Montserrat are SIL OFL; Luckiest Guy is Apache 2.0.
  Each product's display face follows its scene category — see `typeset.py`.
- Size data lives in `specs.json` (checked in) and `specs.csv` (local, gitignored).
- Nothing calls a cloud API. Copy comes from the local VLM via Ollama.
- The `main` catalog image is kept pure white (no watermark) for marketplace rules:
  Google Merchant Center disapproves product images carrying a watermark or logo.
- The cutout model is pinned to an MIT-licensed BiRefNet. Do **not** call
  `rembg.new_session()` bare — its default is `bria-rmbg`, which is CC BY-NC and
  not licensed for a commercial shop. See `REMBG_MODEL` in `process_products.py`.
- `OLLAMA_VLM` must name a tag you actually pulled; the analyzer reports which it used.
