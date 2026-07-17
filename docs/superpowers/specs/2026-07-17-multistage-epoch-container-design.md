# Multi-stage, per-epoch Tetracorder container — design

**Date:** 2026-07-17
**Repo:** `tetracorder-lite` (branch `convolved-library-build`)
**Status:** approved design, ready for implementation plan

## Problem

The cluster procedure for standing up a new EMIT calibration epoch is a shell
script (`AAA.make.new.instrument.convolved.spectral.library.sh` + follow-on
steps). We ported the **library-convolution** half into `tetrapy convolve`
(pure Python: convolve masters → `s06emitc`/`r06emitc`, export ENVI, strip
header commas). Two things were left out, and the run model no longer matches
where we want to land:

1. **Config wiring was never ported** — the steps that copy a prior epoch's
   `DATASETS/`, `restart_files/`, and `DELETED.channels/` files and rewrite
   their internal references so Tetracorder can actually use the new library.
2. **The image is not epoch-versioned** — convolution/config still happen at
   run time from mounted inputs, so there is no reproducible, taggable artifact
   per calibration.
3. **The run contract is too wide** — `run` still accepts
   version/sensor/mode/params and runs `cmd-setup-tetrun` on every invocation.

## Goal

A **multi-stage build** that produces a **per-instrument, per-epoch image**
(`emit-tc:<epoch>`) in which the convolved library, the epoch config, and the
prepared Tetracorder run tree are all **baked at build time**. At run time the
**only input is the L2A reflectance file** (plus an output mount).
Configuration management is via the **image tag**.

## Non-goals

- The `cp … /store/shared/tetracorder_libraries/` NFS distribution copies (a
  cluster-side concern; handled by whoever mounts `/output`).
- Multi-instrument support beyond EMIT (`emit_c`) for now; the structure should
  not preclude it.
- A build-time smoke run (see Verification — deferred to documented manual
  practice).

## Key domain facts (verified against the delivery)

- **Convolve from the `b` masters, never `a`.** `splib06a`/`sprlb06a` are the
  native-resolution base; `splib06b`/`sprlb06b` are that base cubic-splined to
  more channels for proper convolution. Specpr restart uses `y = *06b`, `v` =
  the convolved output. (`library06.conv/AAA.README.splib06b.txt`,
  `rlib06/AAAAA.README.txt`.)
- **Delivery layout** (`spectroscopy-tetracorder/sl1/usgs/`):
  - Standard master: `library06.conv/splib06b`
  - Research master: `rlib06/sprlb06b` — lives in `rlib06/`, NOT beside the
    standard master. New deliveries arrive in this structure; keep it.
- **EMIT is a known USGS convolution instrument.** Per the `rlib06` table,
  `mak.convol.library r06emit c 285 EMIT22c` = the 285-channel in-orbit epoch.
  The container's `emit_c` sensor token → convolved outputs `s06emitc` /
  `r06emitc`, matching `restart_files/r1-emitc`
  (`iyfl=/sl1/usgs/library06.conv/s06emitc`, `iwfl=/sl1/usgs/rlib06/r06emitc`).
- As of this delivery: new standard `splib06b` is **byte-identical** (md5) to
  what was previously baked; research `sprlb06b` **differs** — the research
  master was the stale one.

## Architecture — three tiers, independently cacheable layers

### Stage `base` (`emit-tc-base:<sha>`)
OS + engines. Everything in today's `Containerfile`: apt deps, Davinci, specpr
compile, tetracorder compile (cube + single), pixi/python CLI. Changes rarely.

### Stage `libdata` (`FROM base`)
Reference data in **separate `COPY` layers**, ordered big→stable → small→volatile
so a recipe/template edit does not invalidate the 21 MB master layer:

- **Layer A — masters:** `sl1/usgs/library06.conv/splib06b`,
  `sl1/usgs/rlib06/sprlb06b` (real delivery paths).
- **Layer B — recipes:** `conv.s06emitc.cmds`, `conv.r06emitc.cmds`.
- **Layer C — config templates:** one known-good reference epoch's DATASET,
  restart file, and DELETED.channels file (baked so the build is
  self-contained; no runtime mount).

### Stage `epoch` (`FROM libdata`, per calibration) → `emit-tc:<epoch>`
Runs at **build time**, using epoch inputs supplied as build context/args:
`--epoch <tag>`, `emit_wl_<date>.txt`, `emit_fwhm_<date>.txt`.

1. **Convolve** from baked `*06b` masters + recipes, using a **new text-file
   grid reader** (`emit_wl`/`emit_fwhm` pairs — the calibration deliverable,
   matching the original script's `-waves`/`-fwhm`). Alongside the existing
   ENVI-header reader. Install outputs to the paths the restart file expects:
   `s06emitc` → `library06.conv/`, `r06emitc` → `rlib06/`, plus ENVI exports.
2. **Config wiring** (see below).
3. **Setup bake:** run `cmd-setup-tetrun` **once** with fixed build-time params
   (version `6.00a`, sensor `emit_c`, mode `cube`, geology flag, the 9-element
   parameter list) and bake the prepared run tree into the image.
4. **Verification gate** (structural + config-reference; no smoke run).

## Config wiring (the forgotten steps)

Ported into a deterministic, unit-testable module `tetrapy/epoch_config.py`.

**Follow today's cluster procedure and its file-naming convention** so a
reviewer can `ls` the config dirs and read the epoch/vintage off the filenames.
For each new epoch the stage:

1. Copies the reference-epoch **DATASET** → epoch-named file following today's
   convention (e.g. `DATASETS/em<epoch>`), rewriting `data=` / `restart=`.
2. Copies the reference **restart file** → epoch-named
   (e.g. `restart_files/r.sem<epoch>`), rewriting `iyfl=` →
   `/sl1/usgs/library06.conv/s06emitc`, `iwfl=` → `/sl1/usgs/rlib06/r06emitc`,
   and the `inmy`/`iwdgt` device-letter lines.
3. Copies the reference **DELETED.channels** → epoch-named
   (e.g. `DELETED.channels/delete_em<epoch>`), rewriting internal references.
4. Wires `cmd-setup-tetrun`'s sensor entry (`DATASETS/emit_c`) `restart=` to the
   epoch restart file, and **deletes the template originals** (old epoch files
   are tossed, not accumulated).

Filenames encode the epoch for human review; the **image tag is the source of
truth** for CM.

## Runtime contract (simplified)

| Mount | Purpose |
|---|---|
| `/data` | **The only input:** the L2A reflectance file (ENVI `.img`/`.hdr`). |
| `/output` | Tetracorder results. |

- **`run`** takes **no positional args and no version/sensor/mode/geology/`-a`
  flags.** It locates the L2A under `/data` and executes the **baked**
  `cmd.runtet` against it, writing `/output`.
- L2A ↔ image compatibility is the **user's responsibility**, asserted by the
  image tag they chose.
- **`convolve` / `cmds2csv`** are demoted to **build-time-only** internals
  (invoked by the epoch stage), not part of the runtime UX. No `/spectral-lib`
  mount at run time.
- `validate` may remain as a dev/debug utility; not part of the run contract.

## Verification gate (build-time; fails `docker build`)

1. **Structural asserts** — 30-record specpr header, record counts/layout for
   both convolved libraries (extends the asserts already in
   `build_from_recipe`).
2. **Config-reference sanity** — the generated DATASET/restart/DELETED files
   parse and every internal path reference resolves to a baked file
   (`s06emitc`, `r06emitc`, restart wiring).

**Smoke run — deferred to documented manual practice.** A tiny end-to-end
`cmd.runtet` against a real L2A is the strongest check that setup wired
correctly, but we will NOT commit a fixture L2A or run it in the build. Document
it in the README as a **recommended manual acceptance step** before promoting a
freshly built `emit-tc:<epoch>` image: run it against a known scene and confirm
output.

## Repo hygiene (rides along)

- `.gitignore`: add `sl1-archive/` and `sl1-usgs-new/` (kept locally for
  reference, never committed); remove stray `.DS_Store` under the new `sl1`.
- Masters committed at delivery paths: `sl1/usgs/library06.conv/splib06b`,
  `sl1/usgs/rlib06/sprlb06b`.

## Components & interfaces

- `tetrapy/convolve.py` — add a **text-file grid reader**
  (`read_wavelengths_fwhm_txt(wl_path, fwhm_path)`) parallel to the existing
  ENVI-header reader; convolution core unchanged.
- `tetrapy/epoch_config.py` — **new**: copy-and-rewrite DATASET / restart /
  DELETED.channels from baked templates to epoch-named files; pure text
  transforms; unit-testable with fixture template snippets.
- `Containerfile` — split into `base` / `libdata` (separate COPY layers) /
  `epoch` stages; epoch stage runs convolve → epoch_config → cmd-setup-tetrun
  bake → verification; parameterized by `--epoch`, wl/fwhm build inputs.
- `tetrapy/__main__.py` — collapse `run` to the L2A+output contract; move
  `convolve`/`cmds2csv` to build-time-only usage.
- `README.md` — new build/run instructions; per-epoch tagging; the manual
  smoke-run acceptance step.

## Open items for the implementation plan

- Choose the concrete `<epoch>` tag format (e.g. `emit_c-20250721`) and how it
  maps to the config filenames.
- Identify the specific known-good reference-epoch files to bake as templates.
- Confirm the exact set of internal references each config file needs rewritten
  (diff a prior→current pair from the cluster to enumerate them precisely).
- Confirm `export_envi` fully reproduces `specpr2envi` + `strip_tetra_commas.py`
  (no stray header commas) — verify during implementation.
- Decide how the epoch build receives the `emit_wl`/`emit_fwhm` files: `COPY`
  of a build-context directory vs `--build-arg` paths. (No runtime mount either
  way — this is a build-time input.)
