# Rebase to v6.00a5 + Containerfile Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the Tetracorder v6.00a5 engine + library delivery onto the multistage branch and prune/robustify the Containerfile, so the image builds clean, passes the build gates, and runs Tetracorder on a real L2A scene producing non-zero mineral IDs.

**Architecture:** Cherry-pick the a5 *payload* (engine source, cmds-tree, research library) from draft PR #12 via path-scoped `git checkout pr12 --`, keeping the existing 3-stage Containerfile (`base` → `libdata` → `epoch`). Restore our curated `restart_files/r1-emitc`. Update `tetrapy` code + tests from the `t6.00a2` vintage to `t6.00a5` and from 1410 to 1512 research-library records. The existing build gates (`sync-restart`, `verify-config`, record-alignment) re-derive and re-validate automatically.

**Tech Stack:** Docker (linux/amd64), Fortran/ratfor engine (specpr + tetracorder), Python 3.10 CLI (`tetrapy`, pixi), pytest.

## Global Constraints

- Platform: `linux/amd64` only (davinci dep has no ARM). Copy verbatim from spec.
- Keep the 3-stage structure `base` → `libdata` → `epoch`. Do NOT adopt PR #12's single-stage Containerfile.
- Standard library `s06emitc` is byte-identical in a5 (8220 records) — do not touch it.
- Research library `r06emitc` is 1512 records in a5 → restart protection `iprtw/iprty = -(records-1) = -1511`.
- Curated files that must remain OURS (not a5's): `restart_files/r1-emitc`. `DATASETS/emit_c` is untouched by a5 (verify, no action).
- `pr12` ref already exists locally (`git fetch upstream pull/12/head:pr12` was run). Working branch: `multistage-epoch-container`.
- Frequent commits. Each task ends with a commit.

---

### Task 1: Adopt the a5 file payload (engine + cmds-tree + research library)

**Files:**
- Modify (from pr12): `tetracorder/tetracorder/` (engine `.r` sources, `authtetracorder`, `group.names.txt`, etc.)
- Modify (from pr12): `tetracorder/AAA.INSTALL.spectroscopy-os-setup-linux.sh`
- Modify (from pr12): `tetracorder/tetracorder.cmds/tetracorder6.00a.cmds/` (whole tree: rename `t6.00a2`→`t6.00a5`, a5 cmd changes, AVIRIS datasets)
- Modify (from pr12): `tetracorder/sl1/usgs/rlib06/r06emitc`, `tetracorder/sl1/usgs/library06.conv/conv.r06emitc.cmds`
- Restore (from our branch): `tetracorder/tetracorder.cmds/tetracorder6.00a.cmds/restart_files/r1-emitc`

**Interfaces:**
- Produces: the a5 cmds tree containing `cmd.lib.setup.t6.00a5` (replaces `cmd.lib.setup.t6.00a2`); a 1512-record `r06emitc`. Tasks 2–4 consume these.

- [ ] **Step 1: Confirm starting state is clean on the working branch**

Run:
```bash
cd tetracorder-lite
git switch multistage-epoch-container
git status --short
```
Expected: only the pre-existing untracked `tetracorder/sl1/usgs/library06.conv/r.r06emitc` (harmless) — no staged/modified tracked files. If other changes exist, stash them first.

- [ ] **Step 2: Pull the a5 engine source + install script from pr12**

Run:
```bash
git checkout pr12 -- \
  tetracorder/tetracorder/ \
  tetracorder/AAA.INSTALL.spectroscopy-os-setup-linux.sh
```

- [ ] **Step 3: Re-apply the exec bit lost in a5 (mode 755→644 regression)**

Run:
```bash
chmod +x tetracorder/AAA.INSTALL.spectroscopy-os-setup-linux.sh
```

- [ ] **Step 4: Pull the a5 cmds-tree and research library from pr12**

Run:
```bash
git checkout pr12 -- \
  tetracorder/tetracorder.cmds/tetracorder6.00a.cmds/ \
  tetracorder/sl1/usgs/rlib06/r06emitc \
  tetracorder/sl1/usgs/library06.conv/conv.r06emitc.cmds
```

- [ ] **Step 5: Restore OUR curated restart file (a5 didn't change it; our protection edits must survive)**

Run:
```bash
git checkout multistage-epoch-container -- \
  tetracorder/tetracorder.cmds/tetracorder6.00a.cmds/restart_files/r1-emitc
```

- [ ] **Step 6: Verify the payload landed as expected**

Run:
```bash
# a5 setup file present, a2 gone:
ls tetracorder/tetracorder.cmds/tetracorder6.00a.cmds/cmd.lib.setup.t6.00a5
! ls tetracorder/tetracorder.cmds/tetracorder6.00a.cmds/cmd.lib.setup.t6.00a2 2>/dev/null && echo "a2 correctly gone"
# research lib is 1512 records (1512*1536 = 2322432 bytes):
test $(stat -f%z tetracorder/sl1/usgs/rlib06/r06emitc) -eq 2322432 && echo "r06emitc = 1512 records OK"
# standard lib untouched (8220 records = 12625920 bytes):
test $(stat -f%z tetracorder/sl1/usgs/library06.conv/s06emitc) -eq 12625920 && echo "s06emitc unchanged OK"
# our curated files intact:
git diff --quiet multistage-epoch-container -- tetracorder/tetracorder.cmds/tetracorder6.00a.cmds/restart_files/r1-emitc && echo "r1-emitc = ours OK"
git diff --quiet multistage-epoch-container -- tetracorder/tetracorder.cmds/tetracorder6.00a.cmds/DATASETS/emit_c && echo "emit_c DATASET = unchanged OK"
```
Expected: all five OK lines print.

- [ ] **Step 7: Commit the payload**

Run:
```bash
git add -A tetracorder/
git commit -m "feat: adopt Tetracorder v6.00a5 engine + library payload

Cherry-pick a5 engine source, cmds-tree (cmd.lib.setup.t6.00a5, 1512-rec
r06emitc) from PR #12 onto the multistage branch. Standard lib s06emitc
byte-identical. Curated restart_files/r1-emitc kept from our branch;
DATASETS/emit_c untouched by a5."
```

---

### Task 2: Update `tetrapy` code from the a2 vintage to a5

**Files:**
- Modify: `tetrapy/epoch_config.py:214` (docstring), `:224` (comment), `:225` (glob `t*a2` → `t*a5`)

**Interfaces:**
- Consumes: the a5 cmds tree from Task 1 (default setup file now `cmd.lib.setup.t6.00a5`).
- Produces: `_resolve_setup_file(cmds_dir, sensor)` that resolves the a5 default when no `lib=` line is present in the DATASET. Tasks 3 and 4 rely on this resolving correctly.

- [ ] **Step 1: Update the failing test first — rename the default-resolution test to a5**

In `tests/test_epoch_config.py`, replace the `test_resolve_setup_file_defaults_to_t6a2` test (lines ~239-245) with:

```python
def test_resolve_setup_file_defaults_to_t6a5(tmp_path):
    cmds = tmp_path / "cmds"
    (cmds / "DATASETS").mkdir(parents=True)
    (cmds / "DATASETS" / "emit_c").write_text("restart= r1-emitc\n")  # no lib= line
    (cmds / "cmd.lib.setup.t6.00a5").write_text("  a SMALL:  [splib06] 1 d\n")
    got = _resolve_setup_file(cmds, "emit_c")
    assert got.name == "cmd.lib.setup.t6.00a5"
```

- [ ] **Step 2: Update the `_setup_file` test helper to write the a5 name**

In `tests/test_epoch_config.py`, change the helper at line ~186:

```python
def _setup_file(tmp_path, body):
    d = tmp_path / "cmds"
    d.mkdir(exist_ok=True)
    p = d / "cmd.lib.setup.t6.00a5"
    p.write_text(body)
    return p
```

- [ ] **Step 3: Run the test to verify it FAILS (code still globs `t*a2`)**

Run: `pixi run pytest tests/test_epoch_config.py::test_resolve_setup_file_defaults_to_t6a5 -v`
Expected: FAIL — `_resolve_setup_file` finds no `t*a2` and raises `ValueError: no cmd.lib.setup.t*a2 found`.

- [ ] **Step 4: Update `_resolve_setup_file` in `tetrapy/epoch_config.py`**

Change the docstring (line ~214), comment (line ~224), and glob (line ~225):

```python
def _resolve_setup_file(cmds_dir, sensor):
    """Return the Path to the expert cmd.lib.setup file the sensor's run uses.

    The DATASET may name it via a ``lib=`` line; otherwise the shipped default for
    this cmds tree (``cmd.lib.setup.t6.00a5``) is used. Validated to exist.
    """
    cmds = Path(cmds_dir)
    dataset = cmds / "DATASETS" / sensor
    name = None
    if dataset.exists():
        m = re.search(r"^lib=\s*([^\s#]+)", dataset.read_text(), re.M)
        if m:
            name = m.group(1)
    if name is None:
        # cmd-setup-tetrun's default: lib=cmd.lib.setup.t6.00a5
        matches = sorted(cmds.glob("cmd.lib.setup.t*a5"))
        if not matches:
            raise ValueError(f"no cmd.lib.setup.t*a5 found in {cmds}")
        return matches[-1]
    setup = cmds / name
    if not setup.exists():
        raise ValueError(f"missing setup file: {setup}")
    return setup
```

- [ ] **Step 5: Run the test to verify it PASSES**

Run: `pixi run pytest tests/test_epoch_config.py::test_resolve_setup_file_defaults_to_t6a5 -v`
Expected: PASS.

- [ ] **Step 6: Run the full epoch_config test module (catch the other a2 fixtures)**

Run: `pixi run pytest tests/test_epoch_config.py -v`
Expected: all PASS. If any test still writes `cmd.lib.setup.t6.00a2` via a literal (search the file), fix it to `t6.00a5`. Re-run until green.

- [ ] **Step 7: Confirm no `t6.00a2` / `t*a2` literals remain in `tetrapy/` or `tests/`**

Run: `grep -rn "t6.00a2\|t\*a2\|6\.00a2" tetrapy/ tests/`
Expected: no output.

- [ ] **Step 8: Commit**

```bash
git add tetrapy/epoch_config.py tests/test_epoch_config.py
git commit -m "fix: resolve cmd.lib.setup.t6.00a5 default (was t6.00a2)"
```

---

### Task 3: Containerfile — a5 record-count bookkeeping + prune dead content

**Files:**
- Modify: `tetracorder-lite/Containerfile` (apt block ~11/26/34-58; libdata comments ~171-176)
- Modify: `docs/build.md:35` (record-count doc)

**Interfaces:**
- Consumes: the baked a5 libraries from Task 1.
- Produces: a Containerfile whose comments/docs state 1512 research records; `sync-restart`/`verify-config` invocations are unchanged (they re-derive `-1511`).

- [ ] **Step 1: Remove the duplicate `gnuplot` apt package**

In `Containerfile`, the `apt-get install` list names `gnuplot` twice (once near the `#~ davinci` group ~line 11, once near `#~ tetracorder` ~line 26). Delete the second occurrence (the one at ~line 26), keeping `gnuplot-x11`.

- [ ] **Step 2: Remove the dead commented-out "extras" apt block**

Delete the commented block "extras installed by the install script" through the end of the commented package list (the run of `# glibc-doc \` … `# imagemagick-doc \` lines, ~34-58). Replace with a single line:
```
      #~~ (extras the install script may reference are pulled transitively; none needed explicitly)
```

- [ ] **Step 3: Update the libdata-stage comment block to a5 record counts**

In the `libdata` stage comment (~lines 170-176), change the two references:
- `cmd.lib.setup.t6.00a2` → `cmd.lib.setup.t6.00a5`
- `r06emitc (1410 recs)` → `r06emitc (1512 recs)`
Leave `s06emitc (8220 recs)` and the explanatory zero-ID paragraph intact.

- [ ] **Step 4: Update `docs/build.md` record count**

In `docs/build.md:35`, change `` `r06emitc` = 1410 records `` → `` `r06emitc` = 1512 records ``. Leave `s06emitc = 8220 records` as-is.

- [ ] **Step 5: Verify no stale counts/names remain in Containerfile or build.md**

Run: `grep -n "1410\|1409\|t6.00a2" Containerfile docs/build.md`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add Containerfile docs/build.md
git commit -m "chore: a5 record-count bookkeeping; prune dead apt block + dup gnuplot"
```

---

### Task 4: Containerfile — robustify brittle line-number `sed` patches

**Files:**
- Modify: `tetracorder-lite/Containerfile` (specpr install RUN ~133-139; tetracorder install RUN ~142-156)

**Interfaces:**
- Consumes: the a5 install scripts + source from Task 1 (multmap.h and specpr install script confirmed unchanged by a5; the tetracorder install script IS a5's).
- Produces: content-anchored patches that survive a5 line-number shifts.

**Background (verified):** a5 leaves `multmap.h` and the specpr install script byte-unchanged, so those anchor swaps are durability insurance. The `AAA.INSTALL.spectroscopy-os-setup-linux.sh` is a5's version — its chown/chmod loop and forced-install block are the real robustification targets.

- [ ] **Step 1: Robustify the specpr `psplotdaemon` skip**

In the specpr install RUN block, replace the positional
`sed -i "234,245 s/^/#/" AAA.INSTALL.specpr+support-progs-linux-upgrade.1.7.sh`
with a range anchored to the block's start marker (`src.psplotdaemon`) through the following `make install` guard. Use awk-free sed range addressing:

```dockerfile
    # psplotdaemon does not compile (unresolved errors); skip its build block.
    # Anchored to the block's markers so it survives upstream line-number shifts.
    sed -i '/src\.psplotdaemon/,/^[[:space:]]*make install/ s/^/#/' AAA.INSTALL.specpr+support-progs-linux-upgrade.1.7.sh &&\
```

- [ ] **Step 2: Robustify the tetracorder install chown/chmod suppression**

In the tetracorder install RUN block, replace
`sed -i "398,416 s/^/#/" AAA.INSTALL.spectroscopy-os-setup-linux.sh`
with a range anchored to the ownership loop (`for i in  $t1 $sl1` … its closing `done`):

```dockerfile
    # Comment out the chown/chmod ownership loop (fails on network-mounted FS).
    sed -i '/^for i in[[:space:]]*\$t1[[:space:]]*\$sl1/,/^done/ s/^/#/' AAA.INSTALL.spectroscopy-os-setup-linux.sh &&\
```

- [ ] **Step 3: Robustify the "forced installs" suppression**

The current `sed -i "231,254 s/^/#/"` masks a forced-install section. Open a5's script to find a stable anchor for that block:

Run: `sed -n '225,260p' tetracorder/AAA.INSTALL.spectroscopy-os-setup-linux.sh`

Identify the block's opening and closing marker lines from the output, then replace the positional sed with a `/START/,/END/ s/^/#/` form using those literal markers. If no clean pair of anchors exists, keep a line range BUT add a comment: `# NOTE: line range targets a5's install script (AAA.INSTALL ... vNNN); re-check on engine bump.` Document the actual markers chosen inline.

- [ ] **Step 4: Robustify the `multmap.h` block-A/block-B toggle**

Replace the two positional seds
`sed -i "137,140 s/^/#/" multmap.h` (disable block A) and
`sed -i "144,147 s/^#//" multmap.h` (enable block B)
with marker-anchored ranges. Block A begins after the `# A` marker; block B after the `# B` marker. Each block is the 4 consecutive `parameter (...)` lines:

```dockerfile
    ### Disable block A (image-cube params), enable block B (single-spectrum params)
    sed -i '/^# A$/,/maxpi4=131060/ { /parameter/ s/^/#/ }' multmap.h &&\
    sed -i '/^# B/,/maxpi4=16000/ { /parameter/ s/^#//  }' multmap.h
```

- [ ] **Step 5: Sanity-check the sed expressions against the real files (dry run, no build yet)**

Run:
```bash
# psplotdaemon block gets commented:
sed -n '/src\.psplotdaemon/,/^[[:space:]]*make install/p' tetracorder/specpr/AAA.INSTALL.specpr+support-progs-linux-upgrade.1.7.sh | head
# chown loop matches:
grep -n 'for i in  *\$t1  *\$sl1' tetracorder/AAA.INSTALL.spectroscopy-os-setup-linux.sh
# multmap A/B markers present:
grep -n '^# A$\|^# B' tetracorder/tetracorder/multmap.h
```
Expected: the psplotdaemon block prints; the chown `for` line matches; both `# A` and `# B` markers found. If any anchor fails to match, adjust the regex before proceeding.

- [ ] **Step 6: Commit**

```bash
git add Containerfile
git commit -m "refactor: anchor Containerfile sed patches to content markers (a5-durable)"
```

---

### Task 5: Build the image and pass the build gates

**Files:** none modified (build + validate). May loop back to Task 1/4 on failure.

**Interfaces:**
- Consumes: the full a5 tree + cleaned Containerfile from Tasks 1-4.
- Produces: a built `epoch` image `emit-tc:emit_c-20260620-a5` with passing gates.

- [ ] **Step 1: Build the `base` stage in isolation first (a5 engine compile check)**

Run:
```bash
docker build --platform linux/amd64 --target base -t emit-tc-base:a5 .
```
Expected: completes without specpr/tetracorder `make` errors. If the a5 engine introduces a new compile error, fix it here (likely a missing anchor from Task 4 or a genuine a5 source expectation) before proceeding.

- [ ] **Step 2: Build the `epoch` stage (runs the gates: sync-restart, verify-config, record-alignment)**

Run:
```bash
docker build --platform linux/amd64 --target epoch \
  --build-arg SENSOR=emit_c \
  --build-arg NCHANS=285 \
  --build-arg EPOCH_TAG=20260620-a5 \
  --build-arg WL_FILE=epoch-inputs/emit_wl_20260620.txt \
  --build-arg FWHM_FILE=epoch-inputs/emit_fwhm_20260620.txt \
  -t emit-tc:emit_c-20260620-a5 .
```
Expected: build succeeds. The `verify-config` gate output should show every `[sprlb06]`/`[splib06]` record in `cmd.lib.setup.t6.00a5` validated against the 1512-record research / 8220-record standard libraries, and `sync-restart` deriving `iprtw=-1511`.

- [ ] **Step 3: If a gate FAILS on a record-alignment error**

A failure here means an a5 `cmd.lib.setup.t6.00a5` reference points outside the baked 1512-rec research library — the zero-ID guard working as designed. Capture the failing record number from the build log. This indicates the baked `r06emitc` and the a5 config are from different sub-vintages; re-pull both from `pr12` (Task 1 Steps 4) and confirm they are the SAME commit. Do NOT relax the gate. Re-run Step 2.

- [ ] **Step 4: Commit (no file change; this is a checkpoint — skip commit, record success in the task log)**

No commit needed. Note the built image tag `emit-tc:emit_c-20260620-a5`.

---

### Task 6: Full pytest suite green on a5

**Files:**
- Modify (if needed): any test in `tests/` pinning 1410/1409/`t6.00a2` values.

**Interfaces:**
- Consumes: updated `tetrapy` (Task 2) + a5 tree (Task 1).
- Produces: green `pixi run pytest`.

- [ ] **Step 1: Run the full suite**

Run: `pixi run pytest -v`
Expected: all pass. The record-alignment unit tests (Task 2 file) use synthetic libraries with inline record counts (100/200/1116/1104) — these are illustrative and NOT the real 1410/1512 counts, so they need NO change. Only fix a test if it FAILS.

- [ ] **Step 2: If any test fails on a hardcoded vintage/count**

Search the failing test for `1410`, `1409`, or `t6.00a2` literals that refer to the REAL delivered library (not synthetic fixtures). Update to `1512` / `1511` / `t6.00a5`. Re-run.

- [ ] **Step 3: Commit (only if a test file changed)**

```bash
git add tests/
git commit -m "test: update fixtures to a5 vintage where pinned to real libs"
```
If no test changed, skip.

---

### Task 7: End-to-end acceptance run on the real L2A scene

**Files:** none modified.

**Interfaces:**
- Consumes: the built `emit-tc:emit_c-20260620-a5` image (Task 5) and the scene `in/emit20230728t214153_rfl` (+ `.hdr`).

- [ ] **Step 1: Prepare the scene mount and output directory**

The `run` contract mounts the scene dir at `/data` and writes results to `/output`. The scene lives at `in/emit20230728t214153_rfl` with header `in/emit20230728t214153_rfl.hdr`.

Run:
```bash
mkdir -p /tmp/tc-out
ls -la in/emit20230728t214153_rfl in/emit20230728t214153_rfl.hdr
```
Expected: both files exist (img ~1.8GB + .hdr).

- [ ] **Step 2: Run the container against the scene**

Run:
```bash
docker run --rm \
  -v "$(pwd)/in:/data" \
  -v /tmp/tc-out:/output \
  emit-tc:emit_c-20260620-a5
```
Expected: runs setup + runtet against the discovered scene under `/data`; exits 0. Watch for the hardened "fail loud on runtet errors" output — a Fortran/tty error would surface here, not silently.

- [ ] **Step 3: Confirm NON-ZERO mineral-ID output (the acceptance criterion)**

Run:
```bash
find /tmp/tc-out -type f | head -50
# Expect group output files under a tetracorder results tree, non-empty:
find /tmp/tc-out -type f -size +0c | grep -iE "group|mineral|depth" | head
```
Expected: mineral-group output files present and non-empty. A tree of only zero-byte files, or no group outputs, means the zero-ID failure mode — STOP and debug (check the run log for the specpr restart-protection prompt or a tty/Fortran error).

- [ ] **Step 4: Spot-check a depth output has real values**

Run (adjust filename to an actual group output found in Step 3):
```bash
# Use gdalinfo -stats on one group depth raster to confirm non-zero max:
docker run --rm -v /tmp/tc-out:/output emit-tc:emit_c-20260620-a5 \
  bash -lc 'gdalinfo -stats /output/<group_output_file> 2>/dev/null | grep -E "Maximum|STATISTICS_MAXIMUM"'
```
Expected: a Maximum > 0 for at least one mineral group — real identifications, not an all-zero result.

- [ ] **Step 5: Record acceptance in build.md**

Append to `docs/build.md` a dated note under the smoke-run section:
```markdown
### a5 acceptance (2026-07-25)
Image `emit-tc:emit_c-20260620-a5` (v6.00a5, r06emitc=1512, s06emitc=8220) run
against `emit20230728t214153_rfl` produced non-zero mineral-group depth output.
```

- [ ] **Step 6: Commit**

```bash
git add docs/build.md
git commit -m "docs: record v6.00a5 e2e acceptance on emit20230728t214153_rfl"
```

---

## Self-Review

**Spec coverage:**
- Cherry-pick a5 payload (engine + cmds + research lib) → Task 1 ✓
- Keep curated `restart_files/r1-emitc`, verify `DATASETS/emit_c` → Task 1 Steps 5-6 ✓
- `epoch_config.py` t6.00a2→a5 (incl. the `t*a2` glob) → Task 2 ✓
- Containerfile prune (apt block, dup gnuplot) → Task 3 ✓
- Containerfile robustify seds (multmap, chown, forced-install, psplotdaemon) → Task 4 ✓
- a5 record-count bookkeeping (1410→1512) → Task 3 ✓
- Build gates pass (sync-restart→-1511, verify-config, record-alignment) → Task 5 ✓
- pytest green → Task 6 ✓
- E2E run on `in/emit20230728t214153_rfl` with non-zero IDs → Task 7 ✓

**Placeholder scan:** Task 4 Step 3 legitimately requires inspecting a5's script to pick anchors (the exact markers can't be known without reading the file mid-execution); it gives the command, the decision rule, and a documented fallback — not a blank TODO. All code/sed steps show concrete content.

**Type consistency:** `_resolve_setup_file` / `_setup_file` / `parse_library_record_refs` / `validate_record_alignment` names match `tetrapy/epoch_config.py` and `tests/test_epoch_config.py`. Record counts 1512/1511/8220 used consistently. Image tag `emit-tc:emit_c-20260620-a5` consistent across Tasks 5 and 7.
