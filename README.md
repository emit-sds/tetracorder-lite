# tetracorder-lite

Containerized USGS Tetracorder (v6) for EMIT mineral identification, with a Python
CLI for running tetracorder and for rebuilding the convolved spectral library when a
new calibration epoch arrives.

## Quick start

```sh
# Run tetracorder on a mounted reflectance file (default action)
docker run --rm \
  -v /path/to/input:/data \
  -v /path/to/output:/output \
  tetracorder-lite

# Build convolved spectral libraries for a new calibration epoch.
# Masters are baked into the image; mount the recipe(s) at /spectral-lib and the
# scene at /data (its ENVI header supplies the target grid).
docker run --rm \
  -v /path/to/scene:/data \
  -v /path/to/recipes:/spectral-lib \
  -v /path/to/output:/output \
  tetracorder-lite convolve
```

## Building the container

```sh
podman build -f Containerfile -t tetracorder-lite .
# or
docker build --platform linux/amd64 -f Containerfile -t tetracorder-lite .
```

The image compiles specpr + Tetracorder (Fortran/ratfor), installs DaVinci, and
sets up the `tetrapy` Python environment via pixi.

## Commands

The container entrypoint is `tetrapy`. Pass a subcommand as the container argument
(defaults to `run` if omitted):

| Command | Description |
|---|---|
| `run` | **(default)** Setup then run tetracorder on the mounted input |
| `setup` | Configure a tetracorder run only (`cmd-setup-tetrun`) |
| `tetrun` | Execute a previously-configured run (`cmd.runtet`) |
| `convolve` | Rebuild the convolved spectral libraries from recipes (pure Python) |
| `cmds2csv` | Convert a `.cmds` recipe to the documented CSV format |
| `validate` | Compare two convolved libraries (per-spectrum RMS) |

Use `--help` on any command for full options:

```sh
docker run --rm tetracorder-lite --help
docker run --rm tetracorder-lite convolve --help
```

## Volume contract

| Mount point | Purpose |
|---|---|
| `/data` | Input: reflectance/L1A file (ENVI format with `.hdr`) — supplies the target grid |
| `/output` | Output: tetracorder results or the newly-convolved libraries |
| `/spectral-lib` | (convolve only) Directory containing the convolution recipes (`conv.s06*` / `conv.r06*`, `.cmds` or `.csv`) |

The unconvolved master libraries (`splib06b`, `sprlb06b`; ~24 MB total) are **baked
into the image** at `/root/sl1/usgs/library06.conv/`, so a convolve run only needs the
recipe(s) mounted at `/spectral-lib` plus the scene at `/data`. To convolve from a
different master vintage, mount a directory over `--spectral-lib` (it must contain
`splib06b` / `sprlb06b`).

## Convolved spectral library

Tetracorder matches observed reflectance against a spectral library convolved to the
instrument's channels. When EMIT gets a new calibration (new wavelengths/FWHM), the
library must be regenerated. `tetrapy convolve` does this in **pure Python**, driven
by a convolution **recipe** — no previously-convolved library is needed as a template.

### How it works

`tetrapy convolve` builds **two** libraries when both are available:

| Library | Master | Recipe (in the same dir) | Output |
|---|---|---|---|
| Standard | `splib06b` | `conv.s06*.cmds` (or `.csv`) | `s06emit_convolved` |
| Research | `sprlb06b` | `conv.r06*.cmds` (or `.csv`) | `r06emit_convolved` |

For each, it:

1. Reads the recipe to learn, per output spectrum, which master records to convolve:
   the spectrum record, its native wavelength grid, and its native FWHM/resolution.
2. Gaussian-convolves each spectrum from its native grid to the target EMIT grid
   (with native-FWHM quadrature correction), matching the USGS Fortran math.
3. Writes a valid specpr library from scratch, reproducing the record layout
   Tetracorder expects — absolute record numbers must line up because the
   fit-scripts reference the library by number (`[splib06] 7170`, `[sprlb06] 1116`).

The target grid comes from the mounted EMIT reflectance ENVI header (`/data/r.hdr` by
default), so wavelength/FWHM self-consistently match the scene. A family is skipped
(with a log line, not an error) if its master or recipe is absent, so a
standard-only run still works.

### The recipe: `.cmds` and `.csv`

The recipe is the same information the USGS Fortran convolution read from a specpr
command script (`conv.s06emitc.cmds`). That script interleaves the meaningful fields
with GUI keystrokes; `tetrapy` parses out only what affects the output:

| Field | Meaning |
|---|---|
| `inwave` | master record # of the spectrum's native wavelengths |
| `inres` | master record # of the spectrum's native FWHM/bandpass |
| `recnum` | master record # of the spectrum itself |
| `title` | output spectrum title (carries the `=a`/`=b` variant tag Tetracorder uses) |

You can supply either format:

- **`.cmds`** — an existing USGS command script (parsed directly; keystrokes ignored).
- **`.csv`** — a GUI-free equivalent with header `inwave,inres,recnum,title`
  (`title` optional). This is the forward-looking format for new libraries; convert
  a `.cmds` once with `tetrapy cmds2csv <in.cmds> <out.csv>` and maintain the CSV.

> **Directory layout note.** `tetrapy convolve` discovers recipes with a **single
> directory** each for recipes (`--recipe-dir`, the `/spectral-lib` mount) and masters
> (`--spectral-lib`, the baked-in `/root/sl1/usgs/library06.conv/` by default). Both
> default to the same when mounted, so you can drop `splib06b`, `sprlb06b`,
> `conv.s06*`, and `conv.r06*` side by side in one folder. Note the upstream
> `spectroscopy-tetracorder` repo keeps these in *different* folders — masters +
> standard recipe under `sl1/usgs/library06.conv/`, research recipe under
> `sl1/usgs/rlib06/` — so if you override the masters mount, stage the pieces
> together first:
> ```sh
> mkdir libs && cp .../library06.conv/{splib06b,sprlb06b,conv.s06*} libs/ \
>   && cp .../rlib06/conv.r06* libs/
> ```

### Version matching (important)

The research library is **additive across Tetracorder versions** — each release adds
spectra, growing the record numbers its fit-scripts reference. The recipe, the master,
and the Tetracorder `cmd.lib.setup.*` you run with must be the **same vintage**. If a
recipe references a master record that isn't present (e.g. a newer recipe against an
older master), that row is written as a **deleted-data placeholder block** rather than
dropped — this preserves the record numbering downstream spectra depend on, and the
build logs each placeholder. (Standard `emita`/`emitc` recipes are identical except
the title tag; the a/c calibration epoch comes from the grid, i.e. from `/data`.)

### Usage

```sh
# Build both libraries. Masters are baked in; mount only the recipes + scene.
# (reads wavelength/FWHM from /data/r.hdr)
docker run --rm \
  -v ./recipes:/spectral-lib -v ./scene:/data -v ./out:/output \
  tetracorder-lite convolve

# Override the reflectance file used for the target grid
docker run --rm \
  -v ./recipes:/spectral-lib -v ./scene:/data -v ./out:/output \
  tetracorder-lite convolve -f /data/new_scene_rfl

# Build a single library from one explicit recipe (bypasses discovery).
# --master here points at the baked-in master (or a mounted one).
docker run --rm \
  -v ./recipes:/spectral-lib -v ./scene:/data -v ./out:/output \
  tetracorder-lite convolve \
    --cmds /spectral-lib/conv.s06emitc.cmds \
    --master /root/sl1/usgs/library06.conv/splib06b \
    --output /output/s06emit_new

# Convolve from a different master vintage (override the baked-in masters)
docker run --rm \
  -v ./recipes:/spectral-lib -v ./masters:/masters \
  -v ./scene:/data -v ./out:/output \
  tetracorder-lite convolve --spectral-lib /masters

# Convert a .cmds recipe to the documented CSV format
docker run --rm -v ./recipes:/spectral-lib tetracorder-lite \
  cmds2csv /spectral-lib/conv.s06emitc.cmds /spectral-lib/conv.s06emitc.csv

# Validate a result against a reference library
docker run --rm -v ./out:/output tetracorder-lite validate \
  /output/s06emit_convolved /root/sl1/usgs/library06.conv/s06emitc
```

Validated against the shipped `s06emitc`: on the same grid, 1365 spectra reproduce the
reference to float precision (median RMS ~1e-7) with identical record structure. See
[`docs/convolved-library-build.md`](docs/convolved-library-build.md) for the full
technical reference.

## Development

The Python CLI lives in `tetrapy/`. Managed with [pixi](https://pixi.sh):

```sh
pixi install
pixi run tetrapy --help
```

To run outside the container (needs numpy + click):

```sh
pip install numpy click
python -m tetrapy --help
```

## Project structure

```
tetracorder-lite/
  Containerfile          # container build (specpr + tetracorder + pixi/tetrapy)
  pyproject.toml         # Python project config (pixi workspace)
  tetrapy/              # Python CLI
    __main__.py         #   click CLI entrypoint
    tetra.py            #   tetracorder run/setup
    convolve.py         #   recipe-driven convolved-library builder (pure Python)
  tetracorder/          # vendored tetracorder + specpr source tree
  data/                 # mineral grouping matrix
  docs/                 # technical documentation
```

## Documentation

- [`docs/build.md`](docs/build.md) — building per-epoch images, build args, and the
  build-time gates.
- [`docs/adding-a-sensor.md`](docs/adding-a-sensor.md) — add a new sensor, recalibrate an
  existing one, and version the resulting container.
- [`docs/convolved-library-build.md`](docs/convolved-library-build.md) — the convolution
  internals and format reference.
