#!/usr/bin/env bash
# Fetch Draw Things' OFFICIAL pre-generated gRPC stubs (no protoc needed) and
# install the extra deps for the --bg-provider drawthings path.
# Run from the repo root:  bash setup_drawthings.sh
set -euo pipefail

base="https://raw.githubusercontent.com/drawthingsai/draw-things-comfyui/main/src/generated"
mkdir -p generated
for f in imageService_pb2.py imageService_pb2_grpc.py config_generated.py __init__.py; do
  echo "fetching $f"
  curl -fsSL "$base/$f" -o "generated/$f"
done

# ensure the stubs are importable as a package
[ -f generated/__init__.py ] || echo "" > generated/__init__.py

python -m pip install grpcio protobuf flatbuffers

echo
echo "Done. Draw Things stubs are in ./generated/."
echo "Next: enable the Draw Things API server (gRPC), then:"
echo "  export DT_HOST=127.0.0.1 DT_PORT=7859 DT_MODEL='<exact model name>' DT_STEPS=8"
echo "  python gallery_pipeline.py --sku SCOOTER-LED-PINK --bg-provider drawthings"
