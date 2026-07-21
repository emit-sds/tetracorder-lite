import pytest
from tetrapy import tetra


def test_discover_single_l2a(tmp_path):
    (tmp_path / "scene.hdr").write_text("ENVI\n")
    (tmp_path / "scene.img").write_bytes(b"\x00")
    assert tetra.discover_l2a(tmp_path) == str(tmp_path / "scene")


def test_discover_img_scene_exposes_extensionless_binary(tmp_path):
    # EMIT ships <stem>.img + <stem>.hdr, but tetracorder's `[ -f <stem> ]` check
    # requires the binary at the extensionless path. discover_l2a must make it exist.
    (tmp_path / "scene.hdr").write_text("ENVI\n")
    (tmp_path / "scene.img").write_bytes(b"\xDE\xAD")
    result = tetra.discover_l2a(tmp_path)
    stem = tmp_path / "scene"
    assert result == str(stem)
    assert stem.exists()  # extensionless binary now resolves (symlink -> scene.img)
    assert stem.read_bytes() == b"\xDE\xAD"


def test_discover_extensionless_scene_unchanged(tmp_path):
    # When the binary is already extensionless (tetracorder's native convention),
    # discover_l2a returns it and creates no symlink.
    (tmp_path / "r.hdr").write_text("ENVI\n")
    (tmp_path / "r").write_bytes(b"\x00")
    assert tetra.discover_l2a(tmp_path) == str(tmp_path / "r")
    assert not (tmp_path / "r").is_symlink()


def test_discover_none_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        tetra.discover_l2a(tmp_path)


def test_discover_multiple_raises(tmp_path):
    for n in ("a", "b"):
        (tmp_path / f"{n}.hdr").write_text("ENVI\n")
        (tmp_path / f"{n}.img").write_bytes(b"\x00")
    with pytest.raises(ValueError):
        tetra.discover_l2a(tmp_path)
