# image-processor

Toy product photo pipeline for **The Toy Gift Shop** — turns raw product photos
into a Shopify-ready listing gallery and import CSV. Everything runs **locally
and free** — cutouts, copy, graphics and quality checks. Nothing calls a cloud
API and nothing regenerates the product itself: the catalog images are built from
the original product pixels, and only the surroundings are created.

## Install

```bash
git clone https://github.com/Shuraim66/image-processor.git
cd image-processor
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
ollama pull qwen3-vl:8b-instruct-q4_K_M
```

The first cutout downloads BiRefNet-general (973 MB) into `~/.rembg/models/`.
Check the install with `pytest` — 33 tests, a few seconds, no model needed.

Every stage is a subcommand of one entry point, and each takes `--help`:

```bash
toycat --help        # analyze | scenes | specs | build | export
```

`toycat build` and `python gallery_pipeline.py` are the same program with the
same flags; use whichever reads better.

---

## The workflow

### 0. Drop the photos in

```
input/<SKU>/front.jpg, angle2.jpg, angle3.jpg …
```

One folder per product, named as the SKU. `front.jpg` should be the **clearest
whole-product shot** — it drives the white-background image and the close-up
crop. Put packaging shots last; the analyzer finds them on its own.

Four to six photos is the sweet spot. One photo works but costs you the
`every-angle` slot.

> **Transfer them off the phone with AirDrop or a cable.** WhatsApp re-encodes
> 2296×4080 down to 900×1600, and a cutout from that gets upscaled to fill the
> canvas and looks soft. This is the single biggest quality lever in the whole
> pipeline, and it happens before any code runs.

**`input/` is only ever read.** Everything generated lands under `output/`, so
the folder you drop photos into stays exactly as you left it, and the output tree
is safe to delete and rebuild.

### 1. Analyze — photos become copy

```bash
toycat analyze --all              # every product
toycat analyze input/SCOOTER-LED-PINK    # just one
```

Sends every photo of a product to Qwen3-VL **together**, as different views of
one object, and writes `output/<SKU>/product.json`: title, description, bullets,
features, SEO fields, tags, alt text, scene prompts.

Analysis **fails loudly** rather than writing filler. If the model is unreachable
the SKU is skipped and named at the end. `--allow-fallback` opts into placeholder
copy, and anything written that way is flagged for review so it can't ship
silently.

Copy is checked as it is written — `copyguard` catches trademarked names,
drawbacks phrased as features, and claims that outrun the photos. Findings land
in `review_flags` and hold the product back at export.

### 2. Size data — optional, per SKU

```bash
toycat specs                # what is measured, what will skip the size card
toycat specs --read         # read printed sizes off the packaging photos
toycat specs --template     # blank specs.csv rows to fill from a supplier sheet
```

Products with no real measurements **skip the `size-and-specs` slot** and ship a
shorter gallery. Nothing invents a number: a card reading `≈ — cm` still looks
like a specification to a buyer.

### 3. Background plates — once, not per product

```bash
toycat scenes               # placeholder plates -> backgrounds/<category>_a|b.jpg
toycat scenes --list        # which scene category each SKU resolves to
toycat scenes --generate    # generate plates locally with mflux (optional)
```

Each product resolves to a scene category from its own copy — playroom, nursery,
desk, kitchen, garden, outdoor, creative. Plates are reused across every product
in a category, so this is a one-time cost. Drop your own images in under the same
filenames to replace them.

### 4. Build the gallery

```bash
toycat build                             # every SKU
toycat build --sku SCOOTER-LED-PINK      # one
toycat build --resume                    # skip what the manifest says is done
toycat build --reanalyze                 # photos changed: redo the copy too
toycat build --vlm-check                 # ask the VLM if the render matches the product
```

Per product: cut out the product, derive a palette from its own pixels, pick a
hero composition from its shape (wide → poster, tall → side-by-side), render
every applicable slot, then run the quality checks and write
`output/<SKU>/quality-report.json`.

Progress is recorded in `output/_manifest.json` after every product, so an
interrupted batch resumes instead of restarting.

| file | what it is | brand mark |
|------|------------|------------|
| `catalog-hero` | product on a scene, **no text on the image** | yes |
| `white-background` | clean packshot, marketplace-safe | **no** |
| `with-packaging` | product with its retail box, when a box shot exists | **no** |
| `every-angle` | the other shots you took, on cards | yes |
| `lifestyle-scene` | in a room, from a second angle | yes |
| `features-and-benefits` | the branded feature card | yes |
| `size-and-specs` | only when real measurements exist | yes |
| `close-up-detail` | auto-aimed at the product's densest detail | yes |

Listing order lives in `slots.SLOT_ORDER`, not in a numeric filename prefix, so
Shopify positions stay correct while the names stay readable. A slot that does
not apply to a product is simply absent.

### 5. Review before exporting

Read `output/<SKU>/quality-report.json`, or just look at the images. The build
prints a **Needs review** list at the end; those products are held back at the
next step until you deal with them.

The checks are deterministic — dimensions, blank-image, pure-white corners on the
marketplace image, cutout coverage, source sharpness, the brand-mark rules, and
the logo's own SHA-256. `--vlm-check` adds a semantic pass that compares the
render against the real photo.

### 6. Shopify CSV

```bash
toycat export --price 29.99 --status draft
```

Writes `shopify_import.csv` — one product row plus one row per gallery image, in
`SLOT_ORDER`. Products the copy checks flagged are held back; `--include-flagged`
overrides that deliberately.

### 7. Host the images, then import

**Shopify's importer fetches `Image Src` over HTTP, so local paths will not
work.** Upload the images somewhere public first — Shopify's own **Content →
Files** page takes bulk uploads and hands back `cdn.shopify.com` URLs, which
needs no other service — then re-export pointed at them:

```bash
toycat export --price 29.99 --status draft \
  --image-base-url https://cdn.shopify.com/s/files/1/…/
```

Import the CSV under **Products → Import**. Exporting with `--status draft` lets
you check everything in the admin before anything goes live.

---

## Reference

### Environment

| variable | default | what it does |
|---|---|---|
| `OLLAMA_VLM` | `qwen3-vl:8b` | VLM tag; resolves to an installed match and says so |
| `OLLAMA_NUM_CTX` | `8192` | context window for analysis |
| `OLLAMA_VLM_MAX_IMAGES` | `6` | photos sent per analysis call |
| `REMBG_MODEL` | `birefnet-general` | cutout model — see the note below before changing |
| `MAX_ANGLES` | `4` | photos on the `every-angle` card |
| `OLLAMA_VLM_MAX_PX` | `1024` | photos are downscaled to this for the model only |
| `CUTOUT_ALPHA_FLOOR` | `40` | alpha below which a pixel is background haze |
| `CUTOUT_BLOB_KEEP` | `0.05` | smallest blob kept, relative to the largest |
| `TTGS_LOGO_SHA256` | pinned | expected hash of `logo.png` |

### Layout

```
input/<SKU>/*.jpg     raw product photos you supply — never written to
output/<SKU>/         the gallery, product.json, quality-report.json
output/_cutouts/      cutout cache + .box.json sidecars
output/_manifest.json build record, powers --resume
logo.png              brand mark (transparent, hash-pinned)
specs.json            per-SKU size-card data (dimensions, badges)
assets/fonts/         bundled faces + licences (OS-portable rendering)
backgrounds/          scene plates, one pair per category

toycat.py             one entry point over the stages below
analyzer.py           local VLM -> product.json
slots.py              slot vocabulary and listing order
gallery_pipeline.py   orchestrator: cutout -> render -> check
make_hero.py          hero templates (clean, side, poster) + brand mark
gallery.py            infographic / angles / size / detail slots
process_products.py   cutout, trimming and canvas primitives
palette.py            per-product colours from the cutout
scenes.py             scene categories + plate generation
providers.py          background providers (folder, procedural)
typeset.py            per-category display typography
copyguard.py          drawback / invention / trademark checks on copy
specs.py              size data, packaging reader, missing-data report
quality.py            deterministic checks + the VLM semantic check
shopify_export.py     Shopify import CSV
tests/                33 tests over the real catalogue
```

### Running a large batch

Roughly 60 s of analysis plus 50 s of rendering per product on an M3 Pro, so a
thousand products is a ~30 h job. Two things matter more than parallelism:

- **Analyze first, render second.** `toycat analyze --all`, then `toycat build`.
  Ollama and rembg both want the whole machine; running them at once just makes
  both slower.
- **Watch memory, not cores.** A rembg worker peaks at 6–7 GB on full-resolution
  photos, so `--jobs` is capped by RAM, not core count — on 18 GB that is **one
  worker**, and `--jobs` clamps itself and says so. Most of that peak is the
  full-res RGBA image rather than the model, so a smaller `REMBG_MODEL` buys
  speed, not headroom.

### Troubleshooting

| symptom | cause | fix |
|---|---|---|
| `no Ollama model matching …` | tag not pulled | `ollama pull qwen3-vl:8b-instruct-q4_K_M`, or set `OLLAMA_VLM` |
| SKU skipped, named at the end | analysis failed | rerun; `--allow-fallback` only if you accept placeholder copy |
| `source_resolution` warn/fail | photo too small, cutout upscaled | re-transfer the original without WhatsApp; frame tighter |
| `cutout nearly empty` / `almost fully opaque` | background removal missed | check the photo has a plain background and clear edges |
| product held back at export | `review_flags` in `product.json` | fix the copy, or `--include-flagged` deliberately |
| `FAIL_BRAND_ASSET` | `logo.png` changed | restore it, or update `TTGS_LOGO_SHA256` |
| `vlm_check: fail` | the check could not run | it never reports "skipped" when asked for — read the reason |

## Notes

- Fonts are bundled, so rendering works on macOS/Linux without system fonts.
  Anton, Baloo 2, Fredoka and Montserrat are SIL OFL; Luckiest Guy is Apache 2.0.
  Each product's display face follows its scene category — see `typeset.py`.
- Size data lives in `specs.json` (checked in) and `specs.csv` (local, gitignored).
- Nothing calls a cloud API. Copy comes from the local VLM via Ollama.
- The `white-background` and `with-packaging` images are kept free of the brand
  mark: Google Merchant Center disapproves product images carrying a watermark or
  logo, and those are the two a marketplace feed reaches for. A test enforces it.
- The cutout model is pinned to an MIT-licensed BiRefNet. Do **not** call
  `rembg.new_session()` bare — its default is `bria-rmbg`, which is CC BY-NC and
  not licensed for a commercial shop. See `REMBG_MODEL` in `process_products.py`.
