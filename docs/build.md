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

For the baked-library path the two calibration text files are **provenance only**
— the delivered library is already convolved for the epoch's grid. They drive the
convolution only when re-convolving (`--build-arg RECONVOLVE=1`); place them under
`epoch-inputs/` in the build context.

## What the epoch stage does

For emit_c the epoch stage **bakes the finished USGS delivery libraries** and runs
two build-time gates. It does *not* re-convolve by default.

1. **Baked libraries.** The finished convolved libraries — standard
   `library06.conv/s06<sensor>` and research `rlib06/r06<sensor>` — are copied in
   directly (libdata stage). They must be **config-aligned**: `cmd.lib.setup`
   addresses spectra by **absolute specpr record number** (research references up
   to 1338, standard up to 8208 for emit_c), so the library the runtime restart
   opens must contain those records as valid data-starts. The USGS delivery
   (`r06emitc` = 1410 records, `s06emitc` = 8220 records) satisfies this.
2. **`sync-restart`** — sets the restart file's device-protection numbers
   (`iprtw`, `iprty`) to `-(records - 1)` of the libraries actually baked, so
   specpr does not stall on a protection mismatch.
3. **`verify-config`** — a fail-closed gate that validates the sensor-keyed
   `DATASETS/<sensor>`, `restart_files/r1-<slug>`, and `DELETED.channels` against
   the epoch channel count, asserts the restart protection equals `-(records - 1)`
   of each baked library (**protection gate**), *and* asserts every
   `[sprlb06]`/`[splib06]` record referenced in `cmd.lib.setup` is a valid
   data-start in the baked libraries (**record-alignment gate**).

**Why both gates exist.** Two independent conditions each yield a silent
zero-mineral-IDs failure (tetracorder still exits 0):

- *Protection desync.* specpr stores a per-library "device protection" number in
  the restart, equal to `-(records - 1)` where `records = filesize / 1536`. On a
  mismatch specpr prints an *interactive* WARNING; a non-interactive container
  "continues" past it and produces no `.depth` images.
- *Record misalignment.* `cmd.lib.setup` selects each reference spectrum by
  absolute record number. If the baked library is a different vintage/size than
  the config expects, a referenced record is missing or is not a spectrum head;
  tetracorder emits `invalid input` on that material, turns off command
  redirection, and aborts identification (historically manifesting as a `/dev/tty`
  read loop). This is the failure that a re-convolution from a **stale recipe**
  (179 spectra → a 1104-record research library, where record 1116 was out of
  range) originally caused.

The two gates fail the **build** on either condition instead of the container
silently succeeding with no output.

## Re-convolving for a new grid or sensor (opt-in)

The per-epoch re-convolution path is preserved but off by default. Build with
`--build-arg RECONVOLVE=1` to convolve the standard (`splib06b` → `s06<sensor>`)
and research (`sprlb06b` → `r06<sensor>`) libraries onto the epoch grid from the
`WL_FILE`/`FWHM_FILE` calibration deliverable. `sync-restart` and both
`verify-config` gates then run against the freshly-built libraries — so a recipe
that produces a misaligned library fails the build rather than silently yielding
zero mineral IDs. (The convolution recipes must reproduce the config-aligned
record layout; see the Phase-2 recipe-regeneration work.)

## Recommended manual acceptance (smoke run) — NOT automated

Before promoting a freshly built `emit-tc:<sensor>-<epoch>` image, run it against a
known L2A scene and confirm output looks right:

```bash
docker run --rm -v /path/to/known_scene:/data -v /tmp/out:/output emit-tc:emit_c-20260620
# inspect /tmp/out/tetracorder for expected mineral group outputs
```
This step is deliberately manual — we do not commit a fixture scene or run it in
the build. The image tag records which library+config were baked.
