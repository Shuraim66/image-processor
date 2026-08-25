# Draw Things → gallery pipeline (macOS, M3 Pro 18 GB)

Slots 3 & 4 (lifestyle scenes) come from Draw Things. There are two ways to feed
them in. **Use the folder workflow — it's the recommended path.** The gRPC route
is advanced/optional and needs a proto file you must source yourself.

---

## ✅ RECOMMENDED: folder workflow (no gRPC, no protos)

You generate scenes in the Draw Things **app** and drop them in a folder; the
pipeline composites your real product on top and adds all text/badges/logo.
Identical final images, none of the proto pain.

### 1. Pick a model (18 GB-friendly)
- **Qwen Image Edit 2511** (newer/better than 2509) at a **4-bit or 5-bit** quant.
  Avoid 8-bit — ~20 GB won't fit 18 GB.
- Add a **Qwen Lightning LoRA** (4/8-step) if one matches your model → set steps 4-8.
  If none matches, run ~15-20 steps.
- Test ONE generation in the app first to confirm speed/memory on 18 GB.

### 2. Export scenes to `backgrounds/`
Prompt idea:
> bright modern children's playroom, soft daylight, empty foreground surface,
> product photography, no people, no text

Save each result into `backgrounds/` named:
- `backgrounds/<SKU>_a.jpg`  and  `backgrounds/<SKU>_b.jpg`  (per product), or
- `backgrounds/_a.jpg` / `backgrounds/_b.jpg`  (one shared look for all products).

### 3. Run
```bash
.venv/bin/python gallery_pipeline.py --sku SCOOTER-LED-PINK --bg-provider folder
# add --no-ollama to skip the copy API
```
Any missing background just falls back to the procedural studio look — nothing breaks.

**Why this over gRPC:** the pipeline always composites your *real cutout* on top,
so Draw Things only makes the room — it can't distort the product, and you skip
all proto/stub work.

---

## ⚙️ ADVANCED (optional): fully-automated gRPC

Only if manual export becomes the bottleneck. This needs Draw Things'
`imageService.proto`, which you must obtain from
`github.com/drawthingsai/draw-things-community` (it may pull in imports).

Common failure: `proto: warning: directory does not exist` / `Could not make
proto path relative` → you have **not** created `proto/` and downloaded the
`.proto` into it. protoc can't run without the actual file.

```bash
mkdir proto
# download imageService.proto (+ any imports) into ./proto first!
pip install grpcio grpcio-tools
python3 -m grpc_tools.protoc -Iproto --python_out=. --grpc_python_out=. proto/imageService.proto
```
Then enable the API server (Settings → API Server: gRPC, Model Browser on,
Response Compression off), finalize `DrawThingsProvider._generate()` in
`providers.py` against your stubs, set `DT_HOST/DT_PORT/DT_MODEL/DT_STEPS[/DT_TLS]`,
and run `--bg-provider drawthings`.

If you want this automated without protos at all, the cleaner option is the
**Draw Things MCP server for Claude Code** — ask and I'll wire that instead.
