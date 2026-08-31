# toycat-browser

Local product catalog automation for THE TOY GIFT SHOP.

Drop raw product photos into `products-input/` — no renaming, no folders, no
SKUs — and the tool groups them by product, analyzes each product locally with
Qwen3-VL, generates six catalog images through an authenticated ChatGPT browser
session, applies the exact TTGS watermark locally, runs QC, and writes
Shopify-ready output to `products-output/`.

## Status

Phase 2 of 12. Working today: `doctor`, `config`, `prompts`, `providers`,
`version`, and `scan`. The remaining pipeline commands are declared and exit
non-zero naming the phase that implements them.

```bash
toycat scan products-input/ --normalize
```

`scan` discovers photos (recursively, ignoring `.DS_Store` and friends),
validates each one, reads EXIF, applies orientation, collapses byte-identical
duplicates, and writes `working/scan/scan.json`. With `--normalize` it also
writes EXIF-corrected, metadata-stripped working copies. Your originals are
never modified.

## Requirements

- macOS on Apple silicon (developed on an M3 Pro / 18 GB)
- Python 3.12+
- [Ollama](https://ollama.com/download) with `qwen3-vl:8b-instruct-q4_K_M`
- Google Chrome with the Claude in Chrome extension, signed in to ChatGPT
- Claude Desktop, for local-file browser tasks

No cloud image API is used. No heavyweight local image generator is installed.

## Setup

```bash
cd toycat-browser
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev,heic]"
.venv/bin/toycat doctor
```

`doctor` reports every dependency it actually observed, and tells you exactly
what to do about anything missing.

## Layout

- `config/` — every tunable threshold (catalog, watermark, grouping, qc, scenes)
- `prompts/` — the mandatory product lock plus one template per catalog image
- `assets/brand/` — the locked TTGS logo, verified by SHA-256
- `logs/` — `catalog.log`, `browser.log`, `qc.log`, stamped with a run id
- `working/` — scan manifest and normalized copies; safe to delete
- `tests/fixtures/dumpling/` — the mandatory product-fidelity regression case

## Isolation

This app does not touch, import or depend on the legacy Draw Things / Qwen Image
Edit pipeline in the repository root. It has its own virtualenv.
