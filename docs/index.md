# tetrapy

A containerized, config-driven wrapper around the USGS
[Tetracorder](https://www.usgs.gov/labs/spectroscopy-lab/tetracorder) expert
system for imaging-spectroscopy mineral identification. `tetrapy` drives the
full pipeline — from convolving spectral libraries onto a scene's grid, through
running Tetracorder, to aggregating its outputs into L2B mineral and
uncertainty products — off a single YAML config.

## What it does

Tetracorder identifies surface materials by matching continuum-removed
absorption features in a reflectance spectrum against a reference library.
Running it against a new sensor or scene normally means hand-editing a tree of
command files, convolving spectral libraries to the instrument's wavelength
grid, and post-processing a directory of per-material rasters. `tetrapy`
automates that end to end:

- **Pure-Python spectral convolution** ([`tetrapy.conv`][]) reimplements USGS
  specpr function 17 (Gaussian high-to-low resolution convolution). Given an
  unconvolved master library and a scene's ENVI header, it builds a complete
  convolved specpr library — no convolution recipe required, since each master
  spectrum carries its own wavelength/FWHM grid.
- **Expert-system decoding** ([`tetrapy.tetracorder`][]) parses the Tetracorder
  `cmd.lib.setup.*` files into structured per-material records (library, record,
  features, constraints) and exports a material matrix CSV.
- **Sensor integration** ([`tetrapy.sensor`][]) writes the per-sensor files the
  command tree looks up by name (restart, deleted-channels, enable/disable,
  color-channels) so a run uses the freshly convolved library.
- **Run orchestration** ([`tetrapy.tetra`][]) drives the vendored
  `cmd-setup-tetrun` / `cmd.runtet` scripts.
- **L2B aggregation** ([`tetrapy.aggregate`][]) composites the group 1 / group 2
  material rasters into band-depth and mineral-id stacks, with per-pixel
  band-depth uncertainty (Clark, 2003), written as NetCDF and/or GeoTIFF.

## Where to go next

<div class="grid cards" markdown>

- :material-download: **[Installation](installation.md)**

    Install `tetrapy` and wire it up to a Tetracorder installation.

- :material-pipe: **[Pipeline](pipeline.md)**

    How the stages fit together, and how to configure and run them.

- :material-code-braces: **[Reference](api/tetrapy/)**

    Auto-generated API documentation for every module.

- :material-account-group: **[Developers](developers/contributing.md)**

    Contributing and documentation guidelines.

</div>

## Output products

`aggregate` writes a mineral product and an uncertainty product over the
`downtrack`/`crosstrack` dimensions (extension decides format — `.nc` for
NetCDF, `.tif` for GeoTIFF). See
[Output products](pipeline.md#output-products) for the variables each carries.

## Notes

- The default config paths (`/root/tetracorder`, `/data`, `/output`) reflect the
  intended containerized deployment; adjust them for a local Tetracorder
  install.
- Logs are written both to the console (via
  [rich](https://github.com/Textualize/rich)) and, when `log.file` is set, to a
  file. The resolved config is exported to `log.config` for reproducibility.
