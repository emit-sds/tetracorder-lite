# Contributing

Thanks for your interest in improving `tetrapy`. This page covers the basics for
getting a development environment set up and the conventions the project
follows.

## Development setup

Clone the repository and sync the environment with [uv](https://docs.astral.sh/uv/),
including the docs extra so you can build the site locally:

```bash
git clone https://github.com/jammont/tetrapy
cd tetrapy
uv sync --extra docs
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
├── aggregate.py      # aggregate group outputs into L2B products + uncertainty
├── utils.py          # logging/timing helpers
├── conv/             # pure-Python specpr Gaussian convolution
│   ├── library.py    #   build a convolved specpr library from a master
│   ├── convolve.py   #   the Convolver
│   └── specpr.py     #   specpr file reader/writer
├── configs/          # example configs (aviris, test)
└── data/             # reference material matrices (v6.00a6.csv)
```

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
3. Build the docs locally to confirm the reference still renders.
4. Open a pull request against
   [`jammont/tetrapy`](https://github.com/jammont/tetrapy/).
