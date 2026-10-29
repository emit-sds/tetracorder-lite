import logging
from pathlib import Path

import numpy as np
import pytest
import rasterio
import xarray as xr

import synthetic
from tetrapy import postprocess


@pytest.mark.parametrize("rel, expected", [
    ("group.1um/foo.depth.gz", "group.1um/foo.depth.tif"),
    ("group.1um/foo.fit.gz", "group.1um/foo.fit.tif"),
    ("results.masses/foo.png", "results.masses/foo.tif"),
    ("a/b/foo.GIF", "a/b/foo.tif"),
    ("foo.depth", "foo.depth.tif"),
])
def test_cog_dest(rel, expected):
    assert postprocess.cog_dest(Path(rel), Path("/out")) == Path("/out") / expected


@pytest.fixture
def tree(tmp_path):
    """A small tetracorder output tree with gzipped ENVI rasters and side files."""
    root = tmp_path / "tc"
    data = np.arange(np.prod(synthetic.SCENE_SHAPE), dtype=np.uint8).reshape(synthetic.SCENE_SHAPE)
    synthetic.write_envi(root / "group.1um/a.depth.gz", data, gz=True)
    synthetic.write_envi(root / "group.1um/a.fit.gz", data, gz=True)
    synthetic.write_envi(root / "group.2um/b.depth.gz", data, gz=True)
    (root / "results.group1").mkdir()
    (root / "results.group1/list").write_text("x")
    (root / "results.case1").write_text("x")
    (root / "keep.txt").write_text("x")
    return root, data


class TestMakeCogs:
    def test_converts_matches_and_skips_hdr(self, tree, tmp_path):
        root, data = tree
        out = tmp_path / "cogs"
        postprocess.make_cogs(str(root), ["group.*/*.depth.gz*", "group.1um/*"], str(out))

        written = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.tif"))
        assert written == ["group.1um/a.depth.tif", "group.1um/a.fit.tif", "group.2um/b.depth.tif"]

        with rasterio.open(out / "group.1um/a.depth.tif") as src:
            assert src.driver == "GTiff"
            assert src.compression.name.lower() == "deflate"
            assert src.profile["tiled"]
            np.testing.assert_array_equal(src.read(1), data)

    def test_skip_existing(self, tree, tmp_path):
        root, _ = tree
        out = tmp_path / "cogs"
        dest = out / "group.2um/b.depth.tif"
        dest.parent.mkdir(parents=True)
        dest.write_text("sentinel")

        postprocess.make_cogs(str(root), "group.2um/*.gz", str(out), skip_existing=True)
        assert dest.read_text() == "sentinel"

        postprocess.make_cogs(str(root), "group.2um/*.gz", str(out), skip_existing=False)
        with rasterio.open(dest) as src:
            assert src.count == 1

    def test_failure_is_logged_not_raised(self, tree, tmp_path, caplog):
        root, _ = tree
        (root / "group.1um/broken.depth.gz").write_bytes(b"not a raster")
        with caplog.at_level(logging.INFO, logger="tetrapy.postprocess"):
            postprocess.make_cogs(str(root), "group.1um/*.depth.gz", str(tmp_path / "cogs"))
        assert "1 failed" in caplog.text
        assert (tmp_path / "cogs/group.1um/a.depth.tif").exists()

    def test_orthorectified_with_glt(self, tree, glt, tmp_path):
        root, data = tree
        out = tmp_path / "cogs"
        postprocess.make_cogs(str(root), "group.1um/a.depth.gz", str(out), glt=str(glt))

        with rasterio.open(out / "group.1um/a.depth.tif") as src:
            assert src.crs.to_epsg() == 4326
            assert src.nodata == 0
            assert src.transform.c == pytest.approx(-118.0)
            ortho = src.read(1)

        assert ortho.shape == tuple(n + 2 for n in synthetic.SCENE_SHAPE)
        assert (ortho[0] == 0).all() and (ortho[:, 0] == 0).all()
        np.testing.assert_array_equal(ortho[1:-1, 1:-1], np.fliplr(data))


class TestOrthorectify:
    def test_out_of_range_indices_are_fill(self):
        raw = xr.DataArray(np.arange(1, 5, dtype=np.float32).reshape(1, 2, 2), dims=("band", "y", "x"),
                           coords={"band": [1]})
        glt_data = np.array([
            [[1, 2, 9]],    # sample: 9 is out of range
            [[1, 2, 1]],    # line
        ])
        glt = xr.DataArray(glt_data, dims=("band", "y", "x"), coords={"band": [1, 2], "y": [0.5], "x": [0.5, 1.5, 2.5]})
        glt.rio.write_crs("EPSG:4326", inplace=True)

        out = postprocess.orthorectify(raw, glt)
        np.testing.assert_array_equal(out.values, [[[1, 4, 0]]])
        assert out.rio.nodata == 0


class TestRemovePaths:
    def test_removes_files_and_dirs(self, tree):
        root, _ = tree
        postprocess.remove_paths(str(root), ["results.group*", "results.case*", "results.case1"])
        assert not (root / "results.group1").exists()
        assert not (root / "results.case1").exists()
        assert (root / "keep.txt").exists()

    def test_symlinked_dir_unlinked_not_followed(self, tree, tmp_path):
        root, _ = tree
        target = tmp_path / "elsewhere"
        target.mkdir()
        (target / "precious").write_text("x")
        (root / "link").symlink_to(target)

        postprocess.remove_paths(str(root), "link")
        assert not (root / "link").exists()
        assert (target / "precious").exists()


def test_run_converts_before_removing(tree, tmp_path):
    root, _ = tree
    out = tmp_path / "cogs"
    postprocess.run(str(root), cogs={"glob": ["group.1um/*.gz"], "output": str(out)}, remove=["group.1um"])
    assert (out / "group.1um/a.depth.tif").exists()
    assert not (root / "group.1um").exists()


def test_run_noop(tree):
    root, _ = tree
    before = sorted(root.rglob("*"))
    postprocess.run(str(root))
    assert sorted(root.rglob("*")) == before
