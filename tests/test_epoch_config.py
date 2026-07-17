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
