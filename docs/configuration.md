# Configuration

The whole [pipeline](pipeline.md) runs from a single YAML config. Config is
loaded with [python-box](https://github.com/cdgriffith/Box) (see
[`tetrapy.config`][]) and supports a few conveniences. The
[default config](#default-config) is reproduced at the bottom of this page.

## Interpolation

`${...}` references other config values. A leading dot (`${.key}`) is relative
to the current section; otherwise it resolves from the top of the config.
Fully-substituted strings are parsed as Python literals where possible.

```yaml
output:
  base: /output/test
  tetrapy: ${output.base}/aggregate
```

## CLI overrides

Any dotted key can be overridden on the command line. Values are parsed as
Python literals, so lists and numbers work:

```bash
tetrapy run config.yml --tetrun.args '["band", 10, "gif"]' --output.base /output/run2
```

Override the leaf key, not the section it is in. `--output /output/run2`
replaces the whole `output:` block with a string, and the config then fails to
load with `Interpolation reference '${output.tetrapy}' not found`.

To check the final, interpolated config without running anything, use
`preview`:

```bash
tetrapy preview config.yml --output.base /output/run2
```

## Section inheritance

A section can pull in defaults from others with the `^^` key
(`^^: [base, shared]`); its own keys win on conflict.

## `--section`

Load and operate on just one subsection of the file with `-s/--section`.

## Default config

This is the `config.yml` baked into the container image (at `/root/config.yml`,
the working directory). It is included here directly from the repository when
the docs are built, so it always matches the release you are reading.

```yaml
--8<-- "config.yml"
```
