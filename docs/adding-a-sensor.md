# Adding or recalibrating a sensor

This guide covers three related tasks:

- **[Recalibrate an existing sensor](#recalibrate-an-existing-sensor)** — new
  wavelengths/FWHM (and maybe a new recipe) for a sensor that already has config.
- **[Add a brand-new sensor](#add-a-brand-new-sensor)** — create the sensor-keyed
  config, then convolve/bake as in a recalibration.
- **[Tag and version the container](#tag-and-version-the-container)** — how a set of
  checked-in instrument files becomes a versioned image.

The worked example throughout is `emit_c`. For the convolution internals see
[`convolved-library-build.md`](convolved-library-build.md); for build args and the
build-time gates see [`build.md`](build.md).

---

## How sensor config is organized

There is no single "sensor file." A sensor's configuration is a **set** of files spread
across the tetracorder command tree
(`tetracorder/tetracorder.cmds/tetracorder6.00a.cmds/`), tied together by one entry
under `DATASETS/`. When you run the container, `cmd-setup-tetrun` reads
`DATASETS/<sensor>`, follows its `restart=` line to a restart file, and that restart
points specpr at the convolved libraries.

| Piece | Path (under the cmds tree, except libraries) | Per-sensor? | Comes from |
|---|---|---|---|
| DATASET entry | `DATASETS/<sensor>` | yes | Hand-authored (copy `emit_c`) |
| Restart file | `restart_files/r1-<slug>` | yes | Copy template; protection numbers auto-synced by the build |
| Deleted channels | `DELETED.channels/delete_<sensor>` | yes | Hand-authored (expert-curated bad-channel list) |
| Research library | `sl1/usgs/rlib06/r06<slug>` | yes | Baked USGS delivery **or** re-convolved from master |
| Standard library | `sl1/usgs/library06.conv/s06<slug>` | yes | Baked USGS delivery **or** re-convolved from master |
| Convolution recipe | `sl1/usgs/library06.conv/conv.r06<slug>.cmds`, `conv.s06<slug>.cmds` | yes | USGS ("command file") |
| Research master | `sl1/usgs/rlib06/sprlb06b` | **no** — shared | Baked (general USGS library) |
| Standard master | `sl1/usgs/library06.conv/splib06b` | **no** — shared | Baked (general USGS library) |
| Material setup | `cmd.lib.setup.t6.00a5` | **no** — shared | USGS (selects which spectra tetracorder scores) |

### The `<sensor>` vs `<slug>` naming rule

The **DATASET key keeps underscores**, but the **restart and library filenames drop
them**. The slug is the sensor name with `_` removed:

| `<sensor>` | `<slug>` | Files |
|---|---|---|
| `emit_c` | `emitc` | `DATASETS/emit_c`, `DELETED.channels/delete_emit_c`, `restart_files/r1-emitc`, `rlib06/r06emitc`, `library06.conv/s06emitc` |

(The build derives the slug automatically: `slug = sensor.replace("_", "")`.)

### Why grid alignment matters

The convolved libraries must be built onto **the instrument's exact wavelength/FWHM
grid**, and their records must line up with the shared `cmd.lib.setup`. `cmd.lib.setup`
addresses reference spectra by **absolute specpr record number**, so a library built
from a different-vintage recipe — or convolved to the wrong grid — can shift or drop the
records the config expects. When that happens tetracorder exits `0` while silently
producing **zero mineral IDs**. Two build-time gates (`sync-restart` and
`verify-config`) catch this; see [Troubleshooting](#pre-flight-checklist--troubleshooting).

---

## Recalibrate an existing sensor

Use this when EMIT (or another instrument) issues a new calibration for a sensor that
already has config in the tree. There are two paths depending on what the calibration
delivers.

### Normal path: re-convolve in-container (`RECONVOLVE=1`)

A calibration normally delivers new **wavelength and FWHM text files**, and sometimes an
**updated convolution recipe** (`conv.*.cmds`). The container re-convolves the libraries
from the shared masters onto the new grid.

1. **Check in the calibration grid.** Drop the two text files into `epoch-inputs/`,
   named for the epoch:

   ```
   epoch-inputs/emit_wl_<epoch>.txt      # one wavelength per line
   epoch-inputs/emit_fwhm_<epoch>.txt    # one FWHM per line, same order
   ```

   Both are in the units given by the `GRID_UNITS` build arg (default `nanometers`).

2. **Check in a new recipe, if one was delivered.** Replace the sensor's recipes in
   `tetracorder/sl1/usgs/library06.conv/`:

   ```
   conv.r06<slug>.cmds     # research
   conv.s06<slug>.cmds     # standard
   ```

   A changed recipe changes which spectra are convolved and their record order — this is
   exactly the case the record-alignment gate protects against, so let the build check it.

3. **Build with `RECONVOLVE=1`.** Point `WL_FILE`/`FWHM_FILE` at the checked-in grid:

   ```bash
   docker build --platform linux/amd64 -f Containerfile --target epoch \
     --build-arg SENSOR=emit_c \
     --build-arg NCHANS=285 \
     --build-arg EPOCH_TAG=<epoch> \
     --build-arg RECONVOLVE=1 \
     --build-arg WL_FILE=epoch-inputs/emit_wl_<epoch>.txt \
     --build-arg FWHM_FILE=epoch-inputs/emit_fwhm_<epoch>.txt \
     -t emit-tc:emit_c-<epoch>-v01 .
   ```

   During the build:
   - `convolve-epoch` builds `s06emitc` and `r06emitc` from the shared masters
     (`splib06b`, `sprlb06b`) + recipes onto the new grid.
   - `sync-restart` sets the restart's `iprtw`/`iprty` to `-(records - 1)` of the
     freshly built libraries.
   - `verify-config` asserts the channel count, restart protection, and record
     alignment. **If any gate fails, the build fails** — it does not produce a
     silently-broken image.

4. **Verify the grid matches a real scene** (optional but recommended). Confirm the
   built library grid equals the scene you will process:

   ```bash
   .venv/bin/python - <<'PY'
   from tetrapy import convolve
   import numpy as np
   swl, sfwhm = convolve.read_wavelengths_fwhm("in/<scene>_rfl.hdr")
   recs = convolve.load("tetracorder/sl1/usgs/rlib06/r06emitc")
   wl_i, res_i = convolve.find_grid(recs)
   lwl = np.asarray(convolve.read_array(recs, wl_i), float)
   swl = np.asarray(swl, float)
   print("channels:", len(lwl), "vs scene", len(swl))
   print("max wavelength delta (um):", np.abs(lwl - swl).max())
   PY
   ```

   Expect the channel counts to be equal and the max delta well below one channel
   spacing (for emit_c, ~2e-4 µm against ~7 nm spacing).

### Secondary path: USGS delivered finished libraries (`RECONVOLVE=0`)

Occasionally USGS delivers **already-convolved** libraries for the sensor (this is how
the a5 `emit_c` libraries arrived). In that case you do not re-convolve:

1. Check the finished libraries in at their real paths:
   ```
   tetracorder/sl1/usgs/rlib06/r06<slug>
   tetracorder/sl1/usgs/library06.conv/s06<slug>
   ```
2. Build with the default `RECONVOLVE=0` (omit the arg). The WL/FWHM files are then
   **provenance only** — recorded for traceability but not used to convolve.
3. `sync-restart` and `verify-config` still run against the baked libraries, so the same
   alignment guarantees hold.

```bash
docker build --platform linux/amd64 -f Containerfile --target epoch \
  --build-arg SENSOR=emit_c \
  --build-arg NCHANS=285 \
  --build-arg EPOCH_TAG=<epoch> \
  --build-arg WL_FILE=epoch-inputs/emit_wl_<epoch>.txt \
  --build-arg FWHM_FILE=epoch-inputs/emit_fwhm_<epoch>.txt \
  -t emit-tc:emit_c-<epoch>-v01 .
```

---

## Add a brand-new sensor

Adding a sensor is a recalibration **plus** creating the three hand-authored config
files. Pick a `<sensor>` name (keep it lowercase; use `_` if you want a suffix like
`emit_c`) and derive `<slug>` by removing underscores.

### 1. Create the DATASET entry

Copy `emit_c` and edit. The minimal entry:

```
# tetracorder.cmds/tetracorder6.00a.cmds/DATASETS/<sensor>
data=    <SHORTNAME>          # short data label (e.g. EMITc)
restart= r1-<slug>            # MUST match the restart filename below
deletedpoint=  -99999.0       # value flagging deleted/no-data points
threshholdmin= -0.009         # reflectance floor
threshholdmax= 99999.0        # reflectance ceiling
```

`cmd-setup-tetrun` reads these fields by name; `restart=` is what links the sensor to
its restart file. Optional fields (`lib=`, `band=`, `start=`, `c_nots=`) default
sensibly — only add them if this sensor needs a non-default material setup.

### 2. Create the restart file

Copy `restart_files/r1-emitc` to `restart_files/r1-<slug>` and edit these fields to
point at the new sensor's libraries and grid:

| Field | Set to | Notes |
|---|---|---|
| `iwfl=` | `/sl1/usgs/rlib06/r06<slug>` | research library path (in-container) |
| `iyfl=` | `/sl1/usgs/library06.conv/s06<slug>` | standard library path (in-container) |
| `irfl=` | `r1-<slug>` | the restart's own name |
| `iwdgt=` | `r06<slug>` | 8-char device name for the research library |
| `inmy=` | `s06<slug>` | 8-char device name for the standard library |
| `nchans=` | `<NCHANS>` | the instrument's channel count |
| `iprtw=` | (leave as-is) | **auto-set** by `sync-restart` to `-(research records - 1)` |
| `iprty=` | (leave as-is) | **auto-set** by `sync-restart` to `-(standard records - 1)` |

Leave everything else (plot bounds, record pointers, `filtyp` block) at the template
values unless you know the instrument needs different plot ranges. Do **not** hand-edit
`iprtw`/`iprty` — the build derives them from the actual baked libraries, and a stale
hand value causes the silent-zero-IDs failure.

### 3. Create the deleted-channels file

Create `DELETED.channels/delete_<sensor>` listing the bad channels for the new grid. The
first line is the deletion spec using USGS range syntax; lines beginning with `\#` are
comments. Example (from `delete_emit_c`):

```
1t4 75t79 99t106 128t148 188t214 218 219t221 226  280t285c  # <sensor>
```

`NtM` means the inclusive channel range N..M; a trailing `c` on the last token is
allowed; channels are 1-based and must fall within `[1, NCHANS]`. This is
expert-curated per instrument (atmospheric water bands, detector edges, etc.) — do not
copy `emit_c`'s ranges blindly onto a different grid.

### 4. Provide the libraries and recipe

Either check in USGS-delivered finished libraries, or provide the recipe + calibration
grid for `RECONVOLVE=1`, exactly as in
[Recalibrate an existing sensor](#recalibrate-an-existing-sensor). A new sensor almost
always uses the re-convolve path, so you will also add:

```
sl1/usgs/library06.conv/conv.r06<slug>.cmds
sl1/usgs/library06.conv/conv.s06<slug>.cmds
epoch-inputs/<sensor>_wl_<epoch>.txt
epoch-inputs/<sensor>_fwhm_<epoch>.txt
```

### 5. Build

```bash
docker build --platform linux/amd64 -f Containerfile --target epoch \
  --build-arg SENSOR=<sensor> \
  --build-arg NCHANS=<nchans> \
  --build-arg EPOCH_TAG=<epoch> \
  --build-arg RECONVOLVE=1 \
  --build-arg WL_FILE=epoch-inputs/<sensor>_wl_<epoch>.txt \
  --build-arg FWHM_FILE=epoch-inputs/<sensor>_fwhm_<epoch>.txt \
  -t emit-tc:<sensor>-<epoch>-v01 .
```

The gates validate the new config the same way they validate `emit_c`.

---

## Tag and version the container

The image tag is the version record. Use:

```
emit-tc:<sensor>-<epoch>-v<NN>
```

- **`<sensor>`** — the `SENSOR` build arg (e.g. `emit_c`).
- **`<epoch>`** — the calibration identifier, typically the date the WL/FWHM apply to
  (e.g. `20260620`).
- **`v<NN>`** — a monotonic **build revision** for that sensor+epoch, two digits,
  starting at `v01`. Bump it when you rebuild the *same* calibration — for example after
  fixing a recipe or a deleted-channels list. Bump `<epoch>` instead when the
  calibration itself changes.

The tetracorder **engine** version is deliberately **not** in the tag. It is pinned by
the base image and by the git commit the instrument files live in. That is why the
workflow is **check in, then build**:

1. Commit the instrument files (DATASET, restart, deleted-channels, recipe, calibration
   grid, and any finished libraries) to the repo.
2. Build the image from that commit.
3. Tag it `emit-tc:<sensor>-<epoch>-v<NN>`.

The commit is the source of truth; the tag is a human-readable pointer to "the image
built from those files." If you need to know exactly which engine an image used, it is
the tetracorder version at that commit (and in the base image the epoch stage was built
`FROM`).

---

## Pre-flight checklist & troubleshooting

Before building, confirm you have — for `<sensor>` / `<slug>`:

- [ ] `DATASETS/<sensor>` with a `restart= r1-<slug>` line
- [ ] `restart_files/r1-<slug>` pointing at `r06<slug>` / `s06<slug>`, with `nchans=` set
- [ ] `DELETED.channels/delete_<sensor>` with channels inside `[1, NCHANS]`
- [ ] libraries present: either finished `r06<slug>`/`s06<slug>`, or recipe
      `conv.{r,s}06<slug>.cmds` + `epoch-inputs/` WL/FWHM for `RECONVOLVE=1`
- [ ] build args: `SENSOR`, `NCHANS`, `EPOCH_TAG` (and `WL_FILE`/`FWHM_FILE`,
      plus `RECONVOLVE=1` on the re-convolve path)

The two gate failures you may hit — both fail the **build**, not the run, which is the
point (a broken config never ships as a silently-zero-IDs image):

**Protection desync.** specpr stores a per-library "device protection" number in the
restart, equal to `-(records - 1)` where `records = filesize / 1536`. If the restart's
`iprtw`/`iprty` do not match the baked libraries, `verify-config` fails with a message
like:

```
r1-<slug>: iprtw=... but library .../r06<slug> has N records
-> protection must be -(N-1) ...
```

`sync-restart` sets these automatically during the build; this only fails if the sync
step was skipped or the wrong libraries were baked.

**Record misalignment.** If a library reference in `cmd.lib.setup` points at a record
that is missing or is not a spectrum head (stale/wrong-vintage recipe), `verify-config`
fails with:

```
cmd.lib.setup...: [sprlb06] record <n> is out of range / not a data-start
in .../r06<slug> (M records) — ... The library is stale/misaligned relative to this config.
```

Fix the recipe (or use the matching finished library) so the convolved records line up
with the config, then rebuild.
