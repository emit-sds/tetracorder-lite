# Pipeline

The whole pipeline runs from a single YAML config. `tetrapy run` executes the
enabled stages in order:

```
export_matrix → convolve → sensor → setup → tetrun → aggregate
```

Each stage is gated by its own `{stage}.enabled` flag in the config, so any
stage can be skipped. The stage functions live in [`tetrapy.pipeline`][], which
maps config keys onto the underlying calls.

## Running the pipeline

```bash
tetrapy run config.yml \
  --data.rfl /data/emit20230728t214153_rfl \
  --data.rfluncert /data/emit20230728t214153_uncert
```

Individual stages are also exposed as subcommands:

```bash
tetrapy export_matrix config.yml   # decode expert system -> material matrix CSV
tetrapy convolve      config.yml   # convolve reference/research libraries to scene grid
tetrapy sensor        config.yml   # wire convolved library into the command tree
tetrapy setup         config.yml   # configure a Tetracorder run (cmd-setup-tetrun)
tetrapy tetrun        config.yml   # execute the run (cmd.runtet)
tetrapy aggregate     config.yml   # aggregate outputs into L2B products
tetrapy preview       config.yml   # print the resolved config without running anything
```

## Stages

Each stage takes the loaded config and dispatches to the module that does the
work. See [`tetrapy.pipeline`][] for the full docstrings.

| Stage | Does | Backed by |
| --- | --- | --- |
| [`export_matrix`](#export_matrix) | Decode the expert system and export a material matrix CSV | [`tetrapy.tetracorder`][] |
| [`convolve`](#convolve) | Gaussian-convolve reference/research libraries to the scene grid | [`tetrapy.conv`][] / [`tetrapy.tetra`][] |
| [`sensor`](#sensor) | Integrate the convolved library into the command tree | [`tetrapy.sensor`][] |
| [`setup`](#setup) | Configure a Tetracorder run (`cmd-setup-tetrun`) | [`tetrapy.tetra`][] |
| [`tetrun`](#tetrun) | Execute the run (`cmd.runtet`) | [`tetrapy.tetra`][] |
| [`aggregate`](#aggregate) | Aggregate outputs into L2B mineral/uncertainty products | [`tetrapy.aggregate`][] |

Every stage carries an `enabled` flag (documented per-stage below); the rest of
its keys are described in each section. Values shared across stages —
`data.rfl`, `data.rfluncert`, `tetracorder.*`, and `output.*` — are documented
under [Shared inputs](#shared-inputs). After all stages complete, output
directory permissions are set to `ugo+rwX,o-w` (group-writable,
world-readable).

### Shared inputs

These keys are not owned by any one stage but are read by several of them.

| Key | Used by | Description |
| --- | --- | --- |
| `data.rfl` | `convolve`, `sensor`, `setup`, `tetrun`, `aggregate` | Scene reflectance raster (the data file, **not** the `.hdr`). Its companion `.hdr` supplies the target wavelength/FWHM grid for convolution, and its band count sets the sensor restart file's channel count. |
| `data.rfluncert` | `aggregate` | Reflectance-uncertainty raster. Required (together with `rfl`) to compute band-depth uncertainty. |
| `tetracorder.root` | `export_matrix`, `sensor`, `setup` | Root of the Tetracorder install (command tree + libraries). |
| `tetracorder.version` | `export_matrix`, `sensor`, `setup` | Tetracorder version, e.g. `6.00a`. Selects the `.cmds` tree and enables v6-specific patches. |
| `tetracorder.sensor` | `setup` | Sensor name passed to `cmd-setup-tetrun`; typically `${sensor.name}`. |
| `tetracorder.mode` | `setup`, `tetrun` | Processing mode: `cube` or `singlespectrum`. |
| `tetracorder.davinci` | `tetrun` | If `False`, DaVinci entries are stripped from `PATH` before the run. |
| `output.tetracorder` | `run`, `setup`, `tetrun`, `aggregate` | Tetracorder run output directory. |
| `output.tetrapy` | `run`, `aggregate`, `log` | tetrapy (L2B) output directory. |

### `export_matrix`

Decode the Tetracorder expert system and export its material matrix to CSV
(one row per mapped material). Backed by
[`tetrapy.tetracorder.TetraDecoder`][].

| Key | Type | Description |
| --- | --- | --- |
| `enabled` | bool | Whether the stage runs. Disabled by default in the example config. |
| `file` | str | Destination path for the exported CSV. |
| `groups` | list[int] | Group numbers to decode and include (e.g. `[1, 2]`). |
| `columns` | list[str] | Record keys to emit as columns, in order — chosen from `id`, `group`, `library`, `record`, `title`, `path`. |
| `reference` | str | Reference matrix CSV. When set, a stable `index` column is added by aligning records to it, keeping material indices consistent across runs. |
| `sortby` | list[str] | Sort key(s) for the output rows (e.g. `[group, index]`). |
| `clean_titles` | bool | Normalize material titles when matching against the reference. |

### `convolve`

Gaussian-convolve the unconvolved reference and research master libraries onto
the scene's wavelength grid (read from `{data.rfl}.hdr`), writing a convolved
specpr library for each. Backed by [`tetrapy.tetra.convolve`][] /
[`tetrapy.conv`][].

| Key | Type | Description |
| --- | --- | --- |
| `enabled` | bool | Whether the stage runs. |
| `reflib` | str | Path to the unconvolved **reference** master library (`splib06b`, specpr format). |
| `reslib` | str | Path to the unconvolved **research** master library (`sprlb06b`, specpr format). |
| `output.reflib` | str | Output path for the convolved reference library. |
| `output.reslib` | str | Output path for the convolved research library. |
| `name` | str | Library/sensor name (typically `${sensor.name}`). |

!!! note
    The convolved libraries are consumed by both the `sensor` stage (wired into
    the command tree) and the `aggregate` stage (reference spectra for
    uncertainty). It raises `FileNotFoundError` if a master library or the
    scene `.hdr` is missing.

### `sensor`

Wire the convolved libraries into the Tetracorder command tree for a named
sensor, by writing the four per-sensor files the tree looks up by name (restart,
deleted-channels, enable/disable, and color-channels). Backed by
[`tetrapy.sensor.build`][].

| Key | Type | Description |
| --- | --- | --- |
| `enabled` | bool | Whether the stage runs. |
| `name` | str | Sensor name; every written file is keyed on it. |
| `deleted_channels` | str | specpr channel-deletion spec, e.g. `"1t4 75t79 ... 226c"`. Written to `DELETED.channels/delete_{name}`. |
| `enable.groups` | list | Analysis groups to enable; everything else is disabled. Accepts ints and inclusive `"a-b"` range strings (e.g. `[1-5, 18, 20-22]`). |
| `enable.cases` | list | Analysis cases to enable (same range syntax), e.g. `[1-6]`. |
| `colors` | list[str] | Lines for the color-channels file (`COLOR.channels/color-{name}`). |
| `reflib` | str | Convolved reference library (typically `${convolve.output.reflib}`), written into the restart file. |
| `reslib` | str | Convolved research library (typically `${convolve.output.reslib}`), written into the restart file. |

!!! note
    The restart file's channel count (`nchans`) is read directly from
    `data.rfl`, so it self-consistently matches the scene being mapped. Missing
    libraries raise `FileNotFoundError`.

### `setup`

Initialize a Tetracorder run via the vendored `cmd-setup-tetrun` script, then
apply post-setup patches (geology flag, CPU count, `cmd.runtet` fixups). Backed
by [`tetrapy.tetra.setup_tetrun`][].

| Key | Type | Description |
| --- | --- | --- |
| `enabled` | bool | Whether the stage runs. |
| `geology` | bool | On v6, enables geology mode; otherwise `nogeology` is used. |
| `cores` | int | CPU cores written to `TETNCPU.txt`. Defaults to `os.cpu_count()` when unset. |
| `args` | list[str] | Extra arguments passed through to `cmd-setup-tetrun`, e.g. `["1", "-T", "-20", "80", "C", "-P", ".5", "1.5", "bar"]`. |

!!! warning
    Any pre-existing `output.tetracorder` directory is removed entirely before
    setup (`cmd-setup-tetrun` requires a fresh directory), so don't point it at
    a location holding data you want to keep.

### `tetrun`

Execute the run prepared by `setup` via the vendored `cmd.runtet` script,
streaming output to a live panel and capturing it to `tetracorder.out` in the
output directory. Backed by [`tetrapy.tetra.exec_tetrun`][].

| Key | Type | Description |
| --- | --- | --- |
| `enabled` | bool | Whether the stage runs. |
| `args` | list[str] | Extra arguments passed through to `cmd.runtet`, e.g. `["band", "20", "gif"]`. |

Mode, reflectance, output directory, and the DaVinci toggle come from the
[shared](#shared-inputs) `tetracorder.mode`, `data.rfl`, `output.tetracorder`,
and `tetracorder.davinci` keys.

### `aggregate`

Composite the group 1 / group 2 material rasters into the L2B mineral and
uncertainty products, in whatever formats the output extensions imply (`.nc`
NetCDF, `.tif` GeoTIFF). Backed by [`tetrapy.aggregate.build`][].

| Key | Type | Description |
| --- | --- | --- |
| `enabled` | bool | Whether the stage runs. |
| `tetracorder` | str | Tetracorder output directory to read group products from (typically `${output.tetracorder}`). |
| `reflib` | str | Convolved reference library, supplying reference spectra for the band-depth uncertainty calculation. |
| `reslib` | str | Convolved research library, likewise used for uncertainty. |
| `out_min` | str | Output path for the **mineral** product; extension selects `.nc` or `.tif`. |
| `out_minuncert` | str | Output path for the **uncertainty** product; extension selects `.nc` or `.tif`. |
| `reference` | str | Reference matrix CSV; when set, the mineral-id band uses each material's stable `index`. |

Band-depth uncertainty is only computed when all of `data.rfl`,
`data.rfluncert`, `reflib`, and `reslib` are available. See
[Output products](#output-products) below for the resulting variables.

## Output products

`aggregate` writes two products over the `downtrack`/`crosstrack` dimensions
(extension decides format — `.nc` for NetCDF, `.tif` for GeoTIFF):

- **Mineral product** (`out_min`): `group_1_band_depth`, `group_1_mineral_id`,
  and the group 2 equivalents.
- **Uncertainty product** (`out_minuncert`): `group_1_band_depth_unc`,
  `group_1_fit`, and the group 2 equivalents.

Mineral IDs are keyed to a stable reference matrix (`tetrapy/data/v6.00a6.csv`)
so material indices stay consistent across runs. A group that identified nothing
(e.g. full cloud, snow, or water) is zero-filled rather than omitted, so both
products always carry all four group variables.

## Configuration

Every stage is driven by a single YAML config, with interpolation, CLI
overrides, and section inheritance. See the [Configuration](configuration.md)
page for the full reference and an example `config.yml`.
