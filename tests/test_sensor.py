import pytest
from box import Box

import synthetic
from tetrapy import sensor
from tetrapy.conv.specpr import RECORD_BYTES


@pytest.mark.parametrize("vals, expected", [
    (["1-5", 18, "20-22"], [1, 2, 3, 4, 5, 18, 20, 21, 22]),
    ([3], [3]),
    (["7-7"], [7]),
    ([], []),
])
def test_parse_list(vals, expected):
    assert sensor.parse_list(vals) == expected


@pytest.fixture
def libs(tmp_path):
    ref = tmp_path / "conv/reflib"
    res = tmp_path / "conv/reslib"
    ref.parent.mkdir()
    ref.write_bytes(bytes(RECORD_BYTES * 10))
    res.write_bytes(bytes(RECORD_BYTES * 4))
    return ref, res


@pytest.fixture
def config(libs):
    ref, res = libs
    return Box({
        "name": "mysensor",
        "deleted_channels": "1t4 280t285",
        "enable": {"groups": ["1-2"], "cases": [1, 3]},
        "colors": ["BASE 23 23 23 base.jpg", "COLOR1 38 23 11 rgb.jpg"],
        "reflib": str(ref),
        "reslib": str(res),
    })


def test_build_writes_all_sensor_files(cmds, scene, config, libs):
    sensor.build(cmds, config, scene[0])
    ref, res = libs

    restart = (cmds / "restart_files/r1-mysensor").read_text()
    assert f"iyfl={ref}" in restart
    assert f"iwfl={res}" in restart
    assert "irfl=r1-mysensor" in restart
    assert f"nchans= {synthetic.SCENE_WAVE.size}" in restart
    assert "iprty= -9" in restart     # -(records - 1)
    assert "iprtw= -3" in restart
    assert "inmy=       reflib" in restart

    assert (cmds / "DELETED.channels/delete_mysensor").read_text() == "1t4 280t285 c # mysensor"
    assert (cmds / "DATASETS/mysensor").read_text() == "data=    mysensor\nrestart= r1-mysensor"
    assert (cmds / "COLOR.channels/color-mysensor").read_text() == "\n".join(config.colors)

    disable = (cmds / "DISABLE/mysensor").read_text().splitlines()
    assert disable == [
        "ENABLE  grp  1",
        "ENABLE  grp  2",
        "DISABLE grp  3",
        "ENABLE  cse  1",
        "DISABLE cse  2",
        "ENABLE  cse  3",
        "DISABLE cse  4",
        "DISABLE cse  5",
        "DISABLE cse  6",
        "DISABLE cse  7",
    ]


@pytest.mark.parametrize("missing", ["reflib", "reslib"])
def test_build_missing_library_raises(cmds, scene, config, missing):
    config[missing] = "/does/not/exist"
    with pytest.raises(FileNotFoundError, match="library not found"):
        sensor.build(cmds, config, scene[0])
