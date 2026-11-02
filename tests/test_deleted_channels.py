import logging
from pathlib import Path

import pytest
from box import Box

from tetrapy.conv.library import read_grid
from tetrapy.sensor import (
    format_channels,
    parse_channels,
    resolve_deleted_channels,
    wavelength_channels,
)


DATA = Path(__file__).parent / "data"
ROOT = Path(__file__).parent.parent

# EMIT grid fixture; read_grid appends the .hdr
EMIT = DATA / "emit_285"
EMIT_NCHANS = 285

# The historical EMIT deleted-channels string, hand-written for the 285-channel grid
EMIT_LEGACY = "1t4 75t79 99t106 128t148 188t214 218 219t221 226 280t285c"


@pytest.fixture
def default_spec():
    return Box.from_yaml(filename=ROOT / "config.yml").sensor.deleted_channels


def test_parse_channels():
    assert parse_channels("1t3 7 9t10c") == [1, 2, 3, 7, 9, 10]
    assert parse_channels("1t3 7 c # emit") == [1, 2, 3, 7]
    assert parse_channels("  c  # HYB2ryug") == []
    assert parse_channels("5 3t4 4") == [3, 4, 5]


@pytest.mark.parametrize("spec", ["1t", "a3", "5t3", "1-4"])
def test_parse_channels_invalid(spec):
    with pytest.raises(ValueError):
        parse_channels(spec)


def test_format_channels_roundtrip():
    chans = parse_channels(EMIT_LEGACY)
    text = format_channels(chans)
    # 218 and 219t221 are adjacent so they merge into one run
    assert text == "1t4 75t79 99t106 128t148 188t214 218t221 226 280t285"
    assert parse_channels(text) == chans
    assert format_channels([]) == ""


def test_emit_default_reproduces_legacy(default_spec):
    assert isinstance(default_spec, dict)
    chans = resolve_deleted_channels(default_spec, EMIT, EMIT_NCHANS)
    assert chans == parse_channels(EMIT_LEGACY)


def test_string_form_unchanged():
    # A string never needs the header
    chans = resolve_deleted_channels(EMIT_LEGACY, DATA / "missing", EMIT_NCHANS)
    assert chans == parse_channels(EMIT_LEGACY)


def test_nm_and_um_agree(default_spec):
    um = [list(r) for r in default_spec.wavelengths]
    nm = [[lo * 1000, hi * 1000] for lo, hi in um]
    a = resolve_deleted_channels({"units": "um", "wavelengths": um}, EMIT, EMIT_NCHANS)
    b = resolve_deleted_channels({"units": "nm", "wavelengths": nm}, EMIT, EMIT_NCHANS)
    assert a == b
    assert a


def test_units_default_um():
    spec = {"wavelengths": [[1.327, 1.477]]}
    assert resolve_deleted_channels(spec, EMIT, EMIT_NCHANS) == list(range(128, 149))


def test_range_edges_inclusive():
    wl = read_grid(EMIT).wavelengths
    # Exactly on channel 188's centre and exactly on channel 214's centre
    assert wavelength_channels([[wl[187], wl[213]]], wl) == list(range(188, 215))


@pytest.mark.parametrize("units, ranges", [
    ("um", [[1327, 1477]]),
    ("nm", [[1.327, 1.477]]),
    ("um", [[1.477, 1.327]]),
    ("um", [[1.3]]),
    ("furlongs", [[1.3, 1.4]]),
])
def test_wavelength_validation(units, ranges):
    wl = read_grid(EMIT).wavelengths
    with pytest.raises(ValueError):
        wavelength_channels(ranges, wl, units)


def test_no_match_warns(caplog):
    wl = read_grid(EMIT).wavelengths
    with caplog.at_level(logging.WARNING, logger="tetrapy.sensor"):
        assert wavelength_channels([[3.0, 3.5]], wl) == []
    assert "matched no channels" in caplog.text


@pytest.mark.parametrize("spec", [
    "0t4",
    "280t286",
    {"channels": "300"},
])
def test_channels_out_of_bounds(spec):
    with pytest.raises(ValueError, match="outside"):
        resolve_deleted_channels(spec, EMIT, EMIT_NCHANS)


def test_unknown_key():
    with pytest.raises(ValueError, match="Unknown"):
        resolve_deleted_channels({"preset": "emit"}, EMIT, EMIT_NCHANS)


def test_wrong_type():
    with pytest.raises(TypeError):
        resolve_deleted_channels([1, 2, 3], EMIT, EMIT_NCHANS)


def test_wavelengths_need_header_grid(tmp_path):
    (tmp_path / "rfl.hdr").write_text("ENVI\nbands = 3\n")
    spec = {"wavelengths": [[1.3, 1.5]]}
    with pytest.raises(ValueError, match="requires a wavelength grid"):
        resolve_deleted_channels(spec, tmp_path / "rfl", 3)
    with pytest.raises(ValueError, match="requires a wavelength grid"):
        resolve_deleted_channels(spec, tmp_path / "missing", 3)

    # Channel numbers alone don't need the grid
    assert resolve_deleted_channels({"channels": "1t2"}, tmp_path / "rfl", 3) == [1, 2]


def test_header_band_mismatch():
    with pytest.raises(ValueError, match="bands"):
        resolve_deleted_channels({"wavelengths": [[1.3, 1.5]]}, EMIT, 284)
