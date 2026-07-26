# Design: Rebase to Tetracorder v6.00a5 + Containerfile cleanup

**Date:** 2026-07-25
**Branch:** `multistage-epoch-container`
**Supersedes library/config vintage in:** `2026-07-17-multistage-epoch-container-design.md`

## Goal

Bring the **v6.00a5** Tetracorder engine + library delivery (from draft PR #12) onto the
existing multistage branch, and prune/robustify the `Containerfile`, so the image:

1. Compiles the a5 engine and bakes the a5-convolved libraries (library **frozen** in the image).
2. Passes the existing build-time gates (record-alignment, restart-sync, config channel-count).
3. Runs Tetracorder on the real L2A scene `in/emit20230728t214153_rfl` and produces
   non-zero mineral-ID / real depth output.

The 3-stage structure (`base` → `libdata` → `epoch`) is **kept**. PR #12's own Containerfile
(the pre-multistage single-stage version) is **not** adopted.

## Context: why this is a cherry-pick, not a rebase

PR #12 (`v6.00a5`, still DRAFT) branched from the **old** `main` (`1b230c4`), before the entire
multistage effort. A `git rebase` onto it would conflict heavily and drag in the obsolete
single-stage Containerfile. Instead we cherry-pick the **a5 payload** onto our branch and let our
existing gates re-validate.

### What the a5 payload actually is (verified against `pr12`)

| Component | a5 change | Action |
|---|---|---|
| Engine source `tetracorder/tetracorder/*.r`, `authtetracorder`, `group.names.txt`, etc. | Modified (real engine upgrade) | **Take a5** |
| `AAA.INSTALL.spectroscopy-os-setup-linux.sh` | Modified (+ mode 755→644) | **Take a5**, re-apply exec bit |
| cmds-tree `cmd.lib.setup.t6.00a2` → `cmd.lib.setup.t6.00a5` | Renamed (R095) | **Take a5** |
| `cmd-setup-tetrun`, `cmd.runtet`, other `cmd.*` | Modified | **Take a5** |
| Research library `sl1/usgs/rlib06/r06emitc` | 1410 → **1512 records** | **Take a5** |
| `sl1/usgs/library06.conv/conv.r06emitc.cmds` | Modified | **Take a5** |
| Standard library `sl1/usgs/library06.conv/s06emitc` | **byte-identical** (8220 recs) | keep (no-op) |
| `DATASETS/emit_c` | unchanged by both | **Keep ours** |
| `restart_files/r1-emitc` | unchanged in a5; **changed by us** (protection) | **Keep ours** |
| `DELETED.channels/delete_emit_c` | a5 adds only explanatory comments; deletion spec on line 1 identical | either; **take a5** (harmless, keeps us close to upstream) |
| AVIRIS `DATASETS/aviris_*`, `WORK/*`, misc a5 additions/deletions | added/removed | take a5 wholesale (not emit_c-relevant, keeps tree consistent) |

**Curated-file protection is the one manual override:** after cherry-picking the a5 cmds-tree,
restore our `restart_files/r1-emitc`. (`DATASETS/emit_c` needs no action — untouched by a5.)

### Code impact

`tetrapy/epoch_config.py` hardcodes `cmd.lib.setup.t6.00a2` in two places
(lines ~214 and ~224). Both become `cmd.lib.setup.t6.00a5`. Grep the whole `tetrapy/` tree
for any other `t6.00a2` / `6.00a2` literal and update.

## Workstream 1 — Adopt the a5 payload

1. On `multistage-epoch-container`, apply the a5 file payload from `pr12`. Because the trees
   diverge, do this as a **path-scoped checkout** rather than a commit cherry-pick:
   - `git checkout pr12 -- tetracorder/tetracorder/ tetracorder/AAA.INSTALL.spectroscopy-os-setup-linux.sh`
   - `git checkout pr12 -- tetracorder/tetracorder.cmds/tetracorder6.00a.cmds/`
   - `git checkout pr12 -- tetracorder/sl1/usgs/rlib06/r06emitc tetracorder/sl1/usgs/library06.conv/conv.r06emitc.cmds`
2. **Restore curated file:** `git checkout multistage-epoch-container -- .../restart_files/r1-emitc`
   (verify `DATASETS/emit_c` still matches ours; it should be untouched).
3. Re-apply exec bit lost in a5: `chmod +x AAA.INSTALL.spectroscopy-os-setup-linux.sh`.
4. Fix `tetrapy/epoch_config.py` (and any other) `t6.00a2` → `t6.00a5`.
5. Confirm no stray `t6.00a2` artifacts remain (old `cmd.lib.setup.t6.00a2` file removed by rename;
   `cmd.lib.setup.t6.00a1` also deleted in a5 — fine).

## Workstream 2 — Containerfile prune + robustify

Keep `base` → `libdata` → `epoch`. Changes:

**Prune (dead / redundant):**
- Remove the large commented-out apt "extras installed by the install script" block (lines ~34–58).
- Remove the duplicate `gnuplot` (listed at both ~11 and ~26; keep one).
- Trim stale davinci commentary to a single explanatory line.

**Robustify (line-number seds → pattern-anchored):** a5 shifts source line numbers, so replace
positional `sed 'N,M s/...'` with content-anchored edits:
- `multmap.h` block-A/block-B toggle (currently `137,140` / `144,147`): anchor to the `# A` and
  `# B` marker lines. *(a5 leaves multmap.h unchanged, so this is durability insurance, not a fix.)*
- Install-script chown/chmod suppression (currently `398,416`): anchor to the
  `for i in $t1 $sl1` … `chown rclark` loop.
- Install-script "forced installs" suppression (currently `231,254`): anchor to a stable
  string in that block rather than the line range.
- specpr `psplotdaemon` skip (currently `234,245` in the specpr install script): anchor if a
  stable marker exists; otherwise keep line-range but add a comment noting the version it targets.

**a5 bookkeeping:**
- Update the libdata-stage comments and any baked record-count references from 1410 → **1512**
  (research) / 8220 (standard, unchanged).
- No change needed to `sync-restart` / `verify-config` invocations: they re-derive
  `iprtw/iprty = -(records-1)` = **-1511** from the actual baked library and gate alignment.

## Build gates (unchanged, must pass)

1. `sync-restart` rewrites restart protection to match baked libs (→ -1511 research).
2. `verify-config` asserts: config channel-count vs `NCHANS`; restart protection vs libs;
   every `[sprlb06]/[splib06]` record in `cmd.lib.setup.t6.00a5` is a valid data-start in the
   baked libraries (fail-closed record-alignment gate — the zero-ID guard).

## Acceptance criteria

1. Image builds clean on the a5 engine; all three build gates pass.
2. `pytest` green (update any test fixture pinned to 1410/`t6.00a2` → 1512/`t6.00a5`).
3. **End-to-end:** run the container against `in/emit20230728t214153_rfl` and confirm it
   produces output with non-zero mineral identifications (real depth values), not a silent
   zero-ID result.

## Risks / notes

- a5 engine `.r` (ratfor) sources are recompiled by the `base` stage; if a5 changed a build flag
  or file the install script expects, the specpr/tetracorder `make` steps could surface new
  errors. Mitigation: build the `base` stage first in isolation before wiring the full image.
- The record-alignment gate is the safety net: if the a5 `cmd.lib.setup.t6.00a5` references a
  record number outside the baked 1512-record research library, the build fails loudly instead
  of the container silently emitting zero IDs.
- Standard library unchanged means only the research-side counts/restart move.

## Out of scope

- Adopting PR #12's single-stage Containerfile.
- AVIRIS sensor support (a5 ships AVIRIS datasets; we take them into the tree but only
  build/validate `emit_c`).
- Re-convolving from masters (the `RECONVOLVE=1` opt-in path) — default bakes the delivered a5 libs.
