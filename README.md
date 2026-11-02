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
sets up the `tetrapy` Python environment via [uv](https://docs.astral.sh/uv/).

## The pipeline

`tetrapy run <config.yml>` executes an ordered pipeline. Each stage has an `enabled`
flag in the config, so you can run any subset:

| Stage | Config key | What it does |
|---|---|---|
| Export matrix | `export_matrix` | Decode the tetracorder expert system and export its material matrix to CSV |
| Convolve | `convolve` | Convolve the reference + research master libraries onto the scene's instrument grid |
| Sensor | `sensor` | Wire the convolved libraries into the tetracorder command tree (restart, deleted-channels, enable/disable, datasets, and color files) |
| Setup | `setup` | Configure a tetracorder run (`cmd-setup-tetrun`) |
| Tetrun | `tetrun` | Execute the configured run (`cmd.runtet`), logging to `{output.tetracorder}/tetrun.log` |
| Postprocess | `postprocess` | Convert matched tetracorder outputs into COGs and/or delete matched paths |
| Aggregate | `aggregate` | Aggregate tetracorder outputs into L2B mineral/uncertainty products |

Setup removes `output.tetracorder` first if it already exists, since
`cmd-setup-tetrun` requires it to be absent. When `log.config` is set, the resolved
config is written there for provenance.

## Configuration

The config is a nested YAML file. Top-level keys hold shared values (`output`,
`data`, `tetracorder`, `log`); the remaining keys are the pipeline stages, each gated
by its own `enabled` flag. Paths refer to locations **inside the container**. The
shipped [`config.yml`](config.yml) is:

```yaml
output:
  base:        /output/test
  tetracorder: ${output.base}/tetracorder   # Tetracorder run directory (removed by setup)
  tetrapy:     ${output.base}/aggregate     # tetrapy products: logs, COGs, L2B
data:                             # Data, not header files
  rfl:       /data/rfl            # Reflectance; its .hdr supplies the target grid
  rfluncert: /data/rfluncert      # Reflectance uncertainty
  glt:       /data/glt            # EMIT L1B GLT; when set, COGs are orthorectified onto its map grid
tetracorder:
  root:    /root/tetracorder
  davinci: True
  version: 6.00a
  sensor:  ${sensor.name}
  mode:    cube                   # "cube" or "singlespectrum"

log:
  level:  DEBUG
  file:   ${output.tetrapy}/tetrapy.log
  append: False                   # False == reset the log file
  config: ${output.tetrapy}/config.yml   # Export the resolved config

export_matrix:
  enabled:      False
  file:         ${output.tetrapy}/matrix.csv
  groups:       [1, 2]
  columns:      [id, group, library, record, title, path]
  reference:    tetrapy/data/v6.00a6.csv
  sortby:       [group, index]
  clean_titles: True

convolve:
  enabled: True
  reflib:  ${tetracorder.root}/sl1/usgs/library06.conv/splib06b   # unconvolved reference master
  reslib:  ${tetracorder.root}/sl1/usgs/library06.conv/sprlb06b   # unconvolved research master
  output:
    reflib: /conv/reflib
    reslib: /conv/reslib
  name:    ${sensor.name}

sensor:
  enabled: True
  name:    tetrapy
  deleted_channels:               # See "Deleted channels" below
    units: um
    wavelengths:
      - [0.38, 0.405]             # detector edge
      - [0.93, 0.963]             # 0.94 um water band
      - [1.11, 1.164]             # 1.13 um water band
      - [1.327, 1.477]            # 1.4 um water band
      - [1.770, 1.968]            # 1.9 um water band
      - [2.455, 2.50]             # detector edge
    channels: "218 219t221 226"   # EMIT-specific isolated channels near 2.0 um
  enable:
    groups: [1-5, 18, 20-22, 37-38]
    cases:  [1-6]
  colors:
    - BASE     23 23 23  base-image.jpg    # base grayscale image
    - COLOR1   38 23 11  color-visRGB.jpg  # visible color channels
    - COLOR2  246 85 18  color-vir.jpg     # false color vis-IR
  reflib: ${convolve.output.reflib}
  reslib: ${convolve.output.reslib}

setup:
  enabled: True
  geology: False
  args:    ["1", "-T", "-20", "80", "C", "-P", ".5", "1.5", "bar"]
  # cores: 8                      # Optional; defaults to os.cpu_count()

tetrun:
  enabled: True
  args:    ["band", "20", "gif"]

postprocess:
  enabled:     True
  tetracorder: ${output.tetracorder}  # Glob root for both cogs and remove
  cogs:                               # Convert matched rasters to COGs (omit to skip)
    output:        ${output.tetrapy}/cogs/   # Mirrored destination root
    skip_existing: False                     # False == overwrite existing COGs
    glt:           ${data.glt}               # Omit for raw (non-orthorectified) COGs
    glob:                                    # Rasters to convert (relative to tetracorder)
      - "results.masses/*.png"
  remove:                             # Paths (files/dirs) to delete (omit to skip)
    - "results.group*"
    - "results.dual*"
    - "results.case*"
    - "color.results+labels"
    - "color.results-envi"

aggregate:
  enabled:       True
  tetracorder:   ${output.tetracorder}
  output:        ${output.tetrapy}
  reflib:        ${convolve.output.reflib}
  reslib:        ${convolve.output.reslib}
  out_min:       ${output.tetrapy}/agg.nc         # .nc (NetCDF) or .tif (GeoTIFF)
  out_minuncert: ${output.tetrapy}/agg-uncert.nc  # .nc (NetCDF) or .tif (GeoTIFF)
  reference:     tetrapy/data/v6.00a6.csv
```

Other `postprocess.cogs.glob` patterns that are commonly useful are
`"group.*/*.depth.gz"` and `"group.*/*.fit.gz"`. The aggregate uncertainty product
needs `data.rfl`, `data.rfluncert`, and both convolved libraries.

### Interpolation (`${...}`)

Values may reference other parts of the config with `${...}` syntax, resolved when
the config is loaded:

- `${output.tetracorder}` — absolute dotted reference from the top of the config.
- `${.key}` — a **relative** reference, resolved within the same subsection.

For example, `tetracorder.sensor` and `convolve.name` both reference `${sensor.name}`,
so the convolved libraries, the tetracorder integration, and the setup run all use the
same sensor name.

### Overriding config on the CLI

Any config value can be overridden without editing the file, using dotted `--key`
flags after the config path. Values are parsed as Python literals (so lists, numbers,
and booleans work), falling back to a string if parsing fails:

```sh
tetrapy run config.yml \
  --output.base /output/run2 \
  --data.rfl /data/scene_rfl \
  --tetrun.enabled True \
  --tetrun.args '["band", 10, "gif"]'
```

You can also load and run just one subsection with `-s/--section`. To check the
final, interpolated config without running anything, use `tetrapy preview`:

```sh
tetrapy preview config.yml --output.base /output/run2
```

### Deleted channels

`sensor.deleted_channels` lists the channels Tetracorder removes before fitting:
atmospheric water bands and detector edges. It can be written in two ways.

**Wavelength ranges (the default).** The `sensor` stage turns these into channel
numbers using the scene's own wavelength grid from `${data.rfl}.hdr`, so the same
config works on any sensor or calibration:

```yaml
sensor:
  deleted_channels:
    units: um                   # um (default) | nm
    wavelengths:                # inclusive [min, max], matched against band centres
      - [0.38, 0.405]
      - [1.327, 1.477]          # 1.4 um water band
      - [1.770, 1.968]          # 1.9 um water band
    channels: "218 219t221 226" # optional 1-based channel numbers, combined with the ranges
```

A channel is deleted when its **centre** wavelength falls inside a range, endpoints
included. Leave some margin around band centres: on EMIT, a lower edge of `1.774`
misses channel 188 (centre 1.7740 µm), but `1.770` catches it.

**Channel numbers.** A plain string uses Tetracorder's own syntax (`NtM` ranges,
single numbers, optional trailing `c`) and is used as written. It is only correct on
the grid it was written for:

```yaml
sensor:
  deleted_channels: "1t4 75t79 99t106 128t148 188t214 218 219t221 226 280t285c"
```

Both forms are checked so that every channel falls within `[1, nchans]`. Ranges that
match no channels log a warning. Values that don't fit `units` raise an error, as do
wavelength ranges against a header with no wavelength grid. The resolved list is
logged and written to `DELETED.channels/delete_{sensor.name}` in the tetracorder
command tree.

For a **non-EMIT sensor**, drop the EMIT-specific `channels` and give only the
physical bands. These ranges are illustrative, so tune them for your instrument:

```yaml
sensor:
  name: aviris3
  deleted_channels:
    units: nm
    wavelengths:
      - [1340, 1460]
      - [1790, 1960]
      - [2450, 2520]
```

You can also override just the ranges on the CLI:

```sh
tetrapy run config.yml \
  --sensor.deleted_channels.wavelengths '[[1.327, 1.477], [1.770, 1.968]]'
```

## Commands

The container entrypoint is `tetrapy`. `run` is the usual entry point; the individual
stages are also exposed as standalone subcommands for debugging or partial runs:

| Command | Description |
|---|---|
| `run` | Execute the full pipeline from a YAML config (the primary interface) |
| `export-matrix` | Decode the expert system and export its material matrix to CSV |
| `convolve` | Convolve the spectral libraries onto a scene's grid |
| `sensor` | Wire the convolved libraries into the tetracorder command tree |
| `setup` | Configure a tetracorder run only (`cmd-setup-tetrun`) |
| `tetrun` | Execute a previously-configured run (`cmd.runtet`) |
| `postprocess` | Convert matched tetracorder outputs into COGs and/or delete matched paths |
| `aggregate` | Aggregate tetracorder outputs into L2B mineral/uncertainty products |
| `preview` | Print the final, interpolated config without running anything |

Every command takes the same `config` argument, `-s/--section` option, and dotted
`--key value` overrides as `run`.

Use `--help` on any command for full options:

```sh
docker run --rm tetracorder-lite tetrapy --help
docker run --rm tetracorder-lite tetrapy run --help
```

## Volume contract

| Mount point | Purpose |
|---|---|
| `/data` | Input: reflectance + uncertainty (ENVI format with `.hdr`; the reflectance header supplies the target grid) and optional GLT |
| `/output` | Output: tetracorder results, COGs, and aggregated L2B products |
| `/conv` | Optional: convolved libraries (written inside the container unless mounted) |

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
correction, matching the USGS Fortran math), writing valid specpr libraries that the
aggregator also reads directly.

The `sensor` stage then wires the convolved libraries into the tetracorder command
tree (restart, deleted-channels, enable/disable, datasets, and color files) under
`sensor.name`, so the subsequent Setup/Tetrun stages use them.

See [`docs/convolved-library-build.md`](docs/convolved-library-build.md) for the full
technical reference on the convolution.

## Development

The Python CLI lives in `tetrapy/`. Managed with [uv](https://docs.astral.sh/uv/):

```sh
uv sync
uv run tetrapy --help
```

Run the tests with:

```sh
uv run --group dev pytest
```

## Project structure

```
tetracorder-lite/
  Containerfile          # container build (specpr + tetracorder + DaVinci + uv/tetrapy)
  pyproject.toml         # Python project config
  config.yml             # pipeline configuration consumed by `tetrapy run`
  tetrapy/               # Python CLI
    __init__.py          #   config loading + logging setup
    __main__.py          #   click CLI entrypoint (run + per-stage commands)
    pipeline.py          #   pipeline stages; maps config keys onto the calls below
    config.py            #   YAML config loader, CLI patching, ${...} interpolation
    tetra.py             #   tetracorder setup/run + library convolution
    sensor.py            #   tetracorder command-tree integration, deleted channels
    postprocess.py       #   COG conversion (optionally orthorectified) + output pruning
    aggregate.py         #   L2B mineral/uncertainty product aggregation
    tetracorder.py       #   expert-system command-file decoder
    utils.py             #   shared helpers
    conv/                #   specpr I/O + Gaussian convolution internals
    data/                #   mineral grouping matrices
  tests/                 # pytest suite
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
