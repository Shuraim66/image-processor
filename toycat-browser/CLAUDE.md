# toycat-browser — THE TOY GIFT SHOP catalog automation

A local catalog automation engine with AI-assisted product understanding and
browser-based ChatGPT image generation. Not a script that asks an AI to make
toy pictures.

## Isolation rule

This directory is self-contained. The Draw Things / Qwen Image Edit pipeline in
the repository root (`analyzer.py`, `gallery_pipeline.py`, `process_products.py`,
`providers.py`, `quality.py`, …) is **legacy reference code**. Do not import it,
refactor it, migrate it, or delete it. This app has its own virtualenv at
`toycat-browser/.venv` and its own `toycat` console script.

## Authority model

| Thing | Role |
|---|---|
| Source photographs | truth |
| Qwen3-VL (Ollama) | product intelligence |
| Claude in Chrome | browser operator |
| ChatGPT Images | creative image generator |
| Python | deterministic controller and post-processor |
| TTGS logo | locked brand asset |
| QC | final authority |

**Product accuracy outranks image creativity.** A plain image of the correct
product beats a beautiful image of a changed product.

## Non-negotiables

These are enforced in code, not just documented. Config that violates them is
rejected at load time.

- `PRODUCT_LOCK` (`prompts/product-lock.txt`) is injected into every generation
  prompt. `PromptLibrary.render` refuses to return a prompt without it.
- Six images, one request each. Never one sheet
  (`catalog.generation.one_image_per_request`).
- Output filenames are owned by Python, never by ChatGPT
  (`states.CANONICAL_FILENAMES`).
- The watermark is mandatory. A failed watermark is `FAILED_BRANDING`, never a
  silent pass.
- The logo is never generated. It is `assets/brand/the-toy-gift-shop-logo.png`
  with a pinned SHA-256; a mismatch is `FAIL_BRAND_ASSET`.
- A vision model may never override a deterministic QC failure
  (`qc.fidelity.vision_model_can_override_deterministic` must stay `false`).
- No `AI_GUESS` provenance. A fact that is not visible is `UNKNOWN`.
- Uniform scaling only. Never stretch, squash, warp or liquify a product.
- A provider may not report success without a downloaded file on disk
  (`GenerationResult.__post_init__` raises).
- Never log cookies, tokens or passwords. `SecretRedactingFilter` is attached to
  every handler; never bypass it.
- Original photographs are read-only. Every transformation writes somewhere
  under `working/`; `write_working_copy` refuses a destination equal to its
  source.
- Working copies carry no EXIF. The source photos have GPS coordinates in them
  and working copies are uploaded to an external service, so
  `input.working_copy.strip_metadata` cannot be set to `false`.
- A file that fails to decode never reaches an upload. `inspect_image` runs a
  structural check *and* a full decode, because `verify()` passes truncated
  JPEGs that `load()` rejects.

## Memory budget (M3 Pro, 18 GB)

Never run heavyweight models concurrently. Qwen3-VL analysis, browser
generation and QC run sequentially, and the model is released between stages
(`catalog.analysis.release_model_between_stages`). Do not add Qwen Image Edit
2511, Draw Things, ComfyUI, FLUX or SDXL — those caused the memory pressure this
project exists to avoid.

## Layout

```
config/     five JSON files; every threshold lives here, none in Python
working/    scratch: scan manifest + normalized copies; safe to delete
prompts/    product-lock.txt + one template per slot; tune without touching code
assets/     brand/ (locked logo), backgrounds/, scenes/
data/       sku-registry.json (Phase 5)
logs/       catalog.log, browser.log, qc.log — one run_id per run
src/toycat_browser/
tests/      tests/fixtures/dumpling/ is a mandatory regression case
```

Per-product output follows spec §37: `products-output/product-NNN/` with
`input-reference/`, `working/`, `output/`.

## Commands

```bash
toycat doctor        # environment preflight — start here
toycat config        # show validated configuration
toycat prompts       # templates and their placeholders
toycat providers     # image providers and availability
toycat scan DIR      # discover + validate input photos; --normalize, --all, --json
```

The remaining pipeline commands (`group`, `analyze`, `generate`, `validate`,
`run`, `batch`, `retry`, `cleanup`) exist and exit non-zero naming the phase
that builds them. Keep it that way: an unbuilt stage must fail loudly.

## Notes for Phase 3 (grouping)

`working/scan/scan.json` is the grouping engine's input. Read it with
`scan.read_manifest`; do not re-walk the folder.

**Capture timestamps are not uniformly trustworthy.** Each record carries a
`timestamp_source`. Photos straight from a phone give `EXIF_ORIGINAL` and are a
genuine proximity signal. Photos that lost their EXIF (copied, exported,
screenshotted) fall back to `FILE_MTIME`, and a bulk copy gives every one of
them the *same* mtime — which would falsely pull unrelated products together.
Down-weight or ignore `FILE_MTIME` when computing timestamp proximity; only
`EXIF_ORIGINAL` and `EXIF_DIGITIZED` deserve the configured `timestamp_weight`.

Records already carry `sha256` (exact duplicates are collapsed before grouping
ever runs), `filename_hint`, orientation-corrected `width`/`height`, and
`camera_make`/`camera_model`. Note that phone-style names like `IMG_1002.jpg`
reduce to a useless hint — that is expected, and hints must never be
authoritative.

## Development

```bash
cd toycat-browser
.venv/bin/python -m pytest
```

Build in phases (spec §62). Do not skip ahead. Complete: Phase 1 (scaffold,
CLI, config, logging, tests) and Phase 2 (folder scanner, file validation, HEIC,
image metadata). Phase 3 is visual grouping, duplicate detection and group
verification.

When you add a phase, add its tests and un-skip the matching entry in
`tests/test_spec_coverage.py`.
