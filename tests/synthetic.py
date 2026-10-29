"""
Builders for synthetic tetrapy inputs.

Everything a pipeline run reads is generated here from a handful of analytic
"minerals" (a flat continuum with one Gaussian absorption): ENVI reflectance cubes,
unconvolved specpr master libraries, a miniature tetracorder command tree (expert
system, cmds.start, variables, sensor directories, and stand-in setup/run scripts),
and a reference matrix. The scene layout is known, so tests can assert that the
pipeline recovers it.
"""

import gzip
import math
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from tetrapy.conv import SpecprWriter
from tetrapy.conv.library import FIRST_SPECTRUM, PADS_PER_SPECTRUM
from tetrapy.conv.specpr import CONT_CHANNELS, HEAD_CHANNELS


REPO = Path(__file__).parents[1]

VERSION = "6.00a"
SENSOR = "synth"

# Native master-library grid (microns). >256 channels so spectra span a
# continuation record.
NATIVE_WAVE = np.round(np.linspace(0.35, 2.6, 451), 6)
NATIVE_FWHM = np.full(NATIVE_WAVE.size, 0.004)

# Scene grid (nanometers, as in EMIT headers). EMIT's 285 channels: the convolved
# library layout assumes each spectrum spans exactly one continuation record.
SCENE_WAVE = np.round(np.linspace(380.0, 2500.0, 285), 3)
SCENE_FWHM = np.full(SCENE_WAVE.size, 8.5)
SCENE_SHAPE = (6, 8)  # (lines, samples)

CONTINUUM = 0.5


@dataclass(frozen=True)
class Mineral:
    """An analytic mineral spectrum and the expert-system entry that maps it."""
    id: str
    name: str
    group: int
    library: str            # "splib06" or "sprlb06"
    center: float           # absorption center, microns
    width: float            # absorption FWHM, microns
    depth: float            # absorption depth relative to the continuum
    continuum: tuple        # (a, b, c, d) feature continuum windows, microns
    index: int              # stable index in the reference matrix

    def spectrum(self, wave: np.ndarray) -> np.ndarray:
        return absorption(wave, self.center, self.width, self.depth)

    @property
    def filename(self) -> str:
        return f"syn_{self.id}"

    @property
    def title(self) -> str:
        return f"{self.name} SYN{self.index} W1R1Ba AREF"


# Group 1 / 2 minerals compete within their group; the group 3 entry exists to
# check that disabled groups are skipped.
HEMATITE  = Mineral("hematite.syn",  "Hematite",  1, "splib06", 0.87, 0.12, 0.30, (0.70, 0.74, 1.10, 1.16), 101)
OLIVINE   = Mineral("olivine.syn",   "Olivine",   1, "splib06", 1.30, 0.20, 0.30, (1.00, 1.05, 1.60, 1.66), 102)
KAOLINITE = Mineral("kaolinite.syn", "Kaolinite", 2, "splib06", 2.20, 0.04, 0.35, (2.08, 2.11, 2.27, 2.30), 201)
CALCITE   = Mineral("calcite.syn",   "Calcite",   2, "sprlb06", 2.34, 0.05, 0.35, (2.22, 2.25, 2.42, 2.45), 202)
VEG       = Mineral("veg.syn",       "Vegetation", 3, "splib06", 0.68, 0.06, 0.40, (0.55, 0.58, 0.76, 0.79), 301)

MINERALS = [HEMATITE, OLIVINE, KAOLINITE, CALCITE, VEG]
GROUP_DIRS = {1: "group.1um/", 2: "group.2um/", 3: "group.veg/"}


def absorption(wave: np.ndarray, center: float, width: float, depth: float) -> np.ndarray:
    """A flat continuum with one Gaussian absorption (all in microns)."""
    sigma = width / 2.355
    return CONTINUUM * (1 - depth * np.exp(-0.5 * ((wave - center) / sigma) ** 2))


def truth() -> dict[int, np.ndarray]:
    """
    The planted mineral per pixel and group, as reference-matrix indices.

    Layout over the (6, 8) scene, columns in pairs::

        cols 0-1  background (no absorption)
        cols 2-3  hematite
        cols 4-5  kaolinite, plus hematite on rows 3-5
        cols 6-7  calcite
    """
    g1 = np.zeros(SCENE_SHAPE, dtype=int)
    g2 = np.zeros(SCENE_SHAPE, dtype=int)

    g1[:, 2:4] = HEMATITE.index
    g1[3:, 4:6] = HEMATITE.index
    g2[:, 4:6] = KAOLINITE.index
    g2[:, 6:8] = CALCITE.index

    return {1: g1, 2: g2}


def scene_reflectance(seed: int = 0) -> np.ndarray:
    """Synthetic scene reflectance as ``(bands, lines, samples)`` float32."""
    wave = SCENE_WAVE / 1000
    by_index = {m.index: m for m in MINERALS}
    t = truth()

    rfl = np.full((wave.size, *SCENE_SHAPE), CONTINUUM, dtype=np.float64)
    for y in range(SCENE_SHAPE[0]):
        for x in range(SCENE_SHAPE[1]):
            # Multiply in each planted absorption so mixtures stack
            spec = np.ones(wave.size)
            for g in (1, 2):
                if idx := t[g][y, x]:
                    spec *= by_index[idx].spectrum(wave) / CONTINUUM
            rfl[:, y, x] *= spec

    rng = np.random.default_rng(seed)
    rfl += rng.normal(0, 0.001, rfl.shape)

    return rfl.astype(np.float32)


#
# ENVI
#

def envi_header(
    shape: tuple[int, int, int],
    dtype: int,
    wavelength: np.ndarray | None = None,
    fwhm: np.ndarray | None = None,
    units: str = "Nanometers",
    compressed: bool = False,
    map_info: str | None = None,
) -> str:
    bands, lines, samples = shape
    text = [
        "ENVI",
        f"samples = {samples}",
        f"lines = {lines}",
        f"bands = {bands}",
        "header offset = 0",
        "file type = ENVI Standard",
        f"data type = {dtype}",
        "interleave = bsq",
        "byte order = 0",
    ]
    if compressed:
        text.append("file compression = 1")
    if map_info:
        text.append(f"map info = {{{map_info}}}")
    if wavelength is not None:
        text.append(f"wavelength units = {units}")
        text.append("wavelength = {" + ", ".join(repr(float(w)) for w in wavelength) + "}")
    if fwhm is not None:
        text.append("fwhm = {" + ", ".join(repr(float(w)) for w in fwhm) + "}")
    return "\n".join(text) + "\n"


ENVI_TYPES = {np.dtype("uint8"): 1, np.dtype("int16"): 2, np.dtype("int32"): 3, np.dtype("float32"): 4}


def write_envi(path: Path, data: np.ndarray, gz: bool = False, **kwargs) -> Path:
    """Write ``(bands, lines, samples)`` data as a BSQ ENVI file (optionally gzipped)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if data.ndim == 2:
        data = data[None]

    raw = np.ascontiguousarray(data.astype(data.dtype.newbyteorder("<"))).tobytes()
    if gz:
        with gzip.open(path, "wb") as f:
            f.write(raw)
    else:
        path.write_bytes(raw)

    hdr = envi_header(data.shape, ENVI_TYPES[data.dtype], compressed=gz, **kwargs)
    Path(f"{path}.hdr").write_text(hdr)

    return path


def write_scene(directory: Path, seed: int = 0) -> tuple[Path, Path]:
    """Write the synthetic reflectance and uncertainty cubes, returning their paths."""
    rfl = scene_reflectance(seed)
    unc = np.full_like(rfl, 0.01)

    kw = dict(wavelength=SCENE_WAVE, fwhm=SCENE_FWHM)
    return (
        write_envi(Path(directory) / "rfl", rfl, **kw),
        write_envi(Path(directory) / "rfluncert", unc, **kw),
    )


def write_glt(path: Path) -> Path:
    """
    Write a geographic GLT one pixel larger than the scene on every side (fill
    border), mirroring the scene left-to-right.
    """
    lines, samples = SCENE_SHAPE
    data = np.zeros((2, lines + 2, samples + 2), dtype=np.int32)
    for y in range(lines):
        for x in range(samples):
            data[0, y + 1, x + 1] = samples - x   # 1-based sample
            data[1, y + 1, x + 1] = y + 1         # 1-based line

    return write_envi(
        path, data,
        map_info="Geographic Lat/Lon, 1, 1, -118.0, 36.0, 0.0005, 0.0005, WGS-84",
    )


#
# specpr
#

def write_master(path: Path, minerals: list[Mineral], extra: list[tuple[str, np.ndarray]] = ()) -> Path:
    """
    Write an unconvolved specpr master library with native wavelength/bandpass grids.

    ``extra`` holds additional ``(title, values)`` spectra, e.g. one whose channel
    count has no native grid (which the convolver turns into a placeholder).
    """
    n = NATIVE_WAVE.size
    w = SpecprWriter()
    w.append_spectrum(NATIVE_WAVE, f"Wavelengths SYN {n} ch", itchan=n)
    w.append_spectrum(NATIVE_FWHM, f"Bandpass SYN {n} ch", itchan=n)
    for m in minerals:
        w.append_spectrum(m.spectrum(NATIVE_WAVE), m.title, itchan=n)
    for title, values in extra:
        w.append_spectrum(values, title, itchan=values.size)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    w.write(path)
    return path


def convolved_recno(k: int, nbands: int) -> int:
    """Record number of the ``k``-th spectrum in a convolved library of ``nbands``."""
    conts = math.ceil(max(0, nbands - HEAD_CHANNELS) / CONT_CHANNELS)
    return FIRST_SPECTRUM + k * (1 + conts + PADS_PER_SPECTRUM)


def library_members(library: str) -> list[Mineral]:
    """Minerals stored in a library, in master order."""
    return [m for m in MINERALS if m.library == library]


def record_of(mineral: Mineral) -> int:
    """The convolved record number the expert system references for ``mineral``."""
    k = library_members(mineral.library).index(mineral)
    return convolved_recno(k, SCENE_WAVE.size)


#
# Tetracorder command tree
#

def expert_block(m: Mineral) -> str:
    a, b, c, d = m.continuum
    return textwrap.dedent(f"""\
        \\#################################################################################
        group {m.group}
        use= yes           \\# yes or no
        udata: reflectance
        ID={m.id}

        define library records
          a SMALL:  [{m.library}]  {record_of(m)} d         \\# file ID, rec no.
        endlibraryrecords
        \\#=-=-=-=-=-=-=-=-=-=-=- TITLE={m.title}
        [DELETPTS]
        {m.name.lower()}                \\# output title

        define features
           f1a DLw {a:.3f}   {b:.3f}   {c:.3f}   {d:.3f}  ct [CTHRESH] rcbblc< 0.4 0.5
        endfeatures

        define constraints
           constraint:  FD-FIT>[GLBLFDFIT] DEPTH-FIT>[GLBLDPFIT]
           constraint:  FITALL>[GLBLFITALL]  DEPTHALL>0.02 0.03
        endconstraint

        define output
           output=fit depth fd
           {m.filename}       \\# Output base file name
           8 DN 255 = [DNSCALE]
           compress= zip
        endoutput

        define actions
           action: none
        endaction
        """)


EXPERT_HEADER = """\
\\# Synthetic tetracorder expert system for tetrapy tests
groupname  1  1um region    \\#  electronic absorptions
groupname  2  2-2.5um       \\#  vibrational absorptions
"""

VARIABLES = """\
==[GLBLFITALL] 0.2 0.3
==[GLBLFDFIT] 0.3 0.4
==[GLBLDPFIT] 0.5 0.6
==[CTHRESH] 0.01
==[DNSCALE] 0.5
"""

CMDS_START = "\n".join(
    [f"==[DIRg{g}]{d}" for g, d in GROUP_DIRS.items()] + ["", "mode cube", ""]
)

# Stand-in for cmd-setup-tetrun: lays out the run directory the way the real script
# does (expert system, start file, variables, restart file, cmd.runtet, TETNCPU.txt).
# The cmd.runtet it writes carries the quirks tetrapy patches out (a `time` prefix and
# a tetracorder.out redirect).
SETUP_SCRIPT = """\
#!/bin/bash
set -e
out="$1"; sensor="$2"; mode="$3"; rfl="$4"
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$out"
cp "$here"/cmd.lib.setup.t* "$here"/cmds.start.t* "$out"/
cp "$here/VARIABLES/cmd.lib.setup.variables-default" "$out/cmd.lib.setup.variables"
cp "$here/restart_files/r1-$sensor" "$out/r1"
cp "$here/DISABLE/$sensor" "$out/DISABLE"
echo 1 > "$out/TETNCPU.txt"
cat > "$out/cmd.runtet" <<'EOF'
time "$FAKE_TC_PYTHON" "$FAKE_TC_SCRIPT" "$1" "$2" > tetracorder.out 2>&1
EOF
echo "setup complete: $out $sensor $mode $rfl"
"""


def write_tetracorder_root(root: Path) -> Path:
    """
    Build a miniature tetracorder install under ``root``.

    Mirrors the paths tetrapy reads: ``sl1/usgs/library06.conv/{splib06b,sprlb06b}``
    and ``tetracorder.cmds/tetracorder{VERSION}.cmds/`` with the expert system and
    the per-sensor directories the sensor stage writes into.
    """
    root = Path(root)

    libs = root / "sl1/usgs/library06.conv"
    write_master(libs / "splib06b", library_members("splib06"))
    write_master(libs / "sprlb06b", library_members("sprlb06"))

    cmds = cmd_tree(root)
    cmds.mkdir(parents=True, exist_ok=True)
    for sub in ("restart_files", "DELETED.channels", "DATASETS", "DISABLE", "COLOR.channels", "VARIABLES"):
        (cmds / sub).mkdir(exist_ok=True)

    (cmds / f"cmd.lib.setup.t{VERSION}6").write_text(EXPERT_HEADER + "".join(expert_block(m) for m in MINERALS))
    (cmds / f"cmds.start.t{VERSION}").write_text(CMDS_START)
    (cmds / "VARIABLES/cmd.lib.setup.variables-default").write_text(VARIABLES)
    (cmds / "cmd-setup-tetrun").write_text(SETUP_SCRIPT)

    return root


def cmd_tree(root: Path) -> Path:
    return Path(root) / f"tetracorder.cmds/tetracorder{VERSION}.cmds"


def use_fake_tetracorder(monkeypatch) -> None:
    """Point the synthetic ``cmd.runtet`` at the stand-in tetracorder."""
    monkeypatch.setenv("FAKE_TC_PYTHON", sys.executable)
    monkeypatch.setenv("FAKE_TC_SCRIPT", str(Path(__file__).parent / "fake_tetracorder.py"))


def write_reference(path: Path) -> Path:
    """Reference matrix CSV mapping each mineral id to its stable index."""
    df = pd.DataFrame([
        dict(index=m.index, id=m.id, group=m.group, library=m.library, record=record_of(m),
             title=m.title, path=GROUP_DIRS[m.group] + m.filename)
        for m in MINERALS if m.group in (1, 2)
    ])
    df.to_csv(path, index=False)
    return Path(path)
