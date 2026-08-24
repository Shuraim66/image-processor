#!/usr/bin/env python3
"""
Background providers for the lifestyle slots (3 & 4).

A provider returns a *bare* square background scene (PIL RGBA, W x W). The
pipeline then composites the REAL product cutout on top — the scene is never
trusted to contain the product, which keeps every listing product-faithful.

    ProceduralProvider   free, offline, works everywhere (default / fallback)
    DrawThingsProvider   local Draw Things gRPC server on your Mac (Qwen-Image)

Draw Things note: this Linux dev box can't reach a Draw Things server, so the
gRPC provider is written against Draw Things' documented interface and MUST be
finalized/verified on your Mac (see DRAWTHINGS_SETUP.md). If it can't connect or
errors, it logs a warning and falls back to ProceduralProvider so the batch
never dies.
"""

import os
import sys
from PIL import Image, ImageFilter
import make_hero as mh

W = mh.W


def _tint(theme, variant):
    """Slightly shift the procedural background per variant so A/B differ."""
    shifts = {
        "A": {"bg_top": (232, 244, 255)},   # cool daylight
        "B": {"bg_top": (255, 244, 236)},   # warm daylight
    }
    return {**theme, **shifts.get(variant, {})}


class BackgroundProvider:
    name = "base"

    def scene(self, sku, cutout_path, original_path, variant, prompt):
        raise NotImplementedError


class ProceduralProvider(BackgroundProvider):
    """Soft studio gradient + bokeh. Free, deterministic, always available."""
    name = "procedural"

    def scene(self, sku, cutout_path, original_path, variant, prompt):
        theme = _tint(mh.THEME, variant)
        return mh.make_background(theme)


class DrawThingsProvider(BackgroundProvider):
    """Drives a local Draw Things gRPC server (text-to-image) to make a bare
    lifestyle scene, then the pipeline composites the real product on top.

    Config via env:
        DT_HOST (default 127.0.0.1), DT_PORT (default 7859)
        DT_MODEL (Draw Things model name, e.g. 'qwen_image_edit_2509_q3_k_m.gguf')
        DT_TLS  ('1' to use TLS with certs in ./dt_certs/)
        DT_STEPS (default 8, tuned for a Lightning LoRA)
    """
    name = "drawthings"

    def __init__(self):
        self.host = os.environ.get("DT_HOST", "127.0.0.1")
        self.port = int(os.environ.get("DT_PORT", "7859"))
        self.model = os.environ.get("DT_MODEL", "")
        self.steps = int(os.environ.get("DT_STEPS", "8"))
        self.use_tls = os.environ.get("DT_TLS") == "1"
        self._fallback = ProceduralProvider()
        self._stub = self._connect()

    def _connect(self):
        """Open the gRPC channel + stub. Returns None if unavailable.

        Stubs are the OFFICIAL pre-generated ones — no protoc. Copy these from
        github.com/drawthingsai/draw-things-comfyui/src/generated/ into ./generated/:
            imageService_pb2.py  imageService_pb2_grpc.py  config_generated.py  __init__.py
        Then: pip install grpcio protobuf flatbuffers
        """
        try:
            import grpc
            from generated import imageService_pb2 as pb            # noqa: F401
            from generated import imageService_pb2_grpc as pbg
        except Exception as exc:  # stubs/grpc not present (e.g. this sandbox)
            print(f"  [drawthings] generated stubs/grpc unavailable ({exc}); "
                  f"using procedural", file=sys.stderr)
            return None
        try:
            target = f"{self.host}:{self.port}"
            if self.use_tls:
                with open("dt_certs/root_ca.crt", "rb") as f:
                    creds = grpc.ssl_channel_credentials(f.read())
                channel = grpc.secure_channel(target, creds)
            else:
                channel = grpc.insecure_channel(target)
            grpc.channel_ready_future(channel).result(timeout=5)
            return pbg.ImageGenerationServiceStub(channel)
        except Exception as exc:
            print(f"  [drawthings] cannot reach {self.host}:{self.port} ({exc}); "
                  f"using procedural", file=sys.stderr)
            return None

    def scene(self, sku, cutout_path, original_path, variant, prompt):
        if self._stub is None:
            return self._fallback.scene(sku, cutout_path, original_path, variant, prompt)
        try:
            return self._generate(prompt)
        except Exception as exc:
            print(f"  [drawthings] generate failed for {sku}/{variant} ({exc}); "
                  f"falling back to procedural", file=sys.stderr)
            return self._fallback.scene(sku, cutout_path, original_path, variant, prompt)

    def _build_config_fbs(self):
        """Serialize the generation configuration as FlatBuffer bytes.

        Ported from the official extension: build a `GenerationConfigurationT`
        and pack it. Verified field/class names against draw-things-comfyui;
        two values commonly need a per-setup tweak on the Mac (flagged below):
          * startWidth/startHeight are in UNITS OF 64 px (1024 -> 16).
          * `sampler` is left at the model default; set it if you want a specific one.
        """
        import flatbuffers
        import random
        from generated import config_generated as cfg

        c = cfg.GenerationConfigurationT()
        if self.model:
            c.model = self.model               # exact model name from the browser
        c.startWidth = 16                      # 16 * 64 = 1024 px  (tweak if px-based)
        c.startHeight = 16
        c.steps = self.steps
        c.seed = random.randint(0, 2**31 - 1)
        c.batchCount = 1
        c.batchSize = 1
        c.guidanceScale = 2.5                  # low; suits a Lightning LoRA
        c.strength = 1.0                       # full (text-to-image, no init image)

        builder = flatbuffers.Builder(0)
        builder.Finish(c.Pack(builder))
        return bytes(builder.Output())

    def _generate(self, prompt):
        """Verified against the official extension's src/draw_things.py."""
        import io
        from generated import imageService_pb2 as pb

        request = pb.ImageGenerationRequest(
            prompt=prompt,
            negativePrompt="text, watermark, logo, people, hands, clutter, low quality",
            configuration=self._build_config_fbs(),   # FlatBuffer bytes
        )
        img = None
        for resp in self._stub.GenerateImage(request):   # server streams results
            for gi in getattr(resp, "generatedImages", []) or []:
                data = getattr(gi, "data", None)
                if not data:
                    continue
                w = getattr(gi, "width", 0) or 0
                h = getattr(gi, "height", 0) or 0
                ch = getattr(gi, "channels", 0) or 0
                if w and h and ch:                 # raw pixel buffer (DT's format)
                    mode = "RGBA" if ch == 4 else "RGB"
                    img = Image.frombytes(mode, (w, h), bytes(data)).convert("RGBA")
                else:                              # fallback: encoded PNG/JPEG bytes
                    img = Image.open(io.BytesIO(bytes(data))).convert("RGBA")
        if img is None:
            raise RuntimeError("no image in Draw Things response "
                               "(often an out-of-memory failure on the server)")
        return img.resize((W, W), Image.LANCZOS)


class FolderProvider(BackgroundProvider):
    """Reads pre-made scenes you exported from the Draw Things app (or anywhere).

    Looks for  backgrounds/<SKU>_a.*  and  backgrounds/<SKU>_b.*  (also accepts
    a shared backgrounds/_a.* / _b.* used for every SKU). Falls back to
    procedural if a file is missing, so the batch never dies.

    Zero gRPC / protos — generate scenes manually in Draw Things, drop them in
    ./backgrounds, run the pipeline. Great for getting galleries done now.
    """
    name = "folder"
    BG_DIR = "backgrounds"
    EXTS = (".png", ".jpg", ".jpeg", ".webp")

    def __init__(self):
        self._fallback = ProceduralProvider()

    def _find(self, sku, variant):
        v = variant.lower()
        for stem in (f"{sku}_{v}", f"_{v}"):            # per-SKU, else shared
            for ext in self.EXTS:
                p = os.path.join(self.BG_DIR, stem + ext)
                if os.path.exists(p):
                    return p
        return None

    def scene(self, sku, cutout_path, original_path, variant, prompt):
        p = self._find(sku, variant)
        if p is None:
            print(f"  [folder] no background for {sku}/{variant} in "
                  f"{self.BG_DIR}/ (want {sku}_{variant.lower()}.*); using procedural",
                  file=sys.stderr)
            return self._fallback.scene(sku, cutout_path, original_path, variant, prompt)
        return Image.open(p).convert("RGBA").resize((W, W), Image.LANCZOS)


def get_provider(name):
    return {"procedural": ProceduralProvider,
            "folder": FolderProvider,
            "drawthings": DrawThingsProvider}[name]()
