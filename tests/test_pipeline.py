"""
End-to-end run of ``tetrapy run`` on synthetic data.

Every stage runs for real except the tetracorder binary itself, which only exists
inside the container: the synthetic ``cmd-setup-tetrun`` writes a ``cmd.runtet``
that calls ``fake_tetracorder.py`` instead. The scene has known minerals planted in
known pixels, so the final L2B products can be checked against the truth.
"""

import re

import numpy as np
import pandas as pd
import pytest
import rasterio
import xarray as xr
from box import Box
from click.testing import CliRunner

import synthetic
from tetrapy.__main__ import cli
from tetrapy.conv import SpecprFile


def make_config(tmp_path, tc_root, scene, glt, reference):
    rfl, rfluncert = scene
    return {
        "output": {
            "base": str(tmp_path / "output"),
            "tetracorder": "${output.base}/tetracorder",
            "tetrapy": "${output.base}/aggregate",
        },
        "data": {"rfl": str(rfl), "rfluncert": str(rfluncert), "glt": str(glt)},
        "tetracorder": {
            "root": str(tc_root),
            "davinci": False,
            "version": synthetic.VERSION,
            "sensor": "${sensor.name}",
            "mode": "cube",
        },
        "log": {
            "level": "DEBUG",
            "file": "${output.tetrapy}/tetrapy.log",
            "append": False,
            "config": "${output.tetrapy}/config.yml",
        },
        "export_matrix": {
            "enabled": True,
            "file": "${output.tetrapy}/matrix.csv",
            "groups": [1, 2],
            "columns": ["id", "group", "library", "record", "title", "path"],
            "reference": str(reference),
            "sortby": ["group", "index"],
            "clean_titles": True,
        },
        "convolve": {
            "enabled": True,
            "reflib": "${tetracorder.root}/sl1/usgs/library06.conv/splib06b",
            "reslib": "${tetracorder.root}/sl1/usgs/library06.conv/sprlb06b",
            "output": {
                "reflib": str(tmp_path / "conv/reflib"),
                "reslib": str(tmp_path / "conv/reslib"),
            },
        },
        "sensor": {
            "enabled": True,
            "name": synthetic.SENSOR,
            "deleted_channels": "1t4 283t285",
            "enable": {"groups": ["1-2"], "cases": ["1-6"]},
            "colors": ["BASE 23 23 23 base-image.jpg"],
            "reflib": "${convolve.output.reflib}",
            "reslib": "${convolve.output.reslib}",
        },
        "setup": {"enabled": True, "geology": False, "args": ["1", "-T", "-20", "80", "C"]},
        "tetrun": {"enabled": True, "args": ["band", "20", "gif"]},
        "postprocess": {
            "enabled": True,
            "tetracorder": "${output.tetracorder}",
            "cogs": {
                "output": "${output.tetrapy}/cogs/",
                "skip_existing": False,
                "glt": "${data.glt}",
                "glob": ["results.masses/*.png", "group.*/*.depth.gz"],
            },
            "remove": ["results.group*", "color.results-envi"],
        },
        "aggregate": {
            "enabled": True,
            "tetracorder": "${output.tetracorder}",
            "reflib": "${convolve.output.reflib}",
            "reslib": "${convolve.output.reslib}",
            "out_min": "${output.tetrapy}/agg.nc",
            "out_minuncert": "${output.tetrapy}/agg-uncert.tif",
            "reference": str(reference),
        },
    }


@pytest.fixture(scope="module")
def pipeline_run(tmp_path_factory):
    """Run the full pipeline once through the CLI and return the output paths."""
    tmp_path = tmp_path_factory.mktemp("pipeline")
    tc_root = synthetic.write_tetracorder_root(tmp_path / "tetracorder")
    scene = synthetic.write_scene(tmp_path / "data")
    glt = synthetic.write_glt(tmp_path / "data/glt")
    reference = synthetic.write_reference(tmp_path / "reference.csv")

    config = tmp_path / "config.yml"
    Box(make_config(tmp_path, tc_root, scene, glt, reference)).to_yaml(filename=config)

    with pytest.MonkeyPatch.context() as mp:
        synthetic.use_fake_tetracorder(mp)
        result = CliRunner().invoke(cli, ["run", str(config)], catch_exceptions=False)
    assert result.exit_code == 0, result.output

    out = tmp_path / "output"
    return {
        "tetracorder": out / "tetracorder",
        "tetrapy": out / "aggregate",
        "conv": tmp_path / "conv",
        "cmds": synthetic.cmd_tree(tc_root),
    }


def test_pipeline_recovers_planted_minerals(pipeline_run):
    with xr.open_dataset(pipeline_run["tetrapy"] / "agg.nc") as ds:
        mins = ds.load()

    truth = synthetic.truth()
    for group in (1, 2):
        ids = mins[f"group_{group}_mineral_id"].values.astype(int)
        np.testing.assert_array_equal(ids, truth[group], err_msg=f"group {group} mineral ids")

        depth = mins[f"group_{group}_band_depth"].values
        assert (depth[truth[group] > 0] > 0).all()
        assert (depth[truth[group] == 0] == 0).all()

    # Planted depths are 0.30 (hematite) / 0.35 (kaolinite, calcite); allow for
    # convolution smoothing and 8-bit quantization
    depth1 = mins["group_1_band_depth"].values[truth[1] > 0]
    depth2 = mins["group_2_band_depth"].values[truth[2] > 0]
    assert np.allclose(depth1, 0.30, atol=0.08)
    assert np.allclose(depth2, 0.35, atol=0.08)


def test_pipeline_uncertainty_product(pipeline_run):
    truth = synthetic.truth()
    with rasterio.open(pipeline_run["tetrapy"] / "agg-uncert.tif") as src:
        names = src.descriptions
        data = src.read()

    assert set(names) == {"group_1_band_depth_unc", "group_1_fit", "group_2_band_depth_unc", "group_2_fit"}
    bands = dict(zip(names, data))
    for group in (1, 2):
        unc = bands[f"group_{group}_band_depth_unc"]
        fit = bands[f"group_{group}_fit"]
        mapped = truth[group] > 0

        assert np.isfinite(unc).all()
        assert (unc[mapped] > 0).all() and (unc[~mapped] == 0).all()
        assert (fit[mapped] > 0).all() and (fit[~mapped] == 0).all()


def test_pipeline_convolved_libraries(pipeline_run):
    for name, lib in (("reflib", "splib06"), ("reslib", "sprlb06")):
        conv = SpecprFile.open(pipeline_run["conv"] / name)
        for mineral in synthetic.library_members(lib):
            rec = conv.record(synthetic.record_of(mineral))
            assert rec.title.startswith(mineral.name)
            assert rec.itchan == synthetic.SCENE_WAVE.size


def test_pipeline_sensor_files(pipeline_run):
    cmds, name = pipeline_run["cmds"], synthetic.SENSOR

    restart = (cmds / f"restart_files/r1-{name}").read_text()
    assert f"nchans= {synthetic.SCENE_WAVE.size}" in restart
    assert str(pipeline_run["conv"] / "reflib") in restart

    disable = (cmds / f"DISABLE/{name}").read_text().splitlines()
    assert "ENABLE  grp  1" in disable
    assert "ENABLE  grp  2" in disable
    assert "DISABLE grp  3" in disable

    assert (cmds / f"DELETED.channels/delete_{name}").read_text().startswith("1t4 283t285")


def test_pipeline_setup_and_tetrun(pipeline_run):
    out = pipeline_run["tetracorder"]

    runtet = (out / "cmd.runtet").read_text()
    assert not re.search(r"^\s*time\s", runtet, re.MULTILINE)
    assert "> tetracorder.out" not in runtet

    log = (out / "tetracorder.out").read_text()
    assert "fake tetracorder: done" in log
    assert "group 3 DISABLED" in log

    # Disabled group 3 produced nothing
    assert not (out / "group.veg").exists()


def test_pipeline_postprocess(pipeline_run):
    out, cogs = pipeline_run["tetracorder"], pipeline_run["tetrapy"] / "cogs"

    # Pruned
    assert not (out / "results.group1").exists()
    assert not (out / "color.results-envi").exists()

    # Converted and orthorectified onto the GLT grid (one-pixel fill border)
    png = cogs / "results.masses/group1-winners.tif"
    depth = cogs / f"group.1um/{synthetic.HEMATITE.filename}.depth.tif"
    for path in (png, depth):
        with rasterio.open(path) as src:
            assert src.crs is not None and src.crs.to_epsg() == 4326
            assert (src.height, src.width) == tuple(n + 2 for n in synthetic.SCENE_SHAPE)
            assert src.nodata == 0

    # The GLT mirrors left-to-right, so the planted hematite columns move
    with rasterio.open(png) as src:
        winners = src.read(1)[1:-1, 1:-1]
    expected = np.fliplr(synthetic.truth()[1] > 0)
    np.testing.assert_array_equal(winners > 0, expected)


def test_pipeline_exports(pipeline_run):
    out = pipeline_run["tetrapy"]

    matrix = pd.read_csv(out / "matrix.csv")
    expected = {m.id: m.index for m in synthetic.MINERALS if m.group in (1, 2)}
    assert dict(zip(matrix["id"], matrix["index"])) == expected
    assert list(matrix.columns[:1]) == ["index"]

    # The resolved config is exported with interpolation applied
    config = Box.from_yaml(filename=out / "config.yml")
    assert config["aggregate"]["out_min"] == str(out / "agg.nc")
