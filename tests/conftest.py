import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import synthetic  # noqa: E402


@pytest.fixture
def scene(tmp_path):
    """Synthetic reflectance + uncertainty cubes: ``(rfl, rfluncert)`` paths."""
    return synthetic.write_scene(tmp_path / "data")


@pytest.fixture
def tc_root(tmp_path):
    """A miniature tetracorder install (master libraries + command tree)."""
    return synthetic.write_tetracorder_root(tmp_path / "tetracorder")


@pytest.fixture
def cmds(tc_root):
    """The ``tetracorder{version}.cmds`` command tree inside :func:`tc_root`."""
    return synthetic.cmd_tree(tc_root)


@pytest.fixture
def reference(tmp_path):
    """Reference matrix CSV for the synthetic minerals."""
    return synthetic.write_reference(tmp_path / "reference.csv")


@pytest.fixture
def glt(tmp_path):
    """A GLT that mirrors the scene left-to-right inside a one-pixel fill border."""
    return synthetic.write_glt(tmp_path / "data/glt")


@pytest.fixture
def fake_tetracorder(monkeypatch):
    """Point the synthetic ``cmd.runtet`` at the stand-in tetracorder."""
    synthetic.use_fake_tetracorder(monkeypatch)
