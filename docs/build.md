# Building per-epoch images

Base + libdata are built once; each epoch is a build-arg-parameterized final stage.

```bash
# Base image (rebuild only when engines/deps change)
docker build --platform linux/amd64 --target base -t emit-tc-base:$(git rev-parse --short HEAD) .

# Per-epoch image (EMIT emit_c, 285 ch, 2026-06-20 calibration)
docker build --platform linux/amd64 --target epoch \
  --build-arg SENSOR=emit_c \
  --build-arg NCHANS=285 \
  --build-arg EPOCH_TAG=20260620 \
  --build-arg WL_FILE=epoch-inputs/emit_wl_20260620.txt \
  --build-arg FWHM_FILE=epoch-inputs/emit_fwhm_20260620.txt \
  -t emit-tc:emit_c-20260620 .
```

The convolution grid comes from the two text files (the calibration deliverable),
not from a scene. Place them under `epoch-inputs/` in the build context.

## Recommended manual acceptance (smoke run) — NOT automated

Before promoting a freshly built `emit-tc:<sensor>-<epoch>` image, run it against a
known L2A scene and confirm output looks right:

```bash
docker run --rm -v /path/to/known_scene:/data -v /tmp/out:/output emit-tc:emit_c-20260620
# inspect /tmp/out/tetracorder for expected mineral group outputs
```
This step is deliberately manual — we do not commit a fixture scene or run it in
the build. The image tag records which library+config were baked.
