# Contributing

Thanks for your interest in improving tetracorder-lite and `tetrapy`. This page covers the basics for
getting a development environment set up and the conventions the project
follows.

## Development setup

Clone the repository and sync the environment with [uv](https://docs.astral.sh/uv/),
including the docs extra so you can build the site locally:

```bash
git clone https://github.com/emit-sds/tetracorder-lite
cd tetracorder-lite
uv sync --all-extras
```

## Project layout

```
tetrapy/
├── __main__.py       # Click CLI (tetrapy run, and per-stage subcommands)
├── __init__.py       # app init: config load + logging setup
├── config.py         # YAML load, ${...} interpolation, ^^ inheritance, CLI overrides
├── pipeline.py       # maps config keys to each stage's underlying call
├── tetracorder.py    # TetraDecoder: parse the expert-system command files
├── sensor.py         # write per-sensor tetracorder integration files
├── tetra.py          # setup/exec Tetracorder + library convolution drivers
├── postprocess.py    # COG conversion (optionally orthorectified) + run-directory pruning
├── aggregate.py      # aggregate group outputs into L2B products + uncertainty
├── utils.py          # logging/timing helpers
├── conv/             # pure-Python specpr Gaussian convolution
│   ├── library.py    #   build a convolved specpr library from a master
│   ├── convolve.py   #   the Convolver
│   └── specpr.py     #   specpr file reader/writer
└── data/             # reference material matrices (v6.00a6.csv)
```

The rest of the repository holds the `Containerfile`, the default `config.yml`,
the `pytest` suite under `tests/`, the vendored Tetracorder and DaVinci source
trees, and these docs under `docs/`. See the
[README](https://github.com/emit-sds/tetracorder-lite#project-structure) for
the full layout.

## Conventions

- **Pipeline stages** live in [`tetrapy.pipeline`][]. Each function takes the
  loaded config (a `box.Box`) and dispatches to the module that does the work.
  When adding a stage, gate it behind a `{stage}.enabled` config flag and add it
  to the stage order in `run`.
- **CLI commands** in [`tetrapy.__main__`][] reuse the pipeline function
  docstrings as their `--help` text, so keep those docstrings user-facing.
- **Docstrings** are numpy-style and drive the auto-generated API reference. See
  the [Documentation](documentation.md) guide.

## Submitting changes

1. Create a branch off `main`.
2. Make your change, keeping docstrings and docs up to date.
3. Run the tests with `uv run --group dev pytest`.
4. Build the docs with `uv run mkdocs build --strict` to confirm every page and
   reference still resolves.
5. Open a pull request against
   [`emit-sds/tetracorder-lite`](https://github.com/emit-sds/tetracorder-lite).
