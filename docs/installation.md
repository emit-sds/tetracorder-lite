# Installation

## Use the container (recommended)

The container image ships Tetracorder, specpr, DaVinci, the spectral libraries
and `tetrapy`, for both linux/amd64 and linux/arm64. Build it from the
repository root:

```bash
docker build -f Containerfile -t tetracorder-lite .
```

and run the pipeline with your scene mounted at `/data`:

```bash
docker run --rm -v /path/to/scenes:/data -v tetra-out:/output \
  tetracorder-lite \
  tetrapy run config.yml \
    --data.rfl       /data/<scene>_rfl \
    --data.rfluncert /data/<scene>_uncert \
    --data.glt       /data/<scene>_glt
```

See [Running the container](running-the-container.md) for
Podman, Windows, the volume contract, and why `/output` should be a named
volume on macOS and Windows.

## Install `tetrapy` locally

For development, `tetrapy` can be installed outside the container. It requires
Python ≥ 3.10 (the project targets 3.12), and the stages that call Tetracorder
need a working Tetracorder installation on disk.

Using [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

This installs the `tetrapy` CLI entry point (see [`tetrapy.__main__`][]).

!!! note "Tetracorder installation"
    A working Tetracorder installation (command tree + spectral libraries) is
    expected on disk — the pipeline shells out to its scripts and reads its
    libraries. Paths are configured in the YAML (see the
    [Pipeline](pipeline.md) page); the defaults assume the container layout
    under `/root/tetracorder`, `/data`, and `/output`.

## Documentation dependencies

To build these docs locally, install the optional `docs` extra:

```bash
uv sync --extra docs
```

This pulls in `mkdocs`, `mkdocs-material`, `mkapi`, and `mike`. See the
[Documentation](developers/documentation.md) developer guide for how to build
and serve the site.

## Running the tests

```bash
uv run --group dev pytest
```

## Verify the install

```bash
tetrapy --help
```

You should see the top-level command group and its subcommands
(`run`, `export-matrix`, `convolve`, `sensor`, `setup`, `tetrun`,
`postprocess`, `aggregate`, `preview`).
