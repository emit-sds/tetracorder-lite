"""Tests for the recipe regenerator (reproduces USGS mak.convolve.1.cmds).

These build a tiny synthetic specpr master in memory and assert that
``build_recipe_from_master`` enumerates the mineral records in order, mapping each
to its native (inwave, inres) grid by channel count, and skips the grid/setup
records — then that ``write_recipe_cmds`` round-trips through ``read_recipe``.
"""
import struct

import pytest

from tetrapy import convolve as C
from tetrapy.convolve import (
    RECLEN, OFF_ITCHAN, build_recipe_from_master, write_recipe_cmds,
    read_recipe, CHANNELS_TO_GRID,
)


def _rec(title, *, itchan, data_start=True):
    """Minimal specpr 1536-byte record: icflag low-2-bits + title + itchan.

    ``build_recipe_from_master`` reads only _is_data_start (icflag&3==0), _title
    (bytes 4:44) and _itchan (int32 at OFF_ITCHAN).
    """
    rec = bytearray(RECLEN)
    struct.pack_into(">i", rec, 0, 0 if data_start else 2)
    rec[4:44] = title.encode("ascii", "replace")[:40].ljust(40, b" ")
    struct.pack_into(">i", rec, OFF_ITCHAN, itchan)
    return bytes(rec)


def _write_master(path, records):
    path.write_bytes(b"".join(records))


def test_regen_enumerates_minerals_and_maps_grid(tmp_path):
    # 2 grid/setup records (skipped) + 3 minerals with different channel counts.
    recs = [
        _rec("Wavelengths Standard ASD FR 0.35-2.5um", itchan=2151),  # setup -> skip
        _rec("Bandpass (FWHM) ASD FR 0.35-2.5um", itchan=2151),       # setup -> skip
        _rec("Kaolinite CM9 field sample", itchan=2151),              # -> (28,34)
        _rec("Hematite GDS27 nicolet", itchan=4595),                  # -> (120,133)
        _rec("Chalcedony CU beckman", itchan=3961),                   # -> (6,17)
    ]
    master = tmp_path / "sprlb06b"
    _write_master(master, recs)

    rows = build_recipe_from_master(master, "r06emitc")

    assert [r["recnum"] for r in rows] == [2, 3, 4]  # minerals only, in order
    assert (rows[0]["inwave"], rows[0]["inres"]) == CHANNELS_TO_GRID[2151]
    assert (rows[1]["inwave"], rows[1]["inres"]) == CHANNELS_TO_GRID[4595]
    assert (rows[2]["inwave"], rows[2]["inres"]) == CHANNELS_TO_GRID[3961]
    assert rows[0]["title"].startswith("Kaolinite CM9")


def test_regen_rejects_unknown_channel_count(tmp_path):
    recs = [
        _rec("Wavelengths Standard ASD FR 0.35-2.5um", itchan=2151),
        _rec("Weird Spectrum", itchan=999),  # no known native grid
    ]
    master = tmp_path / "sprlb06b"
    _write_master(master, recs)
    with pytest.raises(ValueError, match="no known native grid"):
        build_recipe_from_master(master, "r06emitc")


def test_write_recipe_roundtrips_through_read_recipe(tmp_path):
    recs = [
        _rec("Wavelengths Standard ASD FR 0.35-2.5um", itchan=2151),
        _rec("Kaolinite CM9 field sample", itchan=2151),
        _rec("Hematite GDS27 nicolet", itchan=4595),
    ]
    master = tmp_path / "sprlb06b"
    _write_master(master, recs)

    rows = build_recipe_from_master(master, "r06emitc")
    cmds = tmp_path / "conv.r06emitc.cmds"
    write_recipe_cmds(rows, cmds, sppad=4)

    parsed = read_recipe(cmds)
    assert len(parsed) == len(rows)
    for a, b in zip(rows, parsed):
        assert a["inwave"] == b["inwave"]
        assert a["inres"] == b["inres"]
        assert a["recnum"] == b["recnum"]


def test_channels_to_grid_covers_delivery_spectrometers():
    # The seven native grids the USGS generator recognizes for splib06b/sprlb06b.
    assert set(CHANNELS_TO_GRID) == {3961, 2151, 4301, 4595, 3325, 4280, 2138}
