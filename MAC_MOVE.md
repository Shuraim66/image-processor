# Moving this repo to the Mac — checklist

## 1. Rebuild the environment (the Linux .venv does NOT transfer)
```bash
cd image-processor
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
- On first run, **rembg re-downloads its model** (~1 GB bria) to your Mac's cache.
  To skip the big download, the code can use the tiny `u2netp` model instead.

## 2. Smoke-test the whole pipeline FREE first (no Draw Things needed)
```bash
python gallery_pipeline.py --sku SCOOTER-LED-PINK --bg-provider procedural --no-gemini
```
If `gallery_out/SCOOTER-LED-PINK/01..07` appear, the move worked. ✅
(Fonts are bundled in `assets/fonts`, so rendering is OS-independent now.)

## 3. Turn on Draw Things (slots 3 & 4) — see DRAWTHINGS_SETUP.md
Pending, in order:
- [ ] Install Draw Things; enable API Server (gRPC, TLS, Model Browser).
- [ ] Download **Qwen-Image-Edit 2509** (Q3_K_M for 18 GB) + **Lightning LoRA**.
- [ ] `pip install -r requirements-drawthings.txt`
- [ ] Get `imageService.proto` from `drawthingsai/draw-things-community`, then
      generate stubs (`grpc_tools.protoc …`).
- [ ] Finalize `DrawThingsProvider._generate()` in `providers.py` (3 field names)
      against your running server — the only part I couldn't verify off-Mac.
- [ ] `export DT_HOST/DT_PORT/DT_MODEL/DT_STEPS[/DT_TLS]` and run
      `--bg-provider drawthings`.
- Safety net: if Draw Things is unreachable, it auto-falls back to procedural.

## 4. Optional — product-specific copy
```bash
export GEMINI_API_KEY=...   # free text tier
python gallery_pipeline.py --sku SCOOTER-LED-PINK --bg-provider drawthings
```

## What is already handled (no action needed)
- Fonts bundled + portable (was hardcoded to a Linux path — fixed).
- `.gitignore` excludes `.venv/`, outputs, models, and the generated gRPC stubs.
- Procedural background + full 7-slot pipeline tested end-to-end.
```
