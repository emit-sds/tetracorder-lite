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
