# tetracorder-lite

Containerized USGS Tetracorder (v6) for EMIT mineral identification, with a Python
CLI (`tetrapy`) that drives the full pipeline — convolving the spectral library for a
new calibration epoch, setting up and running tetracorder, and aggregating the results
into L2B mineral products — from a single YAML config.

Note - this is not the authoritative version of Tetracorder. Please see [here](https://github.com/PSI-edu/spectroscopy-tetracorder)
if that's what you're after.  This version is what is used by EMIT - the core code is consistent,
and we will work to keep this in-sync with the original codebase.  Major difference are that this
version does not hold all convolved libraries to keep the containers small (they are instead
intended to be convolved by the the container).  Python scripts for output conversion
are also included, and will be expanded upon in the future.

This repository is also a work in progress,
that we are continuing to try and revise and simplify to aid in community use and uptake
of Tetracorder.  Suggested contributions are welcome as PRs.

## Quick start

The pipeline is driven by a YAML config (see [`config.yml`](config.yml)). Mount your
data and output directories, then point `tetrapy run` at the config:

```sh
docker run --rm \
  -v /path/to/input:/data \
  -v /path/to/output:/output \
  tetracorder-lite \
  tetrapy run config.yml \
    --data.rfl /data/emit20230728t214153_rfl \
    --data.rfluncert /data/emit20230728t214153_uncert
```

Every config value can be overridden on the command line with dotted `--key value`
flags (see [Overriding config on the CLI](#overriding-config-on-the-cli)).

## Building the container

```sh
podman build -f Containerfile -t tetracorder-lite .
# or
docker build --platform linux/amd64 -f Containerfile -t tetracorder-lite .
```

The image compiles specpr + Tetracorder (Fortran/ratfor), installs DaVinci, and
sets up the `tetrapy` Python environment via pixi.

## The pipeline

`tetrapy run <config.yml>` executes an ordered pipeline. Each stage has an `enabled`
flag in the config, so you can run any subset:

| Stage | Config key | What it does |
|---|---|---|
| Convolve | `convolve` | Convolve the reference + research master libraries onto the scene's instrument grid and integrate them into tetracorder |
| Setup | `setup` | Configure a tetracorder run (`cmd-setup-tetrun`) |
| Tetrun | `tetrun` | Execute the configured run (`cmd.runtet`) |
| Postprocess | `postprocess` | Convert matched tetracorder outputs into COGs and/or delete matched paths |
| Aggregate | `aggregate` | Aggregate tetracorder outputs into L2B mineral/uncertainty products |

After Setup initializes the output directory, the resolved config is written to
`{output}/config.yml` for provenance.

## Configuration

The config is a nested YAML file. Top-level keys hold shared values (`output`,
`data`, `tetracorder`); the remaining keys are the pipeline stages, each gated by its
own `enabled` flag. Paths refer to locations **inside the container**.

```yaml
output: /output/tetracorder      # Must not exist unless setup.autoremove is True
data:
  rfl:       /data/rfl            # Reflectance data (not the .hdr)
  rfluncert: /data/rfluncert      # Reflectance uncertainty data (not the .hdr)
tetracorder:
  version: 6.00a
  mode:    cube                   # "cube" or "singlespectrum"

convolve:
  enabled:   True
  reflib:    /root/tetracorder/sl1/usgs/library06.conv/splib06b   # unconvolved reference master
  reslib:    /root/tetracorder/sl1/usgs/library06.conv/sprlb06b   # unconvolved research master
  output:    /conv/
  integrate: True                 # Wire the convolved libraries into tetracorder
  name:      ${setup.sensor}       # Interpolated from setup.sensor

setup:
  enabled:    True
  autoremove: True                # Remove output dir first (setup requires it absent)
  sensor:     tetrapy
  geology:    True
  args:       ["1", "-T", "-20", "80", "C", "-P", ".5", "1.5", "bar"]

tetrun:
  enabled: False
  args:    ["band", "20", "gif"]

postprocess:
  enabled:     True
  tetracorder: ${output}                  # Glob root for both cogs and remove
  cogs:                                   # Convert matched rasters to COGs (omit to skip)
    output:        ${output}/cogs         # Mirrored destination root
    skip_existing: False                  # False == overwrite existing COGs
    glt:           ${data.glt}            # EMIT L1B GLT ENVI; orthorectify onto its map grid (omit for raw)
    glob:                                 # Rasters to convert (relative to tetracorder)
      - "group.*/*.depth.gz"
      - "group.*/*.fit.gz"
      - "results.masses/*.png"           # 8-bit PNG products (same grid as the rasters)
  remove:                                 # Paths (files/dirs) to delete (omit to skip)
    - "results.group*"
    - "results.dual*"
    - "results.case*"

aggregate:
  enabled:     False
  tetracorder: ${output}
  output:      ${output}/l2b/
  reflib:      ${convolve.output}/reflib.envi
  reslib:      ${convolve.output}/reslib.envi
  output_as:   ["nc", "tif"]      # Product formats: NetCDF and/or GeoTIFF

emit_fmt:                         # TODO — not yet implemented
  enabled: False
```

### Interpolation (`${...}`)

Values may reference other parts of the config with `${...}` syntax, resolved when
the config is loaded:

- `${output}` — absolute reference from the top of the config (e.g. `aggregate.tetracorder`).
- `${convolve.output}` — dotted path into a subsection.
- `${.key}` — a **relative** reference, resolved within the same subsection.

For example, `name: ${setup.sensor}` in the `convolve` block reuses whatever
`setup.sensor` is set to, so the convolved libraries and the tetracorder integration
stay in sync.

### Overriding config on the CLI

Any config value can be overridden without editing the file, using dotted `--key`
flags after the config path. Values are parsed as Python literals (so lists, numbers,
and booleans work), falling back to a string if parsing fails:

```sh
tetrapy run config.yml \
  --output /output/run2 \
  --data.rfl /data/scene_rfl \
  --tetrun.enabled True \
  --tetrun.args '["band", 10, "gif"]'
```

You can also load and run just one subsection with `-s/--section`.

## Commands

The container entrypoint is `tetrapy`. `run` is the usual entry point; the individual
stages are also exposed as standalone subcommands for debugging or partial runs:

| Command | Description |
|---|---|
| `run` | Execute the full pipeline from a YAML config (the primary interface) |
| `convolve` | Convolve + integrate the spectral libraries for a scene's grid |
| `setup` | Configure a tetracorder run only (`cmd-setup-tetrun`) |
| `tetrun` | Execute a previously-configured run (`cmd.runtet`) |
| `postprocess` | Convert matched tetracorder outputs into COGs and/or delete matched paths |
| `aggregate` | Aggregate tetracorder outputs into L2B mineral/uncertainty products |
| `goc` | Convert group outputs to EMIT L2B NetCDF format |

Use `--help` on any command for full options:

```sh
docker run --rm tetracorder-lite tetrapy --help
docker run --rm tetracorder-lite tetrapy run --help
```

## Volume contract

| Mount point | Purpose |
|---|---|
| `/data` | Input: reflectance file (ENVI format with `.hdr`) — supplies the target grid |
| `/output` | Output: tetracorder results and aggregated L2B products |

The unconvolved master libraries (`splib06b`, `sprlb06b`; ~24 MB total) are **baked
into the image** at `/root/tetracorder/sl1/usgs/library06.conv/`, so a normal run only
needs the scene mounted at `/data`. The `convolve` stage reads its target
wavelength/FWHM grid from the reflectance ENVI header (`${data.rfl}.hdr`), so the
convolved library self-consistently matches the scene.

## Convolved spectral library

Tetracorder matches observed reflectance against a spectral library convolved to the
instrument's channels. When EMIT gets a new calibration (new wavelengths/FWHM), the
library must be regenerated. The `convolve` stage does this in **pure Python** — no
previously-convolved library is needed as a template. It builds the reference
(`splib06b`) and research (`sprlb06b`) libraries by Gaussian-convolving each master
spectrum from its native grid onto the target EMIT grid (with native-FWHM quadrature
correction, matching the USGS Fortran math), writing valid specpr libraries plus ENVI
exports for the aggregator.

When `integrate: True`, the convolved libraries are wired into the tetracorder command
tree (restart, color, disable, datasets, and deleted-channels files) under
`name`, so the subsequent Setup/Tetrun stages use them.

See [`docs/convolved-library-build.md`](docs/convolved-library-build.md) for the full
technical reference on the convolution.

## Development

The Python CLI lives in `tetrapy/`. Managed with [pixi](https://pixi.sh):

```sh
pixi install
pixi run tetrapy --help
```

## Project structure

```
tetracorder-lite/
  Containerfile          # container build (specpr + tetracorder + pixi/tetrapy)
  pyproject.toml         # Python project config (pixi workspace)
  config.yml             # pipeline configuration consumed by `tetrapy run`
  tetrapy/               # Python CLI
    __main__.py          #   click CLI entrypoint (run + per-stage commands)
    config.py            #   YAML config loader, CLI patching, ${...} interpolation
    tetra.py             #   tetracorder setup/run + library convolution & integration
    convolve.py          #   recipe-driven convolved-library builder (pure Python)
    aggregate.py         #   L2B mineral/uncertainty product aggregation
    tetracorder.py       #   expert-system command-file decoder
    conv/                #   specpr / ENVI convolution internals
    templates/           #   tetracorder integration file templates
    data/                #   mineral grouping matrices
  tetracorder/           # vendored tetracorder + specpr source tree
  docs/                  # technical documentation
```

## License

The original work in this repository is licensed under the
[Apache License, Version 2.0](LICENSE). Copyright (c) 2026 California Institute of
Technology ("Caltech"). U.S. Government sponsorship acknowledged.

Third-party components keep their own licenses (details in [NOTICE](NOTICE)):

| Component | Where | License |
|---|---|---|
| Tetracorder, specpr, command files ([PSI-edu/spectroscopy-tetracorder](https://github.com/PSI-edu/spectroscopy-tetracorder)) | `tetracorder/` | [GPL-3.0](tetracorder/COPYING) + PSI conditions in each `license.txt` |
| USGS splib06 / sprlb06 spectral libraries | `tetracorder/sl1/` | from spectroscopy-tetracorder |

The Containerfile also downloads third-party software at build time, including
[DaVinci](https://davinci.asu.edu) (GPL-2.0-or-later) from ASU. That software is not
part of this repository and keeps its own license.
