# Configuration

The whole [pipeline](pipeline.md) runs from a single YAML config. Config is
loaded with [python-box](https://github.com/cdgriffith/Box) (see
[`tetrapy.config`][]) and supports a few conveniences. See `config.yml` in the
repository for a fully-commented example.

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

## Section inheritance

A section can pull in defaults from others with the `^^` key
(`^^: [base, shared]`); its own keys win on conflict.

## `--section`

Load and operate on just one subsection of the file with `-s/--section`.

## Example config

A minimal, representative `config.yml`:

```yaml
output:
  base: /output/test
  tetracorder: ${output.base}/tetracorder
  tetrapy: ${output.base}/aggregate
data:
  rfl: /data/rfl          # reflectance data (not the header)
  rfluncert: /data/rfluncert
tetracorder:
  root: /root/tetracorder
  davinci: True
  version: 6.00a
  sensor: ${sensor.name}
  mode: cube
log:
  level: DEBUG
  file: ${output.tetrapy}/tetrapy.log
  append: False           # False == reset the log file
  config: ${output.tetrapy}/config.yml
export_matrix:
  enabled: False
  file: ${output.tetrapy}/matrix.csv
  groups: [1, 2]
  columns: [id, group, library, record, title, path]
  reference: tetrapy/data/v6.00a6.csv
  sortby: [group, index]
  clean_titles: True
convolve:
  enabled: True
  reflib: ${tetracorder.root}/sl1/usgs/library06.conv/splib06b
  reslib: ${tetracorder.root}/sl1/usgs/library06.conv/sprlb06b
  output:
    reflib: /conv/reflib
    reslib: /conv/reslib
  name: ${sensor.name}
sensor:
  enabled: True
  name: tetrapy
  deleted_channels: "1t4 75t79 99t106 128t148 188t214 218 219t221 226 280t285c"
  enable:
    groups: [1-5, 18, 20-22, 37-38]
    cases: [1-6]
  colors:
    - BASE     23 23 23  base-image.jpg    # base grayscale image
    - COLOR1   38 23 11  color-visRGB.jpg  # visible color channels
    - COLOR2  246 85 18  color-vir.jpg     # false color vis-IR
  reflib: ${convolve.output.reflib}
  reslib: ${convolve.output.reslib}
setup:
  enabled: True
  geology: False
  args: ["1", "-T", "-20", "80", "C", "-P", ".5", "1.5", "bar"]
tetrun:
  enabled: True
  args: ["band", "20", "gif"]
aggregate:
  enabled: True
  tetracorder: ${output.tetracorder}
  output: ${output.tetrapy}
  reflib: ${convolve.output.reflib}
  reslib: ${convolve.output.reslib}
  out_min: ${output.tetrapy}/agg.nc          # supports .nc or .tif
  out_minuncert: ${output.tetrapy}/agg-uncert.nc
  reference: tetrapy/data/v6.00a6.csv
```
