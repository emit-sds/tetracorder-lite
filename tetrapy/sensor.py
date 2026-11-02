"""
Integrate a convolved spectral library into the tetracorder command tree.

Once a library has been convolved onto a scene's grid (see :mod:`tetrapy.conv`), a
tetracorder run has to be told about it. That means writing, for a named "sensor",
the handful of per-sensor files the command tree looks up by name:

- ``restart_files/r1-{name}`` — the specpr restart file pointing at the convolved
  reference / research libraries.
- ``DELETED.channels/delete_{name}`` — the channels to drop for this sensor, given
  as channel numbers or as wavelength ranges resolved against the scene's grid.
- ``DISABLE/{name}`` — which analysis groups and cases are enabled vs. disabled.
- ``COLOR.channels/color-{name}`` — the color-composite channel definitions.

:func:`build` writes all four from a ``sensor`` config block. The channel count for
the restart file is read directly from the scene reflectance raster, so the restart
file self-consistently matches the scene being mapped.
"""

import logging
import re
from pathlib import Path
from typing import Iterable, List, Mapping, Sequence, Union

import numpy as np
import xarray as xr
from box import Box

from tetrapy.conv.library import NM_PER_UM, read_grid
from tetrapy.tetracorder import TetraDecoder


Logger = logging.getLogger(__name__)

# NOTE: Copied from v6.00a2 emit-c
RESTART = """\
SPECPR_Restart=2.00      # Restart Version
#
# file names
#
ivfl=/dev/null
iwfl={reslib_full}
idfl=/dev/null
iufl=/dev/null
iyfl={reflib_full}
isfl=/dev/null
ilfl=spoolfile
irfl=r1-{name}
#
# protection number for open files (v,w,d,u,y,s)
#
iprtv=             0  # device protection v
iprtw= {reslib_protection}  # device protection w
iprtd=             0  # device protection d
iprtu=         -7356  # device protection u
iprty= {reflib_protection}  # device protection y
iprts=             0  # device protection s
#
# short 8 character names associated with file device letters
#
isavt=      *unasnd*  # file device letter v
iwdgt=      {reslib_short}  # file device letter w
iwrkt=      *unasnd*  # file device letter d
inmu=       *unasnd*  # file device letter u
inmy=       {reflib_short}  # file device letter y
#
# plot control values (real number format: ex. 0.23E+01)
#
wmina=  0.350000E+00  # plot min wavelength
wmaxa=  0.250000E+01  # plot max wavelength
bbnd=   0.000000E+00  # plot min reflectance
ubnd=   0.105000E+01  # plot max reflectance
#
istarp(1)=         #  # star pack letter
istarp(2)=         0  # star pack rec. no.
#
alat=      0.0000000  # observatory lat in rads
ra=        0.0000000  # right ascension in radians
dec=       0.0000000  # declination in radians
ha=        0.0000000  # hour angle in radians
airmas=    0.0000000  # air mass of object
iwch=              0  # wavelength calib shift
#
# record pointers
#
mag0=             -1  # mag tape drive 0
mag1=             -1  # mag tape drive 1
isavf=             1  # file v
iwjf=             73  # file w
iwrkf=             1  # file d
isvcu=             1  # file u
iwjcy=             7  # file y
istrf=             1  # file s
ilpt=              1  # line Logger.debuger
icdr=              0  # card reader
ipp=               1  # Logger.debuger/plotter
#
nchans= {nchans}  # num wave chans
ibnrm1=           30  # band anal
ibnrm2=           38  # band anal
nchsav=            0  # num chan save
iline=             1  # graphics line type
#
infmth=            0  #
infopr=            1  #
inftrn=            0  #
iother(1)=         0  #
iother(2)=         0  #
iother(3)=         0  #
iother(4)=         0  #
iother(5)=         0  #
iother(6)=         0  #
iother(7)=         0  #
iother(8)=         0  #
iother(9)=         0  #
#
cfile=#                                         #
#
igrmod=           51  # graphics mode
#
itrol(1)=          Y  # wavelength file id
itrol(2)=          6  # record in use
itrol(3)=          a  # chan/wave/energy plot flag
#
# parameters for 3D file I/O
#
filtyp(1,1)=          0  # specpr file flag
filtyp(2,1)=          0  # file header lgth
filtyp(3,1)=          0  # record length
filtyp(4,1)=          0  # record hdr lgth
filtyp(5,1)=          0  # DN offset
filtyp(6,1)=          0  # x - dimension
filtyp(7,1)=          0  # y - dimension
filtyp(8,1)=          0  # z - dimension
filtyp(9,1)=          0  # data type
filtyp(10,1)=         0  # file order
filtyp(11,1)=         0  # point deletion
filtyp(12,1)=         0  # blank
filtyp(1,2)=          0  # specpr file flag
filtyp(2,2)=          0  # file header lgth
filtyp(3,2)=          0  # record length
filtyp(4,2)=          0  # record hdr lgth
filtyp(5,2)=          0  # DN offset
filtyp(6,2)=          0  # x - dimension
filtyp(7,2)=          0  # y - dimension
filtyp(8,2)=          0  # z - dimension
filtyp(9,2)=          0  # data type
filtyp(10,2)=         0  # file order
filtyp(11,2)=         0  # point deletion
filtyp(12,2)=         0  # blank
filtyp(1,3)=          0  # specpr file flag
filtyp(2,3)=          0  # file header lgth
filtyp(3,3)=          0  # record length
filtyp(4,3)=          0  # record hdr lgth
filtyp(5,3)=          0  # DN offset
filtyp(6,3)=          0  # x - dimension
filtyp(7,3)=          0  # y - dimension
filtyp(8,3)=          0  # z - dimension
filtyp(9,3)=          0  # data type
filtyp(10,3)=         0  # file order
filtyp(11,3)=         0  # point deletion
filtyp(12,3)=         0  # blank
filtyp(1,4)=          0  # specpr file flag
filtyp(2,4)=          0  # file header lgth
filtyp(3,4)=          0  # record length
filtyp(4,4)=          0  # record hdr lgth
filtyp(5,4)=          0  # DN offset
filtyp(6,4)=          0  # x - dimension
filtyp(7,4)=          0  # y - dimension
filtyp(8,4)=          0  # z - dimension
filtyp(9,4)=          0  # data type
filtyp(10,4)=         0  # file order
filtyp(11,4)=         0  # point deletion
filtyp(12,4)=         0  # blank
filtyp(1,5)=          0  # specpr file flag
filtyp(2,5)=          0  # file header lgth
filtyp(3,5)=          0  # record length
filtyp(4,5)=          0  # record hdr lgth
filtyp(5,5)=          0  # DN offset
filtyp(6,5)=          0  # x - dimension
filtyp(7,5)=          0  # y - dimension
filtyp(8,5)=          0  # z - dimension
filtyp(9,5)=          0  # data type
filtyp(10,5)=         0  # file order
filtyp(11,5)=         0  # point deletion
filtyp(12,5)=         0  # blank
"""


def parse_list(vals: Iterable[Union[int, str]]) -> List[int]:
    """
    Expand a mixed list of ints and ``"a-b"`` range strings into a flat int list.

    Config lists like ``[1-5, 18, 20-22]`` mix plain integers with hyphenated range
    strings; this flattens them into every integer they cover (ranges inclusive).

    Parameters
    ----------
    vals : Iterable[int or str]
        Items that are either an integer or a ``"start-end"`` range string.

    Returns
    -------
    list[int]
        The expanded integers, in the order the items were given.

    Examples
    --------
    >>> parse_list(["1-5", 18, "20-22"])
    [1, 2, 3, 4, 5, 18, 20, 21, 22]
    """
    ret = []
    for v in vals:
        if isinstance(v, str):
            a, b = map(int, v.split("-"))
            ret += list(range(a, b+1))
        else:
            ret += [v]
    return ret


def parse_channels(spec: str) -> List[int]:
    """
    Expand a tetracorder deleted-channels spec into a sorted list of channel numbers.

    The spec is whitespace-separated tokens, each a single 1-based channel ``N`` or an
    inclusive range ``NtM``. The terminating ``c`` (standalone or attached to the last
    token, e.g. ``280t285c``) and any ``# comment`` are ignored.

    Parameters
    ----------
    spec : str
        Deleted-channels spec, e.g. ``"1t4 75t79 218 280t285c"``.

    Returns
    -------
    list[int]
        Sorted, de-duplicated channel numbers.

    Raises
    ------
    ValueError
        If a token is malformed or a range is reversed.

    Examples
    --------
    >>> parse_channels("1t3 7 9t10c")
    [1, 2, 3, 7, 9, 10]
    """
    spec = str(spec).split("#", 1)[0].strip()
    if spec.endswith("c"):
        spec = spec[:-1]

    chans = set()
    for token in spec.split():
        if not (m := re.fullmatch(r"(\d+)(?:t(\d+))?", token)):
            raise ValueError(f"Invalid deleted channel token {token!r} in {spec!r}")
        a = int(m.group(1))
        b = int(m.group(2) or a)
        if a > b:
            raise ValueError(f"Reversed deleted channel range {token!r}")
        chans.update(range(a, b+1))

    return sorted(chans)


def format_channels(chans: Iterable[int]) -> str:
    """
    Compress channel numbers into tetracorder range syntax.

    Consecutive runs become ``NtM`` and isolated channels stay as plain numbers. No
    terminating ``c`` is added.

    Parameters
    ----------
    chans : Iterable[int]
        Channel numbers, in any order; duplicates are ignored.

    Returns
    -------
    str
        The compressed spec, e.g. ``"1t4 218 280t285"``.

    Examples
    --------
    >>> format_channels([3, 1, 2, 7, 9, 10])
    '1t3 7 9t10'
    """
    chans = sorted(set(chans))
    runs = []
    for ch in chans:
        if runs and ch == runs[-1][1] + 1:
            runs[-1][1] = ch
        else:
            runs.append([ch, ch])
    return " ".join(f"{a}t{b}" if a != b else f"{a}" for a, b in runs)


def wavelength_channels(
    ranges: Iterable[Sequence[float]],
    wavelengths: np.ndarray,
    units: str = "um",
) -> List[int]:
    """
    Find the channels whose centre wavelength falls inside any of the given ranges.

    Parameters
    ----------
    ranges : Iterable[Sequence[float]]
        Inclusive ``[min, max]`` wavelength ranges, in ``units``.
    wavelengths : numpy.ndarray
        Band-centre wavelengths of the scene grid, in microns.
    units : str, default="um"
        Units of ``ranges``: ``"um"`` (or ``"µm"``) or ``"nm"``.

    Returns
    -------
    list[int]
        Sorted 1-based channel numbers matched by any range.

    Raises
    ------
    ValueError
        If ``units`` is unknown, a value's magnitude does not fit ``units``, or a range
        is not an ordered ``[min, max]`` pair.

    Notes
    -----
    A range that matches no channels is logged as a warning, as it usually means a
    typo or the wrong units.
    """
    units = str(units).lower()
    if units in ("um", "µm", "micron", "microns"):
        scale = 1.0
    elif units == "nm":
        scale = NM_PER_UM
    else:
        raise ValueError(f"Unknown deleted_channels units {units!r}, expected 'um' or 'nm'")

    wavelengths = np.asarray(wavelengths)
    chans = set()
    for rng in ranges:
        if len(rng) != 2:
            raise ValueError(f"Wavelength range must be [min, max], got {list(rng)}")
        lo, hi = map(float, rng)
        if lo > hi:
            raise ValueError(f"Reversed wavelength range {[lo, hi]}")
        if scale == 1.0 and hi > 100:
            raise ValueError(f"Wavelength range {[lo, hi]} looks like nm but units is {units!r}")
        if scale == NM_PER_UM and hi < 10:
            raise ValueError(f"Wavelength range {[lo, hi]} looks like um but units is {units!r}")

        idx = np.flatnonzero((wavelengths >= lo / scale) & (wavelengths <= hi / scale))
        if not idx.size:
            Logger.warning(
                f"Deleted wavelength range {[lo, hi]} {units} matched no channels "
                f"(scene grid {wavelengths.min():.4f}-{wavelengths.max():.4f} um); "
                f"check for a typo or the wrong units"
            )
        chans.update(int(i) + 1 for i in idx)

    return sorted(chans)


def resolve_deleted_channels(
    spec: Union[str, int, Mapping],
    rfl: Union[str, Path],
    nchans: int,
) -> List[int]:
    """
    Resolve a ``sensor.deleted_channels`` config value to channel numbers.

    Parameters
    ----------
    spec : str or Mapping
        Either a tetracorder channel spec string (see :func:`parse_channels`), or a
        mapping with keys:

        ``wavelengths`` : list[[float, float]], optional
            Inclusive wavelength ranges, matched against band centres of the scene grid.
        ``units`` : str, default="um"
            Units of ``wavelengths``: ``"um"`` or ``"nm"``.
        ``channels`` : str, optional
            Extra 1-based channel numbers in tetracorder spec syntax.
    rfl : str or Path
        Scene reflectance raster; its ``.hdr`` supplies the wavelength grid. Only read
        when ``wavelengths`` is given.
    nchans : int
        Number of channels in the scene; every resolved channel must be within
        ``[1, nchans]``.

    Returns
    -------
    list[int]
        Sorted, de-duplicated channel numbers to delete.

    Raises
    ------
    TypeError
        If ``spec`` is neither a string nor a mapping.
    ValueError
        If the spec is malformed, wavelength ranges are given but the header has no
        usable wavelength grid, or a channel is outside ``[1, nchans]``.
    """
    if isinstance(spec, int):
        spec = str(spec)

    if isinstance(spec, str):
        chans = parse_channels(spec)
    elif isinstance(spec, Mapping):
        if unknown := set(spec) - {"units", "wavelengths", "channels"}:
            raise ValueError(
                f"Unknown sensor.deleted_channels keys {sorted(unknown)}, "
                f"expected 'units', 'wavelengths' and/or 'channels'"
            )

        chans = []
        if ranges := spec.get("wavelengths"):
            try:
                grid = read_grid(rfl)
            except (OSError, ValueError) as e:
                raise ValueError(
                    f"sensor.deleted_channels.wavelengths requires a wavelength grid in "
                    f"the header of {rfl}: {e}"
                ) from e
            if grid.nbands != nchans:
                raise ValueError(
                    f"Header of {rfl} has {grid.nbands} wavelengths but the raster has "
                    f"{nchans} bands"
                )
            chans += wavelength_channels(ranges, grid.wavelengths, spec.get("units") or "um")

        if channels := spec.get("channels"):
            chans += parse_channels(channels)

        chans = sorted(set(chans))
    else:
        raise TypeError(
            f"sensor.deleted_channels must be a string or a mapping, got {type(spec).__name__}"
        )

    if bad := [ch for ch in chans if not 1 <= ch <= nchans]:
        raise ValueError(f"Deleted channels {bad} are outside [1, {nchans}]")

    return chans


def build(path: Path, sensor: Box, rfl: Union[str, Path]) -> None:
    """
    Write the per-sensor tetracorder integration files for a convolved library.

    Generates the four files the tetracorder command tree looks up by sensor name — the
    restart file, deleted-channels file, enable/disable file, and color-channels file
    — so a subsequent setup/tetrun uses the convolved libraries referenced by
    ``sensor``.

    Parameters
    ----------
    path : Path
        Root of the tetracorder command tree
        (``.../tetracorder{version}.cmds``). The files are written into its
        ``restart_files/``, ``DELETED.channels/``, ``DISABLE/`` and
        ``COLOR.channels/`` subdirectories.
    sensor : box.Box
        The ``sensor`` config block. Fields used:

        ``name`` : str
            Sensor name; every written file is keyed on it.
        ``reflib`` / ``reslib`` : str
            Paths to the convolved reference / research specpr libraries, written
            into the restart file.
        ``deleted_channels`` : str or mapping
            Either a specpr channel-deletion spec (e.g. ``"1t4 75t79 ... 226c"``), or
            a mapping of ``wavelengths`` ranges (in ``units``, default ``um``) plus
            optional ``channels``, resolved against the scene's wavelength grid (see
            :func:`resolve_deleted_channels`).
        ``enable.groups`` / ``enable.cases`` : list
            Analysis groups and cases to enable (as accepted by :func:`parse_list`);
            everything else is disabled.
        ``colors`` : list[str]
            Lines for the color-channels file.
    rfl : str or Path
        Scene reflectance raster; its band count sets ``nchans`` in the restart file,
        and its ``.hdr`` supplies the grid for wavelength-based ``deleted_channels``.

    Notes
    -----
    The restart file's specpr "protection numbers" are derived from each library's
    file size (records of 1536 bytes), matching the specpr convention.
    """
    Logger.info(f"Creating sensor {sensor.name}")

    # restart_files/
    protection = lambda f: -(f.stat().st_size // 1536 - 1)

    if not (reflib := Path(sensor.reflib)).exists():
        raise FileNotFoundError(f"Reference library not found: {reflib}")
    if not (reslib := Path(sensor.reslib)).exists():
        raise FileNotFoundError(f"Research library not found: {reslib}")

    with xr.open_dataset(rfl, engine="rasterio") as ds:
        nchans = ds.band.size

    text = RESTART.format(
        name   = sensor.name,
        nchans = nchans,
        reflib_full       = reflib,
        reflib_short      = reflib.name[:8],
        reflib_protection = protection(reflib),
        reslib_full       = reslib,
        reslib_short      = reslib.name[:8],
        reslib_protection = protection(reslib),
    )
    file = path / "restart_files" / f"r1-{sensor.name}"
    file.write_text(text)
    Logger.debug(f"+ Wrote {file}")

    # DELETED.channels/
    spec = sensor.deleted_channels
    chans = resolve_deleted_channels(spec, rfl, nchans)
    deleted = format_channels(chans)

    if isinstance(spec, Mapping):
        Logger.info(
            f"Resolved deleted channels from wavelengths {spec.get('wavelengths') or []} "
            f"({spec.get('units') or 'um'}) and channels {spec.get('channels') or ''!r}"
        )
    Logger.info(f"Deleting {len(chans)} of {nchans} channels: {deleted}")

    if (size := len(f"{deleted} c")) >= 80:
        Logger.warning(
            f"Deleted channels list is {size} characters; tetracorder expects it "
            f"(including the trailing c) to be under 80"
        )

    file = path / "DELETED.channels" / f"delete_{sensor.name}"
    file.write_text(f"{deleted} c # {sensor.name}")
    Logger.debug(f"+ Wrote {file}")

    # DATASETS/
    file = path / "DATASETS" / sensor.name
    file.write_text("\n".join([
        f"data=    {sensor.name}",
        f"restart= r1-{sensor.name}",
    ]))
    Logger.debug(f"+ Wrote {file}")

    # DISABLE/
    tc = TetraDecoder(path, decode=False)
    groups = parse_list(sensor.enable.groups)
    cases = parse_list(sensor.enable.cases)

    fmt = {True: "ENABLE", False: "DISABLE"}
    lines = [
        f"{fmt[i in groups]:<7} grp {i:>2}"
        for i in sorted(tc.groups)
    ] + [
        f"{fmt[i in cases]:<7} cse {i:>2}"
        for i in range(1, 7+1) # REVIEW: Is there a better way to know how many cases Tetracorder has?
    ]
    file = path / "DISABLE" / sensor.name
    file.write_text("\n".join(lines))
    Logger.debug(f"+ Wrote {file}")

    # COLOR.channels/
    file = path / "COLOR.channels" / f"color-{sensor.name}"
    file.write_text("\n".join(sensor.colors))
    Logger.debug(f"+ Wrote {file}")
