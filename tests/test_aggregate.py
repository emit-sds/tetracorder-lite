import logging

import numpy as np
import pandas as pd
import pytest
import rasterio
import xarray as xr

import synthetic
from tetrapy import aggregate
from tetrapy.tetracorder import TetraDecoder


SHAPE = synthetic.SCENE_SHAPE


@pytest.fixture
def run_dir(cmds):
    """A tetracorder output directory: the command tree with variables alongside."""
    (cmds / "cmd.lib.setup.variables").write_text(synthetic.VARIABLES)
    return cmds


def write_outputs(root, mineral, depth_dn, fit_dn=None):
    """Write a block's ``.depth.gz`` / ``.fit.gz`` rasters (8-bit DN)."""
    base = root / synthetic.GROUP_DIRS[mineral.group] / mineral.filename
    synthetic.write_envi(f"{base}.depth.gz", np.asarray(depth_dn, dtype=np.uint8), gz=True)
    if fit_dn is not None:
        synthetic.write_envi(f"{base}.fit.gz", np.asarray(fit_dn, dtype=np.uint8), gz=True)


def mask(cols):
    m = np.zeros(SHAPE, dtype=np.uint8)
    m[:, cols] = 1
    return m


class TestAggregateGroup:
    def test_composites_winners(self, run_dir, reference):
        write_outputs(run_dir, synthetic.KAOLINITE, mask(slice(0, 2)) * 100, mask(slice(0, 2)) * 200)
        write_outputs(run_dir, synthetic.CALCITE, mask(slice(4, 6)) * 50, mask(slice(4, 6)) * 150)

        tc = TetraDecoder(run_dir)
        mins, unc = aggregate.aggregate(tc, 2, ref=pd.read_csv(reference))

        assert mins["group_2_band_depth"].dims == ("downtrack", "crosstrack")

        ids = mins["group_2_mineral_id"].values
        np.testing.assert_array_equal(ids[:, 0:2], synthetic.KAOLINITE.index)
        np.testing.assert_array_equal(ids[:, 4:6], synthetic.CALCITE.index)
        assert (ids[:, 2:4] == 0).all() and (ids[:, 6:] == 0).all()

        depth = mins["group_2_band_depth"].values
        np.testing.assert_allclose(depth[:, 0], 100 / 255 * 0.5)
        np.testing.assert_allclose(depth[:, 4], 50 / 255 * 0.5)

        fit = unc["group_2_fit"].values
        np.testing.assert_allclose(fit[:, 0], 200 / 255 * 0.5)

        # No libraries -> no uncertainty calculated
        assert (unc["group_2_band_depth_unc"] == 0).all()

    def test_running_index_without_reference(self, run_dir):
        write_outputs(run_dir, synthetic.CALCITE, mask(slice(0, 1)) * 10, mask(slice(0, 1)) * 10)
        mins, _ = aggregate.aggregate(TetraDecoder(run_dir), 2)
        assert (mins["group_2_mineral_id"].values[:, 0] == 2).all()   # second block in group 2

    def test_missing_reference_entry_gets_negative_id(self, run_dir, tmp_path, caplog):
        write_outputs(run_dir, synthetic.CALCITE, mask(slice(0, 1)) * 10, mask(slice(0, 1)) * 10)
        ref = pd.DataFrame([{"index": 1, "id": "other", "title": "Other"}])

        with caplog.at_level(logging.WARNING, logger="tetrapy.aggregate"):
            mins, _ = aggregate.aggregate(TetraDecoder(run_dir), 2, ref=ref)

        assert (mins["group_2_mineral_id"].values[:, 0] == -2).all()
        assert "does not contain an index" in caplog.text

    def test_no_winners_yields_zeros(self, run_dir, caplog):
        zeros = np.zeros(SHAPE)
        write_outputs(run_dir, synthetic.KAOLINITE, zeros, zeros)
        write_outputs(run_dir, synthetic.CALCITE, zeros, zeros)

        with caplog.at_level(logging.WARNING, logger="tetrapy.aggregate"):
            mins, unc = aggregate.aggregate(TetraDecoder(run_dir), 2)

        assert mins is not None
        assert (mins["group_2_mineral_id"] == 0).all()
        assert "none had a winning pixel" in caplog.text

    def test_no_output_returns_none(self, run_dir, caplog):
        with caplog.at_level(logging.ERROR, logger="tetrapy.aggregate"):
            assert aggregate.aggregate(TetraDecoder(run_dir), 2) == (None, None)
        assert "no depth raster could be read" in caplog.text

    def test_missing_fit_skips_block(self, run_dir):
        write_outputs(run_dir, synthetic.KAOLINITE, mask(slice(0, 2)) * 100)
        mins, _ = aggregate.aggregate(TetraDecoder(run_dir), 2)
        assert mins is None


class TestBuild:
    def test_borrows_grid_for_empty_group(self, run_dir, tmp_path):
        write_outputs(run_dir, synthetic.HEMATITE, mask(slice(0, 2)) * 100, mask(slice(0, 2)) * 100)

        out_min, out_unc = tmp_path / "agg.nc", tmp_path / "unc.tif"
        mins, unc = aggregate.build(str(run_dir), out_min=str(out_min), out_minuncert=str(out_unc))

        assert set(mins.data_vars) == {"group_1_band_depth", "group_1_mineral_id",
                                       "group_2_band_depth", "group_2_mineral_id"}
        assert set(unc.data_vars) == {"group_1_band_depth_unc", "group_1_fit",
                                      "group_2_band_depth_unc", "group_2_fit"}
        assert (mins["group_2_mineral_id"] == 0).all()

        with xr.open_dataset(out_min) as ds:
            assert set(ds.data_vars) == set(mins.data_vars)
        with rasterio.open(out_unc) as src:
            assert src.count == 4
            assert (src.height, src.width) == SHAPE

    def test_no_output_raises(self, run_dir):
        with pytest.raises(RuntimeError, match="Neither group"):
            aggregate.build(str(run_dir))


class TestSave:
    @pytest.fixture
    def ds(self):
        da = xr.DataArray(np.ones(SHAPE), dims=("downtrack", "crosstrack"))
        return xr.Dataset({"a": da, "b": da * 2})

    def test_netcdf(self, ds, tmp_path):
        aggregate.save(ds, tmp_path / "sub/out.nc")
        with xr.open_dataset(tmp_path / "sub/out.nc") as out:
            xr.testing.assert_equal(out, ds)

    def test_geotiff_band_names(self, ds, tmp_path):
        aggregate.save(ds, tmp_path / "out.tif")
        with rasterio.open(tmp_path / "out.tif") as src:
            assert src.descriptions == ("a", "b")

    def test_unknown_extension_skipped(self, ds, tmp_path, caplog):
        with caplog.at_level(logging.ERROR, logger="tetrapy.aggregate"):
            aggregate.save(ds, tmp_path / "out.zarr")
        assert not (tmp_path / "out.zarr").exists()
        assert "unrecognized" in caplog.text


class TestUncertainty:
    wl = np.linspace(2.0, 2.5, 101)

    def test_get_continuum_idx(self):
        valid = np.ones(self.wl.size, dtype=bool)
        left, right = aggregate.get_continuum_idx(self.wl, (2.1, 2.12, 2.3, 2.32), valid)
        assert self.wl[left].min() >= 2.1 and self.wl[left].max() <= 2.12
        assert self.wl[right].min() >= 2.3 and self.wl[right].max() <= 2.32

    def test_get_continuum_idx_fallback_to_nearest(self):
        valid = np.ones(self.wl.size, dtype=bool)
        valid[(self.wl >= 2.1) & (self.wl <= 2.12)] = False
        left, _ = aggregate.get_continuum_idx(self.wl, (2.1, 2.12, 2.3, 2.32), valid)
        assert left.size == 1 and self.wl[left[0]] >= 2.12

    def test_get_continuum_idx_none(self):
        valid = np.zeros(self.wl.size, dtype=bool)
        assert aggregate.get_continuum_idx(self.wl, (2.6, 2.7, 2.8, 2.9), valid) is None

    def test_cont_rem_flat_is_zero(self):
        rfl = np.full((3, self.wl.size), 0.4)
        valid = np.ones(self.wl.size, dtype=bool)
        idx = aggregate.get_continuum_idx(self.wl, (2.1, 2.12, 2.3, 2.32), valid)
        depths, bands = aggregate.cont_rem(self.wl, rfl, idx, valid)
        np.testing.assert_allclose(depths, 0, atol=1e-12)
        assert self.wl[bands].min() >= 2.1 and self.wl[bands].max() <= 2.32

    def test_calculate_uncertainty_scales_with_sigma(self):
        lib = synthetic.absorption(self.wl, 2.2, 0.04, 0.3)
        rfl = np.tile(lib, (4, 1))
        features = [{"feature_type": "DLw", "continuum": [2.08, 2.11, 2.27, 2.30]},
                    {"feature_type": "OLw", "continuum": [2.0, 2.01, 2.4, 2.41]}]

        u1 = aggregate.calculate_uncertainty(self.wl, rfl, np.full_like(rfl, 0.01), lib, features)
        u2 = aggregate.calculate_uncertainty(self.wl, rfl, np.full_like(rfl, 0.02), lib, features)

        assert u1.shape == (4,)
        assert (u1 > 0).all()
        np.testing.assert_allclose(u2, 2 * u1)

    def test_calculate_uncertainty_no_usable_features(self):
        rfl = np.ones((2, self.wl.size))
        features = [{"feature_type": "OLw", "continuum": [2.0, 2.01, 2.4, 2.41]}]
        np.testing.assert_array_equal(
            aggregate.calculate_uncertainty(self.wl, rfl, rfl, rfl[0], features), [0, 0]
        )
