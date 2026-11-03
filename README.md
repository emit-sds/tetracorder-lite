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

## Try it in a codespace

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/emit-sds/tetracorder-lite?quickstart=1)

A guided walkthrough: run Tetracorder over a 300x150 window of a real EMIT L2A
scene, one step at a time, and see the mineral maps at the end. No install, no
configuration; about ten minutes of which nine are the run itself.

The badge above opens a GitHub codespace of the repo. The terminal banner tells you
how to start the demo (`.devcontainer/get-started.sh`), which then walks you
through tetracorder-lite one step at a time. See
[`.devcontainer/README.md`](.devcontainer/README.md) for specific details of how it all works.

## Docker or Podman

Either works. Podman implements the same command-line interface, so every
example below runs unchanged under `podman` — substitute the command name and
nothing else. The only additions Podman ever needs are volume suffixes on
SELinux systems, covered below.

**Install** — follow the official instructions, they change more often than this
file does:

| | Docker | Podman |
|---|---|---|
| Windows | [WSL containers](https://learn.microsoft.com/windows/wsl/wsl-container) (`wslc`, recommended; see below) or [Docker Desktop](https://docs.docker.com/desktop/install/windows-install/) | [Podman Desktop](https://podman-desktop.io/docs/installation/windows-install) |
| macOS | [Docker Desktop](https://docs.docker.com/desktop/install/mac-install/) | [Podman Desktop](https://podman-desktop.io/docs/installation/macos-install) |
| Linux | [Docker Engine](https://docs.docker.com/engine/install/) | [Podman](https://podman.io/docs/installation#installing-on-linux) |

### Windows

Every option on Windows runs Linux containers in a WSL 2 virtual machine.

**Recommended: WSL containers (`wslc`).** Since September 2026, WSL includes its
own container engine, so there is nothing else to install and no Docker Desktop
licence to consider. You need WSL 2.9.3 or later. From PowerShell:

```powershell
wsl --install      # first time only, then reboot
wsl --update
wslc version
```

Run the examples in this README from PowerShell, with `wslc` in place of `docker`.

For performance, write `/output` to a named volume rather than a Windows folder (see
[where `/output` lives](#on-macos-and-windows-where-output-lives-changes-the-runtime)):

```powershell
wslc volume create --driver vhd -o SizeBytes=20000000000 tetra-out
wslc run --rm -v C:\path\to\scenes:/data -v tetra-out:/output `
  tetracorder-lite tetrapy run config.yml `
    --data.rfl /data/<scene>_rfl --data.rfluncert /data/<scene>_uncert
# copy the results out in one pass
wslc run --rm -v tetra-out:/output -v C:\path\to\results:/host `
  tetracorder-lite cp -a /output/. /host/
```

**Alternatives: Docker Desktop or Podman Desktop.** Install either one, and turn
on Docker Desktop's **Settings → Resources → WSL integration** for your
distribution. Then run `docker` or `podman` from inside the WSL shell, and keep
scenes and output under your WSL home (`/home/you/...`), not `/mnt/c/...`. You can
still reach those files from Explorer at `\\wsl$\Ubuntu\home\you`.

Details: [WSL containers](https://learn.microsoft.com/windows/wsl/wsl-container) ·
[WSL install](https://learn.microsoft.com/windows/wsl/install) ·
[Docker Desktop WSL 2 backend](https://docs.docker.com/desktop/wsl/) ·
[Podman on WSL](https://podman-desktop.io/docs/installation/windows-install)

### Architecture

Tetracorder-lite images are provided for both **linux/amd64 and linux/arm64**, so modern platforms should pull the correct image. If you need a specific architecture, for instance to compare results under
emulation, ask for it as usual:

```
--platform=linux/amd64
```

### If you are using Podman

Nothing in the examples changes — `--rm`, `-v`, `-e` and the rest mean the same
thing to both. Two things are worth knowing anyway:

* **SELinux** (Fedora, RHEL, CentOS): add `:z` to bind mounts, as in
  `-v /path/to/input:/data:z`. Without it the container cannot read the mount.
  This is the one flag Docker has no equivalent for.
* **Rootless**: files written to `/output` come back owned by you, not by root,
  which is usually what you want.

## Quick start

Most people run the whole pipeline in one container call and never install
`tetrapy` themselves. Put the scene's ENVI files in one directory and run:

```sh
docker run --rm \
  -v /path/to/scenes:/data \
  -v tetra-out:/output \
  tetracorder-lite \
  tetrapy run config.yml \
    --data.rfl       /data/<scene>_rfl \
    --data.rfluncert /data/<scene>_uncert \
    --data.glt       /data/<scene>_glt
```

This convolves the spectral library onto the scene's wavelength grid, runs
Tetracorder, writes COGs, and aggregates the result into L2B mineral products under
`/output/test/`. Point `--data.*` at the data files, not the `.hdr`s. The examples
use `tetracorder-lite` as the image name, which is the tag
[Building the container](#building-the-container) produces. If your image has a
different name, use that instead.

`tetra-out` is a named volume, which is the fast choice on macOS and Windows. Copy
the results out when the run finishes. See
[where `/output` lives](#on-macos-and-windows-where-output-lives-changes-the-runtime).
On Linux you can bind-mount a host directory, for example `-v /path/to/output:/output`.

## Running the container

### How a container call is put together

Every call has the same two halves. Everything up to and including the image name
is the container method: which engine, which mounts, which image. Everything after
the image name is the command that runs inside the container:

```
docker run --rm -v …:/data -v …:/output IMAGE  tetrapy <command> config.yml [--key value …]
└───────────── container method ────────────┘  └───────── runs inside the container ──────┘
```

| Part | What it is |
|---|---|
| `docker run --rm` | Engine. `podman run --rm` works the same way (see [Docker or Podman](#docker-or-podman)) |
| `-v …:/data` | Your input scenes. Read-only access is enough |
| `-v …:/output` | Where results are written |
| `IMAGE` | `tetracorder-lite` in these examples; substitute your image's name |
| `tetrapy <command>` | The command to run. The image's default command is bare `tetrapy`, and anything you put after the image name replaces it, so `tetrapy` must be typed out |
| `config.yml` | The default config baked into the image (at `/root/config.yml`, the working directory) |
| `--key value` | Overrides for any config value (see below) |

**The rest of this README shows commands in their short form**, such as
`tetrapy run config.yml …` or `tetrapy aggregate config.yml`. Run them by putting
your container method in front, exactly as in the Quick start. Mounts and engine
flags go before the image name. Config overrides go after `config.yml`.

### Common options

Add these after `config.yml`. Quote any value that contains spaces, so your shell
passes it as a single argument.

| Option | Effect |
|---|---|
| `--output.base /output/<run>` | Writes this run under its own directory. Tetracorder's output directory is wiped at the start of each run, so give each run its own `base` if you want to keep earlier results |
| `--data.glt ""` | No GLT. COGs are written in raw instrument geometry instead of being orthorectified |
| `--sensor.deleted_channels.wavelengths "[[…], …]"` | Wavelength ranges Tetracorder ignores (water bands, detector edges). They are matched against the scene's own grid; see the non-EMIT example below |
| `--<stage>.enabled False` | Skips a pipeline stage, such as `--postprocess.enabled False` (see [The pipeline](#the-pipeline)) |

To check the resolved config without running anything, replace `run` with `preview`:

```sh
docker run --rm tetracorder-lite \
  tetrapy preview config.yml --output.base /output/run2
```

### Example: a non-EMIT sensor

Tetracorder ignores some wavelengths when it fits: the atmospheric water bands and
the detector edges, where the reflectance is unreliable. These are set in
`sensor.deleted_channels` as wavelength ranges, and tetrapy matches them against
the band centres in the scene's own `.hdr`, so the same ranges work on any sensor.

The default config also lists three EMIT-specific channels by number. For another
sensor, set wavelength ranges that suit the instrument and drop those channels
with `--sensor.deleted_channels.channels None`:

```sh
docker run --rm \
  -v /path/to/scenes:/data \
  -v tetra-out:/output \
  tetracorder-lite \
  tetrapy run config.yml \
    --data.rfl       /data/<scene>_rfl \
    --data.rfluncert /data/<scene>_uncert \
    --data.glt       "" \
    --output.base    /output/aviris-ng \
    --sensor.deleted_channels.units       nm \
    --sensor.deleted_channels.wavelengths "[[365, 400], [1340, 1460], [1790, 1960], [2450, 2520]]" \
    --sensor.deleted_channels.channels    None
```

Ranges are inclusive and in `units` (`um` by default, or `nm`). The ranges above
are illustrative, so tune them for your instrument. The `sensor` stage logs the
channels it resolved, and [Deleted channels](#deleted-channels) covers the full
syntax.

### Using your own config

For repeated runs of the same kind, for example one sensor, copy
[`config.yml`](config.yml), edit it, and mount it into the container:

```sh
docker run --rm \
  -v /path/to/scenes:/data \
  -v tetra-out:/output \
  -v "$PWD/config.aviris.yml:/config/config.aviris.yml:ro" \
  tetracorder-lite \
  tetrapy run /config/config.aviris.yml --data.rfl /data/<scene>_rfl
```

Overrides still apply on top of a mounted config.

## Building the container

```sh
docker build -f Containerfile -t tetracorder-lite .
```

The image compiles specpr + Tetracorder (Fortran/ratfor) and DaVinci (C), then
sets up the `tetrapy` Python environment with uv. DaVinci builds from the
vendored source in [`vendor/davinci`](vendor/davinci/VENDOR.md) in a separate
stage, so the compilers and source do not end up in the finished image.

The build is native on both amd64 and arm64, so nothing here is emulated. To
build for the architecture you are not on, which *is* emulated and much slower:

```sh
docker buildx build --platform=linux/arm64 -f Containerfile -t tetracorder-lite .
```

## The pipeline

`tetrapy run <config.yml>` runs these stages in order. Each stage has an `enabled`
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
the config is loaded (after CLI overrides are applied):

- `${output.base}` — absolute dotted path from the top of the config.
- `${.key}` — a **relative** reference, resolved within the same subsection.

This is why most overrides only need one key. `--output.base /output/run2` moves
every output path, because `output.tetracorder`, `output.tetrapy`, the log and the
COG directory are all derived from it. Likewise `sensor.name` feeds `convolve.name`
and `tetracorder.sensor`, so the convolved libraries, the command-tree files and the
run all use the same sensor key.

### Overriding config on the CLI

Any config value can be overridden without editing the file, using dotted `--key`
flags after the config path. Values are parsed as Python literals (so lists, numbers,
and booleans work), falling back to a string if parsing fails. Shown in short form;
prefix your [container method](#how-a-container-call-is-put-together):

```sh
tetrapy run config.yml \
  --output.base /output/run2 \
  --data.rfl /data/scene_rfl \
  --tetrun.enabled True \
  --tetrun.args '["band", 10, "gif"]'
```

Override the leaf key, not the section it is in. `--output /output/run2`
replaces the whole `output:` block with a string, and the config then fails to load
with `Interpolation reference '${output.tetrapy}' not found`.

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

The image's default command is `tetrapy`. As a default command rather than an
entrypoint, it is replaced by whatever follows the image name, which is why every
call spells out `tetrapy <command>`. `run` is the usual command. The individual
stages are also exposed as standalone subcommands for debugging or partial runs.
Each one runs with the same [container method](#how-a-container-call-is-put-together)
as `run`:

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

### On macOS and Windows, where `/output` lives changes the runtime

A full scene writes **8,516 files**. On Linux that costs nothing — the daemon shares
your kernel and a bind mount is an ordinary path. On macOS and Windows every
container runs inside a Linux VM, and a bind mount of a host directory crosses a
file-sharing layer that charges per filesystem operation. Thousands of small
creates, writes, gzips and renames is the worst possible shape for it.

Measured on an M5 Max under Colima (4 CPU, virtiofs), full EMIT granule
`emit20250327t212148`, 1242x1280x285, everything else held constant:

| `/output` on | total | `tetrun` | CPU |
|---|---|---|---|
| a named volume | **6m 42s** | 5m 58s | 200% |
| a host bind mount | 24m 23s | 23m 31s | 71% |

Same image, same scene, byte-identical `agg.nc` — **3.6x**, purely from where the
output went. The CPU column is the tell: on the volume the run never drops below one
core, on the bind mount it sits under one core 79% of the time with the rest idle,
waiting on the filesystem. Raising the VM's CPU allocation does not help, because
cores were never the constraint.

So on macOS and Windows, write to a volume and copy out at the end:

```sh
docker volume create tetra-out
docker run --rm -v /path/to/input:/data -v tetra-out:/output \
  tetracorder-lite tetrapy run config.yml \
    --data.rfl /data/<scene>_rfl --data.rfluncert /data/<scene>_uncert
# one bulk pass, ~11 s for 1.8 GB -- the cost is per-operation, not per-byte
docker run --rm -v tetra-out:/output -v "$PWD/results:/host" \
  tetracorder-lite cp -a /output/. /host/
```

Input can stay bind-mounted: it is two large sequential reads, which this layer
handles fine.

On **Windows**, [the Windows section](#windows) shows the same pattern with
`wslc volume create`. Under Docker Desktop or Podman, keeping data in your WSL home
rather than `/mnt/c/...` avoids the much more expensive crossing into NTFS, but a
named volume is still the safer choice.
On **Linux**, ignore all of this and bind-mount whatever you like.

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
uv sync --all-extras   # --all-extras adds the codespace demo's plotting deps
uv run tetrapy --help
```

Run the tests with:

```sh
uv run --group dev pytest
```

Running `tetrapy` outside the container is for development. The pipeline stages that
call Tetracorder need the binaries and command tree that only the image provides.

The build context is filtered by two files that must be changed together:
`.dockerignore`, which only Docker reads, and `.containerignore`, which Podman
prefers. If either drifts, that engine ships the whole working tree — including
any scenes downloaded under `in/` — into the context and bakes it into the image.

## Project structure

```
tetracorder-lite/
  Containerfile          # container build (DaVinci + specpr + tetracorder + uv/tetrapy)
  .dockerignore          # build context filter -- docker reads this one
  .containerignore       #   the same list for podman; keep the two in step
  pyproject.toml         # Python project config (uv; lockfile in uv.lock)
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
| [DaVinci](https://davinci.asu.edu) (ASU Mars Space Flight Facility) | `vendor/davinci/src/` ([VENDOR.md](vendor/davinci/VENDOR.md)) | [GPL-2.0-or-later](vendor/davinci/src/LICENSE) |

DaVinci is vendored as source at upstream revision r19810 and compiled during the
build, rather than installed from ASU's prebuilt `.deb`. Its tree carries a few
components under their own terms -- the Xvic widgets (Caltech, 3-clause BSD),
libcsv and libltdl (LGPL-2.1), and the libtiff, libpng, giflib and libjpeg copies
bundled inside `iomedley/` (all permissive). [NOTICE](NOTICE) lists each with its
license file.

The container image is an aggregate of separate programs, each keeping its own
license. Because the Containerfile copies the repository into the image, the
complete corresponding source for the GPL components travels inside the image
itself -- `/root/vendor/davinci/src` and `/root/tetracorder` -- so GPL-2 section
3(a) and GPL-3 section 6(a) are met without a separate written offer.
