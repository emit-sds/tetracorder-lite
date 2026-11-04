# Installation

`tetrapy` requires Python ≥ 3.10 (the project targets 3.12) and a working
Tetracorder installation on disk.

## Install the package

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

## Verify the install

```bash
tetrapy --help
```

You should see the top-level command group and its subcommands
(`run`, `export_matrix`, `convolve`, `sensor`, `setup`, `tetrun`,
`aggregate`, `preview`).
