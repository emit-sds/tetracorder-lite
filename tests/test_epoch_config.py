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


from tetrapy.epoch_config import validate_restart
from tests.conftest import FIXTURES

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


# --- record-protection rewrite (reproduces the AAA per-epoch procedure) --------
from tetrapy.epoch_config import records_in, rewrite_restart_protection


def _fake_lib(path, records):
    # specpr libraries are exactly records * 1536 bytes.
    path.write_bytes(b"\x00" * (records * 1536))


def test_records_in_counts_1536_byte_records(tmp_path):
    lib = tmp_path / "r06emitc"
    _fake_lib(lib, 1344)
    assert records_in(lib) == 1344


def test_records_in_rejects_partial_record(tmp_path):
    lib = tmp_path / "r06emitc"
    lib.write_bytes(b"\x00" * (1536 * 3 + 7))
    with pytest.raises(ValueError):
        records_in(lib)


def _restart_with_protection(tmp_path, iprtw, iprty):
    # Minimal restart preserving the real column format specpr writes.
    txt = (
        "SPECPR_Restart=2.00      # Restart Version\n"
        "iwfl=/sl1/usgs/rlib06/r06emitc\n"
        "iyfl=/sl1/usgs/library06.conv/s06emitc\n"
        f"iprtw=        {iprtw:6d}  # device protection w\n"
        "iprtd=             0  # device protection d\n"
        f"iprty=        {iprty:6d}  # device protection y\n"
        "nchans=          285  # num wave chans\n"
    )
    p = tmp_path / "r1-emitc"
    p.write_text(txt)
    return p


def test_rewrite_sets_protection_to_negative_records_minus_one(tmp_path):
    # r06emitc=1344 recs -> iprtw=-1343 ; s06emitc=8220 recs -> iprty=-8219
    res = tmp_path / "r06emitc"; _fake_lib(res, 1344)
    std = tmp_path / "s06emitc"; _fake_lib(std, 8220)
    restart = _restart_with_protection(tmp_path, iprtw=-9999, iprty=-9999)

    rewrite_restart_protection(restart, res_lib=res, std_lib=std)

    text = restart.read_text()
    from tetrapy.epoch_config import _restart_value
    assert _restart_value(text, "iprtw") == "-1343"
    assert _restart_value(text, "iprty") == "-8219"
    # Untouched neighbors and comments survive.
    assert "iprtd=             0  # device protection d" in text
    assert "# device protection w" in text
    assert "nchans=          285" in text


def test_rewrite_is_idempotent(tmp_path):
    res = tmp_path / "r06emitc"; _fake_lib(res, 1104)
    std = tmp_path / "s06emitc"; _fake_lib(std, 8220)
    restart = _restart_with_protection(tmp_path, iprtw=-1343, iprty=-8219)
    rewrite_restart_protection(restart, res_lib=res, std_lib=std)
    once = restart.read_text()
    rewrite_restart_protection(restart, res_lib=res, std_lib=std)
    assert restart.read_text() == once
    from tetrapy.epoch_config import _restart_value
    assert _restart_value(once, "iprtw") == "-1103"


def test_rewrite_missing_key_raises(tmp_path):
    res = tmp_path / "r06emitc"; _fake_lib(res, 1344)
    std = tmp_path / "s06emitc"; _fake_lib(std, 8220)
    restart = tmp_path / "r1-emitc"
    restart.write_text("iwfl=x\niyfl=y\n")  # no iprtw/iprty
    with pytest.raises(ValueError):
        rewrite_restart_protection(restart, res_lib=res, std_lib=std)


# --- verify-config now asserts protection matches built libs (fail-closed) -----
def test_validate_restart_protection_gate_ok(tmp_path):
    res = tmp_path / "r06emitc"; _fake_lib(res, 1344)
    std = tmp_path / "s06emitc"; _fake_lib(std, 8220)
    restart = _restart_with_protection(tmp_path, iprtw=-1343, iprty=-8219)
    validate_restart(restart, nchans=285,
                     iyfl="/sl1/usgs/library06.conv/s06emitc",
                     iwfl="/sl1/usgs/rlib06/r06emitc",
                     res_lib=res, std_lib=std)  # no raise


def test_validate_restart_protection_gate_mismatch(tmp_path):
    res = tmp_path / "r06emitc"; _fake_lib(res, 1104)  # real build, stale restart
    std = tmp_path / "s06emitc"; _fake_lib(std, 8220)
    restart = _restart_with_protection(tmp_path, iprtw=-1343, iprty=-8219)
    with pytest.raises(ValueError, match="protection"):
        validate_restart(restart, nchans=285,
                         iyfl="/sl1/usgs/library06.conv/s06emitc",
                         iwfl="/sl1/usgs/rlib06/r06emitc",
                         res_lib=res, std_lib=std)


# --- record-alignment gate: SMALL refs must be valid data-starts ---------------
# cmd.lib.setup addresses spectra by ABSOLUTE record number; a referenced record
# missing from the baked library makes tetracorder emit "invalid input" and yield
# zero mineral IDs. The gate fails the build closed instead.
import struct as _struct
from tetrapy.epoch_config import (
    parse_library_record_refs, validate_record_alignment, _resolve_setup_file,
)


def _lib_with_data_starts(path, n_records, data_start_indices):
    """Write an n_records specpr library where only the given record indices are
    data-starts. specpr marks a data-start by the low 2 bits of the first int32
    being 0; other records get icflag=2 (a text/continuation record)."""
    recs = []
    for i in range(n_records):
        rec = bytearray(1536)
        flag = 0 if i in data_start_indices else 2  # 0 -> data-start, 2 -> not
        rec[:4] = _struct.pack(">i", flag)
        recs.append(bytes(rec))
    path.write_bytes(b"".join(recs))


def _setup_file(tmp_path, body):
    d = tmp_path / "cmds"
    d.mkdir(exist_ok=True)
    p = d / "cmd.lib.setup.t6.00a2"
    p.write_text(body)
    return p


def test_parse_library_record_refs_only_small_active():
    body = (
        "  a SMALL:  [sprlb06]  1116 d   \\# research ref\n"
        "  a MEDIUM: [splib06]  xxxx d   \\# future placeholder (skip)\n"
        "  a LARGE:  [splib06]  xxxx d   \\# future placeholder (skip)\n"
        "  a SMALL:  [splib06]  7170 d   \\# standard ref\n"
        "   \\#    [splib06] 7020  a commented note (skip)\n"
    )
    refs = list(parse_library_record_refs(body))
    assert refs == [("sprlb06", 1116), ("splib06", 7170)]


def test_validate_record_alignment_ok(tmp_path):
    setup = _setup_file(tmp_path,
                        "  a SMALL:  [sprlb06]  100 d\n  a SMALL:  [splib06]  200 d\n")
    res = tmp_path / "r06emitc"; _lib_with_data_starts(res, 300, {100})
    std = tmp_path / "s06emitc"; _lib_with_data_starts(std, 300, {200})
    n = validate_record_alignment(setup, res_lib=res, std_lib=std)
    assert n == 2


def test_validate_record_alignment_out_of_range(tmp_path):
    # research ref 1116 but library only has 1104 records (the real bug).
    setup = _setup_file(tmp_path, "  a SMALL:  [sprlb06]  1116 d\n")
    res = tmp_path / "r06emitc"; _lib_with_data_starts(res, 1104, {30, 36})
    std = tmp_path / "s06emitc"; _lib_with_data_starts(std, 8220, {200})
    with pytest.raises(ValueError, match="out of range"):
        validate_record_alignment(setup, res_lib=res, std_lib=std)


def test_validate_record_alignment_not_a_data_start(tmp_path):
    # record 200 exists but is a text/continuation record, not a spectrum head.
    setup = _setup_file(tmp_path, "  a SMALL:  [splib06]  200 d\n")
    res = tmp_path / "r06emitc"; _lib_with_data_starts(res, 300, {100})
    std = tmp_path / "s06emitc"; _lib_with_data_starts(std, 300, {201})  # NOT 200
    with pytest.raises(ValueError, match="not a data-start"):
        validate_record_alignment(setup, res_lib=res, std_lib=std)


def test_validate_record_alignment_skips_missing_library(tmp_path):
    # only the standard lib supplied -> research refs skipped, standard checked.
    setup = _setup_file(tmp_path,
                        "  a SMALL:  [sprlb06]  9999 d\n  a SMALL:  [splib06]  200 d\n")
    std = tmp_path / "s06emitc"; _lib_with_data_starts(std, 300, {200})
    n = validate_record_alignment(setup, res_lib=None, std_lib=std)
    assert n == 1  # only the splib06 ref was checkable


def test_resolve_setup_file_defaults_to_t6a2(tmp_path):
    cmds = tmp_path / "cmds"
    (cmds / "DATASETS").mkdir(parents=True)
    (cmds / "DATASETS" / "emit_c").write_text("restart= r1-emitc\n")  # no lib= line
    (cmds / "cmd.lib.setup.t6.00a2").write_text("  a SMALL:  [splib06] 1 d\n")
    got = _resolve_setup_file(cmds, "emit_c")
    assert got.name == "cmd.lib.setup.t6.00a2"
