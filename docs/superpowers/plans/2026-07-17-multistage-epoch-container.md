# Multi-stage Per-Epoch Tetracorder Container — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn tetracorder-lite into a multi-stage build that bakes a convolved spectral library, its config, and a prepared Tetracorder run tree into a per-instrument/per-epoch image (`emit-tc:<sensor>-<epoch>`), whose only runtime input is an L2A reflectance file.

**Architecture:** Three build tiers — `base` (OS + specpr/tetracorder/python), `libdata` (masters, recipes, config templates as separate cacheable COPY layers), and `epoch` (build-time convolution + config validation + baked `cmd-setup-tetrun`). Instrument/epoch identity is selected by `--build-arg`. Runtime `run` collapses to L2A-in / results-out; `convolve` becomes a build-time-only concern.

**Tech Stack:** Python 3.10+ (click, numpy, scipy, gdal via pixi), Fortran specpr/tetracorder, Docker/Podman multi-stage (`linux/amd64`), pytest for unit tests.

## Global Constraints

- Python floor: `requires-python = ">=3.10"` (container CLI runs under pixi's `default` env). Copied verbatim from `pyproject.toml`.
- Platform: image base is `--platform=linux/amd64 ubuntu:22.04` (Davinci is AMD-only). Copied from `Containerfile:3`.
- Convolve **only** from the `b` masters: standard `sl1/usgs/library06.conv/splib06b`, research `sl1/usgs/rlib06/sprlb06b`. Never `a`.
- Convolved output names are fixed by sensor: standard `s06emitc`, research `r06emitc`, installed at `/sl1/usgs/library06.conv/s06emitc` and `/sl1/usgs/rlib06/r06emitc` (paths that `restart_files/r1-emitc` already references).
- Config files are sensor-keyed and **fixed/committed**, not regenerated: `DATASETS/emit_c`, `restart_files/r1-emitc`, `DELETED.channels/delete_emit_c`. The build validates them; it does not rewrite them.
- Runtime contract: mounts are `/data` (the L2A — the only input) and `/output`. No positional args, no version/sensor/recipe runtime flags.
- `delete_<sensor>` is expert-curated; the build must never silently weaken it.
- Never commit `sl1-archive/` or `sl1-usgs-new/`.

---

### Task 1: Repo hygiene — gitignore archives, drop stray files, restore recipes/masters to new `sl1`

**Files:**
- Modify: `.gitignore`
- Create (restore into tracked `sl1`): `tetracorder/sl1/usgs/library06.conv/conv.s06emitc.cmds`, `tetracorder/sl1/usgs/library06.conv/conv.r06emitc.cmds`
- Reference (read-only, do not commit): `tetracorder/sl1-archive/usgs/library06.conv/conv.s06emitc.cmds`, `conv.r06emitc.cmds`

**Interfaces:**
- Consumes: nothing.
- Produces: a tracked `sl1/usgs/` tree containing masters (`library06.conv/splib06b`, `rlib06/sprlb06b`) and recipes (`conv.s06emitc.cmds`, `conv.r06emitc.cmds`) at the paths the later tasks and Containerfile COPY.

- [ ] **Step 1: Confirm current tracked state and what's missing**

Run:
```bash
cd tetracorder-lite
git status --short tetracorder/sl1 tetracorder/sl1-archive tetracorder/sl1-usgs-new 2>/dev/null
ls tetracorder/sl1/usgs/library06.conv/splib06b tetracorder/sl1/usgs/rlib06/sprlb06b 2>&1
ls tetracorder/sl1/usgs/library06.conv/conv.s06emitc.cmds tetracorder/sl1/usgs/library06.conv/conv.r06emitc.cmds 2>&1
```
Expected: masters exist under `sl1`; the two `conv.*emitc.cmds` recipes are MISSING under `sl1` (they currently live only under `sl1-archive`).

- [ ] **Step 2: Add archive/scratch dirs to .gitignore**

Append to `.gitignore`:
```gitignore
# Local-only spectral-library archives / staging (never commit; kept for reference)
tetracorder/sl1-archive/
tetracorder/sl1-usgs-new/
# macOS cruft
.DS_Store
**/.DS_Store
```

- [ ] **Step 3: Restore the two recipes into the tracked `sl1` tree**

Run:
```bash
cp tetracorder/sl1-archive/usgs/library06.conv/conv.s06emitc.cmds tetracorder/sl1/usgs/library06.conv/conv.s06emitc.cmds
cp tetracorder/sl1-archive/usgs/library06.conv/conv.r06emitc.cmds tetracorder/sl1/usgs/library06.conv/conv.r06emitc.cmds
```

- [ ] **Step 4: Remove any tracked .DS_Store and verify masters+recipes present**

Run:
```bash
git rm --cached -r --ignore-unmatch '*.DS_Store' 2>/dev/null; find tetracorder/sl1 -name .DS_Store -delete
ls -la tetracorder/sl1/usgs/library06.conv/splib06b tetracorder/sl1/usgs/rlib06/sprlb06b \
       tetracorder/sl1/usgs/library06.conv/conv.s06emitc.cmds tetracorder/sl1/usgs/library06.conv/conv.r06emitc.cmds
git status --short | grep -E "sl1-archive|sl1-usgs-new" || echo "OK: archives are ignored"
```
Expected: all four files listed; the `grep` prints "OK: archives are ignored".

- [ ] **Step 5: Commit**

```bash
git add .gitignore tetracorder/sl1/usgs/library06.conv/conv.s06emitc.cmds tetracorder/sl1/usgs/library06.conv/conv.r06emitc.cmds
git commit -m "chore: ignore sl1 archives, restore emitc recipes into tracked sl1"
```

---

### Task 2: Set up pytest scaffolding

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py` (empty), `tests/conftest.py`
- Create: `tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a runnable `pytest` in the pixi `default` env; `tests/conftest.py` exposes a `FIXTURES` path constant (`pathlib.Path` to `tests/fixtures`) that later tasks import.

- [ ] **Step 1: Write a smoke test that imports the package**

`tests/test_smoke.py`:
```python
def test_import_tetrapy():
    import tetrapy
    import tetrapy.convolve  # noqa: F401
    assert tetrapy is not None
```

- [ ] **Step 2: Add conftest with a fixtures path**

`tests/conftest.py`:
```python
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
```

`tests/__init__.py`: (empty file)

- [ ] **Step 3: Register pytest dev dependency in pixi**

Add to `pyproject.toml` under `[tool.pixi.dependencies]`:
```toml
pytest = ">=8,<9"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pixi run pytest tests/ -v`
Expected: `test_import_tetrapy PASSED`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/__init__.py tests/conftest.py tests/test_smoke.py
git commit -m "test: add pytest scaffolding"
```

---

### Task 3: Add a plain-text wavelength/FWHM grid reader

**Files:**
- Modify: `tetrapy/convolve.py` (add function next to `read_wavelengths_fwhm`, ~line 241)
- Create: `tests/fixtures/emit_wl_test.txt`, `tests/fixtures/emit_fwhm_test.txt`
- Test: `tests/test_grid_reader.py`

**Interfaces:**
- Consumes: nothing (numpy already imported in `convolve.py`).
- Produces: `read_wavelengths_fwhm_txt(wl_path, fwhm_path, units="nanometers") -> tuple[np.ndarray, np.ndarray]` returning (wavelengths, fwhm) in **microns**. One value per line; blank lines and `#` comments ignored; `units` in {`nanometers`,`nm`,`microns`,`um`} controls the /1000 conversion. Raises `ValueError` on length mismatch or unknown units.

- [ ] **Step 1: Write fixtures (3 channels, nanometers)**

`tests/fixtures/emit_wl_test.txt`:
```text
# EMIT test wavelengths (nm)
380.85787
388.26148
395.66809
```
`tests/fixtures/emit_fwhm_test.txt`:
```text
8.415
8.415
8.417
```

- [ ] **Step 2: Write the failing test**

`tests/test_grid_reader.py`:
```python
import numpy as np
import pytest
from tetrapy.convolve import read_wavelengths_fwhm_txt
from conftest import FIXTURES


def test_reads_nm_and_converts_to_microns():
    wl, fwhm = read_wavelengths_fwhm_txt(
        FIXTURES / "emit_wl_test.txt", FIXTURES / "emit_fwhm_test.txt"
    )
    assert wl.shape == (3,) and fwhm.shape == (3,)
    np.testing.assert_allclose(wl[0], 0.38085787, rtol=1e-6)
    np.testing.assert_allclose(fwhm[0], 0.008415, rtol=1e-6)


def test_microns_units_no_conversion():
    wl, _ = read_wavelengths_fwhm_txt(
        FIXTURES / "emit_wl_test.txt", FIXTURES / "emit_fwhm_test.txt", units="microns"
    )
    np.testing.assert_allclose(wl[0], 380.85787, rtol=1e-6)


def test_length_mismatch_raises(tmp_path):
    wl = tmp_path / "wl.txt"; wl.write_text("1.0\n2.0\n")
    fwhm = tmp_path / "fwhm.txt"; fwhm.write_text("0.1\n")
    with pytest.raises(ValueError):
        read_wavelengths_fwhm_txt(wl, fwhm)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pixi run pytest tests/test_grid_reader.py -v`
Expected: FAIL — `ImportError: cannot import name 'read_wavelengths_fwhm_txt'`.

- [ ] **Step 4: Implement the reader**

Add to `tetrapy/convolve.py` immediately after `read_wavelengths_fwhm` (after ~line 269):
```python
def read_wavelengths_fwhm_txt(wl_path, fwhm_path, units="nanometers"):
    """Read (wavelengths, fwhm) in microns from two plain-text files.

    One numeric value per line; blank lines and ``#`` comments ignored. ``units``
    is the units of BOTH files: nanometers (default; divided by 1000) or microns.
    This is the calibration deliverable format (``emit_wl_*.txt`` / ``emit_fwhm_*.txt``)
    used by the USGS convolution scripts' ``-waves`` / ``-fwhm`` inputs.
    """
    def read(path):
        vals = []
        for line in Path(path).read_text().splitlines():
            s = line.split("#", 1)[0].strip()
            if s:
                vals.append(float(s))
        return np.array(vals)

    waves, fwhm = read(wl_path), read(fwhm_path)
    if waves.shape != fwhm.shape:
        raise ValueError(f"wavelength/fwhm length mismatch: {waves.shape} vs {fwhm.shape}")
    u = units.lower()
    if u.startswith(("nan", "nm")):
        waves, fwhm = waves / 1000.0, fwhm / 1000.0
    elif not u.startswith(("mic", "um", "µ")):
        raise ValueError(f"unexpected units '{units}'")
    return waves, fwhm
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pixi run pytest tests/test_grid_reader.py -v`
Expected: all 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add tetrapy/convolve.py tests/test_grid_reader.py tests/fixtures/emit_wl_test.txt tests/fixtures/emit_fwhm_test.txt
git commit -m "feat: add plain-text wavelength/fwhm grid reader for epoch builds"
```

---

### Task 4: Let the convolution build accept a text grid (not only an ENVI header)

**Files:**
- Modify: `tetrapy/convolve.py` — `build_from_recipe` (~line 455) and `build_all` (~line 405)
- Test: `tests/test_grid_source.py`

**Interfaces:**
- Consumes: `read_wavelengths_fwhm` (ENVI) and `read_wavelengths_fwhm_txt` (Task 3).
- Produces: both `build_from_recipe(master, recipe, output, *, envi_header=None, grid=None, sppad=4)` and `build_all(spectral_lib_dir, recipe_dir, output_dir, *, envi_header=None, grid=None)` accept EITHER an `envi_header` path OR a `grid=(wavelengths_microns, fwhm_microns)` tuple. Exactly one must be provided; supplying neither or both raises `ValueError`. A new helper `resolve_grid(envi_header, grid) -> tuple[np.ndarray, np.ndarray]` centralizes this.

- [ ] **Step 1: Write the failing test**

`tests/test_grid_source.py`:
```python
import numpy as np
import pytest
from tetrapy.convolve import resolve_grid


def test_resolve_grid_from_tuple():
    wl = np.array([0.38, 0.39]); fwhm = np.array([0.008, 0.008])
    out_wl, out_fwhm = resolve_grid(envi_header=None, grid=(wl, fwhm))
    np.testing.assert_array_equal(out_wl, wl)
    np.testing.assert_array_equal(out_fwhm, fwhm)


def test_resolve_grid_requires_exactly_one():
    with pytest.raises(ValueError):
        resolve_grid(envi_header=None, grid=None)
    with pytest.raises(ValueError):
        resolve_grid(envi_header="x.hdr", grid=(np.array([1.0]), np.array([0.1])))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run pytest tests/test_grid_source.py -v`
Expected: FAIL — `cannot import name 'resolve_grid'`.

- [ ] **Step 3: Add `resolve_grid` and thread it through the builders**

Add near the grid readers in `tetrapy/convolve.py`:
```python
def resolve_grid(envi_header=None, grid=None):
    """Return (wavelengths, fwhm) in microns from exactly one grid source."""
    if (envi_header is None) == (grid is None):
        raise ValueError("provide exactly one of envi_header or grid")
    if grid is not None:
        return grid
    return read_wavelengths_fwhm(envi_header)
```

In `build_from_recipe`, change the signature to
`def build_from_recipe(master, recipe, output, *, envi_header=None, grid=None, sppad=4):`
and replace the line that reads the grid (currently `out_wl, out_fwhm = read_wavelengths_fwhm(envi_header)`, ~line 481) with:
```python
    out_wl, out_fwhm = resolve_grid(envi_header=envi_header, grid=grid)
```

In `build_all`, change the signature to
`def build_all(spectral_lib_dir, recipe_dir, output_dir, *, envi_header=None, grid=None):`
and update its internal call to `build_from_recipe(...)` to pass the source through:
```python
        build_from_recipe(master=str(master), recipe=str(recipes[0]),
                          output=output, envi_header=envi_header, grid=grid)
```

- [ ] **Step 4: Update the two existing callers in `__main__.py` to keyword form**

In `tetrapy/__main__.py` `convolve_cmd` (~lines 97 and 101), the calls must use the keyword now that `envi_header` is keyword-only:
```python
        convolve.build_from_recipe(master=master, recipe=cmds,
                                   output=output, envi_header=envi_header)
```
```python
        convolve.build_all(
            spectral_lib_dir=spectral_lib, recipe_dir=recipe_dir,
            output_dir=output_dir, envi_header=envi_header,
        )
```
(These are already keyword calls; confirm they still pass `envi_header=` and add nothing else.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pixi run pytest tests/ -v`
Expected: all PASS (grid-source + earlier tests).

- [ ] **Step 6: Commit**

```bash
git add tetrapy/convolve.py tetrapy/__main__.py tests/test_grid_source.py
git commit -m "feat: convolution accepts a text-file grid or an ENVI header"
```

---

### Task 5: DELETED.channels parser + validator

**Files:**
- Create: `tetrapy/epoch_config.py`
- Test: `tests/test_epoch_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `parse_deleted_channels(text: str) -> list[int]` — expands the USGS range syntax (`1t4` → 1,2,3,4; bare ints; trailing `c`/`C` and `#`-comments ignored; multiple whitespace-separated tokens and multiple lines) into a sorted unique channel list.
  - `validate_deleted_channels(path, nchans: int) -> None` — parses the file and raises `ValueError` if empty, malformed, or any channel is `< 1` or `> nchans`.

- [ ] **Step 1: Write the failing tests**

`tests/test_epoch_config.py`:
```python
import pytest
from tetrapy.epoch_config import parse_deleted_channels, validate_deleted_channels


def test_parse_ranges_and_singletons():
    text = "1t4 75t79 218 226 280t285c  # emit_c"
    got = parse_deleted_channels(text)
    assert got[:4] == [1, 2, 3, 4]
    assert 75 in got and 79 in got and 218 in got and 226 in got
    assert got[-1] == 285
    assert got == sorted(set(got))


def test_parse_ignores_leading_C_lines():
    text = "C\nC\n1t4 128t148c  # emit_c\n"
    got = parse_deleted_channels(text)
    assert got[0] == 1 and 148 in got


def test_validate_ok(tmp_path):
    f = tmp_path / "delete_emit_c"
    f.write_text("1t4 280t285c  # emit_c\n")
    validate_deleted_channels(f, nchans=285)  # no raise


def test_validate_out_of_range(tmp_path):
    f = tmp_path / "delete_emit_c"
    f.write_text("1t4 300t305c  # bad\n")
    with pytest.raises(ValueError):
        validate_deleted_channels(f, nchans=285)


def test_validate_empty(tmp_path):
    f = tmp_path / "delete_emit_c"
    f.write_text("C\nC\n")
    with pytest.raises(ValueError):
        validate_deleted_channels(f, nchans=285)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pixi run pytest tests/test_epoch_config.py -v`
Expected: FAIL — `No module named 'tetrapy.epoch_config'`.

- [ ] **Step 3: Implement the parser/validator**

`tetrapy/epoch_config.py`:
```python
"""Validate the sensor-keyed Tetracorder config baked into an epoch image.

The DATASET, restart, and DELETED.channels files are committed, expert-curated
artifacts (see the design spec). The epoch build does NOT rewrite them — it
validates that they are internally consistent with the delivery's channel count
and the baked convolved-library outputs.
"""
import re
from pathlib import Path


def parse_deleted_channels(text):
    """Expand USGS DELETED.channels range syntax to a sorted unique channel list.

    Tokens: ``NtM`` (inclusive range), bare integers. A trailing ``c``/``C`` on
    the last token, lone ``C`` lines, and ``#`` comments are ignored.
    """
    channels = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line in ("c", "C"):
            continue
        for tok in line.split():
            t = tok.rstrip("cC")
            if not t:
                continue
            m = re.fullmatch(r"(\d+)t(\d+)", t)
            if m:
                lo, hi = int(m.group(1)), int(m.group(2))
                channels.update(range(lo, hi + 1))
            elif t.isdigit():
                channels.add(int(t))
            else:
                raise ValueError(f"unparseable DELETED.channels token: {tok!r}")
    return sorted(channels)


def validate_deleted_channels(path, nchans):
    """Raise ValueError unless the file parses to a non-empty in-range channel set."""
    chans = parse_deleted_channels(Path(path).read_text())
    if not chans:
        raise ValueError(f"{path}: no channels parsed")
    lo, hi = chans[0], chans[-1]
    if lo < 1 or hi > nchans:
        raise ValueError(f"{path}: channel {lo}..{hi} outside [1, {nchans}]")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pixi run pytest tests/test_epoch_config.py -v`
Expected: all 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add tetrapy/epoch_config.py tests/test_epoch_config.py
git commit -m "feat: DELETED.channels parser + channel-count validator"
```

---

### Task 6: Restart-file consistency validator

**Files:**
- Modify: `tetrapy/epoch_config.py`
- Test: `tests/test_epoch_config.py` (add cases)
- Create: `tests/fixtures/r1-emitc` (trimmed copy of the real restart file)

**Interfaces:**
- Consumes: nothing.
- Produces: `validate_restart(path, *, nchans: int, iyfl: str, iwfl: str) -> None` — parses the specpr restart key=value lines and raises `ValueError` unless `nchans=` matches, `iyfl=` equals the expected standard convolved path, and `iwfl=` equals the expected research convolved path.

- [ ] **Step 1: Create the fixture (key lines only, real values)**

`tests/fixtures/r1-emitc`:
```text
SPECPR_Restart=2.00      # Restart Version
ivfl=/dev/null
iwfl=/sl1/usgs/rlib06/r06emitc
iyfl=/sl1/usgs/library06.conv/s06emitc
nchans=          285  # num wave chans
inmy=       s06emitc  # file device letter y
iwdgt=      r06emitc  # file device letter w
```

- [ ] **Step 2: Write the failing tests (append to `tests/test_epoch_config.py`)**

```python
from tetrapy.epoch_config import validate_restart
from conftest import FIXTURES

STD = "/sl1/usgs/library06.conv/s06emitc"
RES = "/sl1/usgs/rlib06/r06emitc"


def test_validate_restart_ok():
    validate_restart(FIXTURES / "r1-emitc", nchans=285, iyfl=STD, iwfl=RES)


def test_validate_restart_wrong_nchans():
    with pytest.raises(ValueError):
        validate_restart(FIXTURES / "r1-emitc", nchans=284, iyfl=STD, iwfl=RES)


def test_validate_restart_wrong_iyfl():
    with pytest.raises(ValueError):
        validate_restart(FIXTURES / "r1-emitc", nchans=285, iyfl="/wrong", iwfl=RES)
```

- [ ] **Step 3: Run to verify failure**

Run: `pixi run pytest tests/test_epoch_config.py -k restart -v`
Expected: FAIL — `cannot import name 'validate_restart'`.

- [ ] **Step 4: Implement `validate_restart`**

Append to `tetrapy/epoch_config.py`:
```python
def _restart_value(text, key):
    m = re.search(rf"^{re.escape(key)}=\s*([^\s#]+)", text, re.M)
    return m.group(1) if m else None


def validate_restart(path, *, nchans, iyfl, iwfl):
    """Raise ValueError unless the restart file matches the epoch/library wiring."""
    text = Path(path).read_text()
    got_n = _restart_value(text, "nchans")
    if got_n is None or int(got_n) != nchans:
        raise ValueError(f"{path}: nchans={got_n}, expected {nchans}")
    for key, want in (("iyfl", iyfl), ("iwfl", iwfl)):
        got = _restart_value(text, key)
        if got != want:
            raise ValueError(f"{path}: {key}={got!r}, expected {want!r}")
```

- [ ] **Step 5: Run to verify pass**

Run: `pixi run pytest tests/test_epoch_config.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add tetrapy/epoch_config.py tests/test_epoch_config.py tests/fixtures/r1-emitc
git commit -m "feat: restart-file consistency validator"
```

---

### Task 7: `verify-config` CLI command (build-time gate)

**Files:**
- Modify: `tetrapy/__main__.py`, `tetrapy/epoch_config.py`
- Test: `tests/test_verify_config_cli.py`

**Interfaces:**
- Consumes: `validate_deleted_channels`, `validate_restart` (Tasks 5–6).
- Produces:
  - `epoch_config.verify_config(cmds_dir, *, sensor, nchans, std_path, res_path) -> None` — locates `DATASETS/<sensor>`, its referenced restart file under `DATASETS/restart_files/`, and `DELETED.channels/delete_<sensor>` within `cmds_dir`; runs both validators; raises `ValueError` on any problem.
  - CLI: `tetrapy verify-config --cmds-dir PATH --sensor emit_c --nchans 285` (exits non-zero on failure). `std-path`/`res-path` default to the Global-Constraints paths.

- [ ] **Step 1: Write the failing CLI test**

`tests/test_verify_config_cli.py`:
```python
import shutil
from click.testing import CliRunner
from tetrapy.__main__ import cli
from conftest import FIXTURES


def _make_cmds_dir(tmp_path):
    d = tmp_path / "tetracorder6.00a.cmds"
    (d / "DATASETS" / "restart_files").mkdir(parents=True)
    (d / "DELETED.channels").mkdir(parents=True)
    (d / "DATASETS" / "emit_c").write_text("data= EMITc\nrestart= r1-emitc\n")
    shutil.copy(FIXTURES / "r1-emitc", d / "DATASETS" / "restart_files" / "r1-emitc")
    (d / "DELETED.channels" / "delete_emit_c").write_text("1t4 280t285c  # emit_c\n")
    return d


def test_verify_config_ok(tmp_path):
    d = _make_cmds_dir(tmp_path)
    r = CliRunner().invoke(cli, ["verify-config", "--cmds-dir", str(d),
                                 "--sensor", "emit_c", "--nchans", "285"])
    assert r.exit_code == 0, r.output


def test_verify_config_bad_nchans(tmp_path):
    d = _make_cmds_dir(tmp_path)
    r = CliRunner().invoke(cli, ["verify-config", "--cmds-dir", str(d),
                                 "--sensor", "emit_c", "--nchans", "284"])
    assert r.exit_code != 0
```

- [ ] **Step 2: Run to verify failure**

Run: `pixi run pytest tests/test_verify_config_cli.py -v`
Expected: FAIL — no such command `verify-config`.

- [ ] **Step 3: Implement `verify_config` in `epoch_config.py`**

```python
def verify_config(cmds_dir, *, sensor, nchans, std_path, res_path):
    """Validate the sensor-keyed config tree under a tetracorder*.cmds directory."""
    cmds = Path(cmds_dir)
    dataset = cmds / "DATASETS" / sensor
    if not dataset.exists():
        raise ValueError(f"missing DATASET: {dataset}")
    m = re.search(r"^restart=\s*([^\s#]+)", dataset.read_text(), re.M)
    if not m:
        raise ValueError(f"{dataset}: no restart= line")
    restart = cmds / "DATASETS" / "restart_files" / m.group(1)
    if not restart.exists():
        raise ValueError(f"missing restart file: {restart}")
    validate_restart(restart, nchans=nchans, iyfl=std_path, iwfl=res_path)
    validate_deleted_channels(cmds / "DELETED.channels" / f"delete_{sensor}", nchans)
```

- [ ] **Step 4: Add the CLI command in `__main__.py`**

After the `validate_cmd` definition (end of file), add:
```python
@cli.command("verify-config", help="Validate the sensor-keyed config tree (build-time gate).")
@click.option("--cmds-dir", required=True, help="Path to a tetracorder*.cmds directory")
@click.option("-s", "--sensor", default="emit_c")
@click.option("--nchans", type=int, required=True, help="Channel count of the epoch")
@click.option("--std-path", default="/sl1/usgs/library06.conv/s06emitc")
@click.option("--res-path", default="/sl1/usgs/rlib06/r06emitc")
def verify_config_cmd(cmds_dir, sensor, nchans, std_path, res_path):
    from tetrapy import epoch_config
    epoch_config.verify_config(cmds_dir, sensor=sensor, nchans=nchans,
                               std_path=std_path, res_path=res_path)
    click.echo(f"config OK: {sensor} @ {nchans} ch")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pixi run pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add tetrapy/epoch_config.py tetrapy/__main__.py tests/test_verify_config_cli.py
git commit -m "feat: verify-config build-time gate command"
```

---

### Task 8: Simplify the runtime `run` contract to L2A-in / results-out

**Files:**
- Modify: `tetrapy/__main__.py` (`run` command), `tetrapy/tetra.py` (`exec_tetrun` L2A discovery)
- Test: `tests/test_run_contract.py`

**Interfaces:**
- Consumes: `tetra.setup_tetrun`, `tetra.exec_tetrun`.
- Produces:
  - `tetra.discover_l2a(data_dir="/data") -> str` — returns the path (without extension, as `cmd.runtet` expects) of the single ENVI reflectance file under `data_dir`; raises `FileNotFoundError` if none and `ValueError` if more than one candidate.
  - `run` command reduced to options `--output` (default `/output/tetracorder`) and `--data-dir` (default `/data`); no `--version/--sensor/--mode/--geology/--cores/--args`. Setup is expected to be baked (Task 9); at runtime `run` calls only `exec_tetrun` against the discovered L2A. A `--setup/--no-setup` flag (default `--no-setup`) preserves the ability to run setup for local dev.

- [ ] **Step 1: Write the failing test for L2A discovery**

`tests/test_run_contract.py`:
```python
import pytest
from tetrapy import tetra


def test_discover_single_l2a(tmp_path):
    (tmp_path / "scene.hdr").write_text("ENVI\n")
    (tmp_path / "scene.img").write_bytes(b"\x00")
    assert tetra.discover_l2a(tmp_path) == str(tmp_path / "scene")


def test_discover_none_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        tetra.discover_l2a(tmp_path)


def test_discover_multiple_raises(tmp_path):
    for n in ("a", "b"):
        (tmp_path / f"{n}.hdr").write_text("ENVI\n")
        (tmp_path / f"{n}.img").write_bytes(b"\x00")
    with pytest.raises(ValueError):
        tetra.discover_l2a(tmp_path)
```

- [ ] **Step 2: Run to verify failure**

Run: `pixi run pytest tests/test_run_contract.py -v`
Expected: FAIL — `module 'tetrapy.tetra' has no attribute 'discover_l2a'`.

- [ ] **Step 3: Implement `discover_l2a` in `tetra.py`**

Add to `tetrapy/tetra.py`:
```python
def discover_l2a(data_dir="/data"):
    """Return the extensionless path of the single ENVI reflectance file in data_dir.

    A scene is an ENVI ``.hdr`` with a matching binary sidecar (``.img`` or no
    suffix). Tetracorder's ``cmd.runtet`` wants the path without the ``.hdr``.
    """
    data_dir = Path(data_dir)
    hdrs = sorted(p for p in data_dir.glob("*.hdr"))
    scenes = []
    for h in hdrs:
        stem = h.with_suffix("")
        if stem.exists() or stem.with_suffix(".img").exists():
            scenes.append(str(stem))
    if not scenes:
        raise FileNotFoundError(f"no ENVI scene (.hdr + sidecar) found in {data_dir}")
    if len(scenes) > 1:
        raise ValueError(f"expected one scene in {data_dir}, found {len(scenes)}: {scenes}")
    return scenes[0]
```

- [ ] **Step 4: Reduce the `run` command in `__main__.py`**

Replace the entire `run` command (currently `__main__.py:59-71`) with:
```python
@cli.command(help="Run tetracorder on the mounted L2A (the default container action).")
@outp
@click.option("--data-dir", default="/data", help="Directory holding the L2A ENVI scene")
@click.option("--setup/--no-setup", default=False,
              help="Run cmd-setup-tetrun first (local dev only; baked in the image)")
def run(output, data_dir, setup):
    file = tetra.discover_l2a(data_dir)
    if setup:
        tetra.setup_tetrun(output=output, file=file)
    tetra.exec_tetrun(output=output, file=file)
```

- [ ] **Step 5: Run all tests to verify they pass**

Run: `pixi run pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add tetrapy/__main__.py tetrapy/tetra.py tests/test_run_contract.py
git commit -m "feat: run contract reduced to L2A-in/results-out with scene discovery"
```

---

### Task 9: Multi-stage Containerfile — base / libdata / epoch

**Files:**
- Modify: `Containerfile`
- Create: `docs/build.md`

**Interfaces:**
- Consumes: everything above (`convolve` build-time usage, `verify-config`, baked masters/recipes/config, `run` contract).
- Produces: a three-stage build. Final stage tagged by the builder as `emit-tc:<sensor>-<epoch>`. Build args: `SENSOR` (default `emit_c`), `EPOCH_TAG`, `WL_FILE`, `FWHM_FILE`, `GRID_UNITS` (default `nanometers`), `NCHANS`. The `epoch` stage runs convolution → `verify-config` → `cmd-setup-tetrun` bake.

- [ ] **Step 1: Refactor the existing Containerfile into a `base` stage**

At the top of `Containerfile`, change the first line to name the stage. Replace `FROM --platform=linux/amd64 ubuntu:22.04` with:
```dockerfile
FROM --platform=linux/amd64 ubuntu:22.04 AS base
```
Keep every existing instruction through the specpr/tetracorder/pixi install EXCEPT the current `COPY . .` (line 113) — replace that broad copy with a narrower copy of just the source needed to compile (the `tetracorder/` engine sources, `tetrapy/`, `pyproject.toml`, `uv.lock`). Change line 113 region to:
```dockerfile
# Engine sources + python CLI (NOT the big libraries/recipes/config — those come
# in the libdata stage so they cache independently)
COPY tetracorder/AAA.INSTALL.spectroscopy-os-setup-linux.sh tetracorder/AAA.INSTALL.spectroscopy-os-setup-linux.sh
COPY tetracorder/specpr tetracorder/specpr
COPY tetracorder/tetracorder tetracorder/tetracorder
COPY tetracorder/tetracorder.cmds tetracorder/tetracorder.cmds
COPY tetrapy tetrapy
COPY pyproject.toml uv.lock README.md ./
```
Keep the existing `ln -s` / `mkdir t1` line, the specpr install, the tetracorder install, and the pixi block unchanged. Remove the final `ENTRYPOINT`/`CMD` from the base stage (they move to the epoch stage).

- [ ] **Step 2: Add the `libdata` stage (separate COPY layers)**

Append after the base stage:
```dockerfile
# ---------------------------------------------------------------------------
# libdata: reference data in independently-cacheable layers (big -> volatile)
# ---------------------------------------------------------------------------
FROM base AS libdata
# Layer A: masters (~24 MB, change rarely) at their real delivery paths
COPY tetracorder/sl1/usgs/library06.conv/splib06b /root/tetracorder/sl1/usgs/library06.conv/splib06b
COPY tetracorder/sl1/usgs/rlib06/sprlb06b        /root/tetracorder/sl1/usgs/rlib06/sprlb06b
# Layer B: convolution recipes (small, change occasionally)
COPY tetracorder/sl1/usgs/library06.conv/conv.s06emitc.cmds /root/tetracorder/sl1/usgs/library06.conv/conv.s06emitc.cmds
COPY tetracorder/sl1/usgs/library06.conv/conv.r06emitc.cmds /root/tetracorder/sl1/usgs/library06.conv/conv.r06emitc.cmds
# Layer C: sensor-keyed config templates are already inside tetracorder.cmds
#          (copied in base): DATASETS/emit_c, restart_files/r1-emitc,
#          DELETED.channels/delete_emit_c — committed, expert-curated, fixed.
```

- [ ] **Step 3: Add the `epoch` stage**

Append after `libdata`:
```dockerfile
# ---------------------------------------------------------------------------
# epoch: per-instrument/per-epoch convolution + config gate + baked setup
# ---------------------------------------------------------------------------
FROM libdata AS epoch
ARG SENSOR=emit_c
ARG EPOCH_TAG=unset
ARG NCHANS
ARG GRID_UNITS=nanometers
ARG WL_FILE
ARG FWHM_FILE

# Calibration grid deliverable (tiny text files) supplied via build context
COPY ${WL_FILE}  /epoch/emit_wl.txt
COPY ${FWHM_FILE} /epoch/emit_fwhm.txt

# 1) Convolve both libraries from the baked b-masters into the paths the
#    restart file references.
RUN tetrapy convolve-epoch \
      --sensor "${SENSOR}" \
      --wl /epoch/emit_wl.txt --fwhm /epoch/emit_fwhm.txt --units "${GRID_UNITS}" \
      --spectral-lib /root/tetracorder/sl1/usgs \
      --recipe-dir  /root/tetracorder/sl1/usgs/library06.conv

# 2) Validate the sensor-keyed config against the epoch channel count + outputs.
RUN tetrapy verify-config \
      --cmds-dir /root/tetracorder/tetracorder.cmds/tetracorder6.00a.cmds \
      --sensor "${SENSOR}" --nchans "${NCHANS}"

# 3) Bake the prepared Tetracorder run tree (setup happens once, at build time).
RUN rm -rf /root/tetbake && \
    tetrapy setup -v 6.00a -s "${SENSOR}" -m cube -o /root/tetbake -f /data/PLACEHOLDER || true

LABEL emit.sensor="${SENSOR}" emit.epoch="${EPOCH_TAG}" emit.nchans="${NCHANS}"
ENTRYPOINT ["tetrapy"]
CMD ["run"]
```
> Note: the `setup` bake uses a placeholder file path because setup writes the run
> tree independent of the scene; `run` supplies the real `/data` scene at runtime.
> Task 10 verifies the exact setup-bake invocation and removes the `|| true` once
> confirmed against the real `cmd-setup-tetrun` behavior.

- [ ] **Step 4: Add `convolve-epoch` convenience command in `__main__.py`**

This wraps `build_all` with the text grid + sensor output naming. After `convolve_cmd`, add:
```python
@cli.command("convolve-epoch", help="Convolve both libraries from a text grid into the sensor-keyed outputs (build-time).")
@click.option("-s", "--sensor", default="emit_c")
@click.option("--wl", required=True)
@click.option("--fwhm", required=True)
@click.option("--units", default="nanometers")
@click.option("--spectral-lib", default="/root/tetracorder/sl1/usgs")
@click.option("--recipe-dir", default="/root/tetracorder/sl1/usgs/library06.conv")
def convolve_epoch_cmd(sensor, wl, fwhm, units, spectral_lib, recipe_dir):
    grid = convolve.read_wavelengths_fwhm_txt(wl, fwhm, units=units)
    # standard master lives in library06.conv, research in rlib06 — build each
    # into the sensor-keyed output path the restart file references.
    convolve.build_from_recipe(
        master=f"{spectral_lib}/library06.conv/splib06b",
        recipe=f"{recipe_dir}/conv.s06{sensor.replace('_','')}.cmds",
        output=f"{spectral_lib}/library06.conv/s06{sensor.replace('_','')}", grid=grid)
    convolve.export_envi(f"{spectral_lib}/library06.conv/s06{sensor.replace('_','')}",
                         f"{spectral_lib}/library06.conv/s06{sensor.replace('_','')}_envi")
    convolve.build_from_recipe(
        master=f"{spectral_lib}/rlib06/sprlb06b",
        recipe=f"{recipe_dir}/conv.r06{sensor.replace('_','')}.cmds",
        output=f"{spectral_lib}/rlib06/r06{sensor.replace('_','')}", grid=grid)
    convolve.export_envi(f"{spectral_lib}/rlib06/r06{sensor.replace('_','')}",
                         f"{spectral_lib}/rlib06/r06{sensor.replace('_','')}_envi")
```

- [ ] **Step 5: Write `docs/build.md` (build + tag instructions)**

`docs/build.md`:
````markdown
# Building per-epoch images

Base + libdata are built once; each epoch is a build-arg-parameterized final stage.

```bash
# Base image (rebuild only when engines/deps change)
docker build --platform linux/amd64 --target base -t emit-tc-base:$(git rev-parse --short HEAD) .

# Per-epoch image (EMIT emit_c, 285 ch, 2025-07-21 calibration)
docker build --platform linux/amd64 --target epoch \
  --build-arg SENSOR=emit_c \
  --build-arg NCHANS=285 \
  --build-arg EPOCH_TAG=20250721 \
  --build-arg WL_FILE=epoch-inputs/emit_wl_20250721.txt \
  --build-arg FWHM_FILE=epoch-inputs/emit_fwhm_20250721.txt \
  -t emit-tc:emit_c-20250721 .
```

The convolution grid comes from the two text files (the calibration deliverable),
not from a scene. Place them under `epoch-inputs/` in the build context.

## Recommended manual acceptance (smoke run) — NOT automated

Before promoting a freshly built `emit-tc:<sensor>-<epoch>` image, run it against a
known L2A scene and confirm output looks right:

```bash
docker run --rm -v /path/to/known_scene:/data -v /tmp/out:/output emit-tc:emit_c-20250721
# inspect /tmp/out/tetracorder for expected mineral group outputs
```
This step is deliberately manual — we do not commit a fixture scene or run it in
the build. The image tag records which library+config were baked.
````

- [ ] **Step 6: Build the base and epoch stages**

Run:
```bash
docker build --platform linux/amd64 --target base -t emit-tc-base:test .
# epoch build requires real epoch-inputs/*.txt present in context:
docker build --platform linux/amd64 --target epoch \
  --build-arg NCHANS=285 --build-arg EPOCH_TAG=test \
  --build-arg WL_FILE=epoch-inputs/emit_wl_20250721.txt \
  --build-arg FWHM_FILE=epoch-inputs/emit_fwhm_20250721.txt \
  -t emit-tc:test .
```
Expected: base builds; epoch stage runs `convolve-epoch` and `verify-config` without error (config gate prints `config OK: emit_c @ 285 ch`).
> If `epoch-inputs/*.txt` are not yet available, this step is validated in Task 10 with the real deliverable; confirm at least `--target base` and `--target libdata` build.

- [ ] **Step 7: Commit**

```bash
git add Containerfile tetrapy/__main__.py docs/build.md
git commit -m "feat: multi-stage base/libdata/epoch build with build-arg identity"
```

---

### Task 10: End-to-end verification + README update

**Files:**
- Modify: `README.md`
- Reference: `docs/build.md`, the design spec

**Interfaces:**
- Consumes: the built `emit-tc:<sensor>-<epoch>` image and a real L2A scene.
- Produces: verified end-to-end behavior and user-facing docs matching the new contract.

- [ ] **Step 1: Confirm the epoch build produces valid convolved libraries**

Run (inside a throwaway container of the epoch image):
```bash
docker run --rm --entrypoint tetrapy emit-tc:test validate \
  /root/tetracorder/sl1/usgs/library06.conv/s06emitc \
  /root/tetracorder/sl1/usgs/library06.conv/s06emitc
```
Expected: `validate` reports zero/near-zero RMS (a library vs itself) — proves the baked standard library is readable and well-formed.

- [ ] **Step 2: Run the full pipeline against a known L2A and observe output**

Run:
```bash
docker run --rm \
  -v "$PWD/in":/data \
  -v /tmp/tcout:/output \
  emit-tc:test
ls /tmp/tcout/tetracorder | head
```
Expected: `run` discovers the single scene under `/data`, executes the baked `cmd.runtet`, and writes mineral-group outputs under `/output/tetracorder`. If setup was NOT correctly baked, this is where it surfaces — fix Task 9 Step 3 (remove `|| true`, correct the `setup` invocation) and rebuild.

- [ ] **Step 3: Update README to the new build/run model**

In `README.md`, replace the "Quick start", "Volume contract", and convolve sections so they describe:
- Runtime: `docker run --rm -v /path/to/scene:/data -v /path/to/output:/output emit-tc:<sensor>-<epoch>` — L2A is the only input; no flags; L2A↔image compatibility is the user's responsibility (asserted by the tag).
- Building per-epoch images: point to `docs/build.md`.
- Note that `convolve`/`convolve-epoch`/`verify-config` are build-time-only commands.

Replace the volume-contract table with:
```markdown
| Mount point | Purpose |
|---|---|
| `/data` | Input: the L2A reflectance scene (ENVI `.img`/`.hdr`) — the only input |
| `/output` | Output: tetracorder results |
```

- [ ] **Step 4: Run the whole test suite once more**

Run: `pixi run pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document per-epoch build + L2A-only run contract"
```

---

## Self-Review

**1. Spec coverage:**
- Three tiers (base/libdata/epoch) → Task 9. ✓
- Separate cacheable master/recipe/template layers → Task 9 Step 2. ✓
- Convolve from `b` masters at real delivery paths → Global Constraints + Tasks 4, 9. ✓
- Text-file grid reader → Task 3; threaded into builders → Task 4. ✓
- Config as fixed/validated (not rewritten), `delete_<sensor>` never weakened → Tasks 5–7. ✓
- Build-arg instrument/epoch identity → Task 9. ✓
- Runtime contract L2A-only, no positional args, convolve build-time-only → Task 8, Task 9 (ENTRYPOINT/CMD), Task 10 docs. ✓
- Verification gate = structural + config sanity, no smoke run; smoke run documented as manual → Task 7 (config), Task 10 Step 1 (structural via `validate`), `docs/build.md` (manual smoke). ✓
- Repo hygiene (ignore archives, drop .DS_Store) → Task 1. ✓

**2. Placeholder scan:** No TBD/TODO. Two explicit "verify during this task" notes (Task 9 Step 3 setup-bake `|| true`; Task 9 Step 6 conditional on `epoch-inputs`) are resolved in Task 10 Step 2 with real inputs — flagged, not hidden.

**3. Type consistency:** `read_wavelengths_fwhm_txt` (Task 3) → used in Tasks 4, 9. `resolve_grid`/`grid=` kwarg (Task 4) → used in Task 9's `convolve-epoch`. `parse_deleted_channels`/`validate_deleted_channels` (Task 5), `validate_restart` (Task 6), `verify_config` (Task 7) signatures match their call sites. `discover_l2a` (Task 8) → used in `run` and Task 10. Sensor→output naming `s06<sensor no underscore>` / `r06...` consistent between Task 9 `convolve-epoch` and the Global-Constraints paths (`emit_c`→`s06emitc`/`r06emitc`).

## Open risk carried into execution
- The exact `cmd-setup-tetrun` bake invocation (Task 9 Step 3) is the least-certain step; Task 10 Step 2 is the gate that confirms it end-to-end. Expect one iteration there.
- Requires the real `emit_wl_*/emit_fwhm_*` deliverable text files in the build context to complete Tasks 9–10; if absent, obtain from the calibration delivery (`spectroscopy-tetracorder/sl1/usgs/library06.conv/waves.ascii.files/` may contain the EMIT grid, or Phil).
