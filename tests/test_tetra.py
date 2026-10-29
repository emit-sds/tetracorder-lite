"""The setup/run drivers, against the synthetic command tree's stand-in scripts."""

import os
import subprocess

import pytest

import synthetic
from tetrapy import tetra


@pytest.fixture
def run_dir(tmp_path, tc_root, cmds, scene):
    # setup copies the sensor's restart/DISABLE files, so write them first
    (cmds / f"restart_files/r1-{synthetic.SENSOR}").write_text("restart")
    (cmds / f"DISABLE/{synthetic.SENSOR}").write_text("ENABLE  grp  1")

    out = tmp_path / "out"
    tetra.setup_tetrun(
        tetracorder=str(tc_root),
        version=synthetic.VERSION,
        output=str(out),
        sensor=synthetic.SENSOR,
        rfl=str(scene[0]),
        geology=False,
        cores=3,
        args=[],
    )
    return out


class TestSetup:
    def test_patches(self, run_dir):
        runtet = (run_dir / "cmd.runtet").read_text()
        assert "time" not in runtet
        assert "tetracorder.out" not in runtet
        assert "2>&1" in runtet

        assert (run_dir / "TETNCPU.txt").read_text() == "3"
        assert "nogeology\nmode cube" in (run_dir / f"cmds.start.t{synthetic.VERSION}").read_text()

    def test_geology_flag(self, tmp_path, tc_root, cmds, scene):
        (cmds / f"restart_files/r1-{synthetic.SENSOR}").write_text("restart")
        (cmds / f"DISABLE/{synthetic.SENSOR}").write_text("")
        out = tmp_path / "geo"
        tetra.setup_tetrun(str(tc_root), synthetic.VERSION, str(out), synthetic.SENSOR, rfl=str(scene[0]),
                           geology=True, args=[])
        text = (out / f"cmds.start.t{synthetic.VERSION}").read_text()
        assert "\ngeology\nmode" in text
        assert (out / "TETNCPU.txt").read_text() == str(os.cpu_count())

    def test_existing_output_cleared(self, tmp_path, tc_root, cmds, scene):
        (cmds / f"restart_files/r1-{synthetic.SENSOR}").write_text("restart")
        (cmds / f"DISABLE/{synthetic.SENSOR}").write_text("")
        out = tmp_path / "out"
        out.mkdir()
        (out / "stale").write_text("x")

        tetra.setup_tetrun(str(tc_root), synthetic.VERSION, str(out), synthetic.SENSOR, rfl=str(scene[0]), args=[])
        assert not (out / "stale").exists()

    def test_script_failure_raises(self, tmp_path, tc_root, scene):
        # No restart file for this sensor, so the stand-in script's cp fails
        with pytest.raises(subprocess.CalledProcessError):
            tetra.setup_tetrun(str(tc_root), synthetic.VERSION, str(tmp_path / "x"), "nosensor",
                               rfl=str(scene[0]), args=[])


class TestExec:
    def test_output_captured(self, run_dir, scene):
        (run_dir / "cmd.runtet").write_text('echo "running $1 $2"; echo "group 9 DISABLED"\n')
        tetra.exec_tetrun(output=str(run_dir), mode="cube", rfl=str(scene[0]), args=[])
        log = (run_dir / "tetracorder.out").read_text()
        assert f"running cube {scene[0]}" in log

    def test_davinci_stripped_from_path(self, run_dir, scene, monkeypatch):
        monkeypatch.setenv("PATH", "/opt/davinci/bin:" + os.environ["PATH"])
        (run_dir / "cmd.runtet").write_text('echo "PATH=$PATH"\n')

        tetra.exec_tetrun(output=str(run_dir), rfl=str(scene[0]), davinci=False, args=[])
        assert "davinci" not in (run_dir / "tetracorder.out").read_text()

        tetra.exec_tetrun(output=str(run_dir), rfl=str(scene[0]), davinci=True, args=[])
        assert "/opt/davinci/bin" in (run_dir / "tetracorder.out").read_text()

    def test_failure_raises(self, run_dir, scene):
        (run_dir / "cmd.runtet").write_text("exit 3\n")
        with pytest.raises(subprocess.CalledProcessError):
            tetra.exec_tetrun(output=str(run_dir), rfl=str(scene[0]), args=[])


class TestConvolve:
    def test_writes_both_libraries(self, tmp_path, tc_root, scene):
        libs = tc_root / "sl1/usgs/library06.conv"
        out_ref, out_res = tmp_path / "c/ref", tmp_path / "c/res"
        tetra.convolve(str(scene[0]), str(libs / "splib06b"), str(libs / "sprlb06b"), str(out_ref), str(out_res))
        assert out_ref.stat().st_size > 0
        assert out_res.stat().st_size > 0

    @pytest.mark.parametrize("which", ["reflib", "reslib"])
    def test_missing_library_raises(self, tmp_path, tc_root, scene, which):
        libs = tc_root / "sl1/usgs/library06.conv"
        kw = dict(reflib=str(libs / "splib06b"), reslib=str(libs / "sprlb06b"))
        kw[which] = str(tmp_path / "missing")
        with pytest.raises(FileNotFoundError):
            tetra.convolve(str(scene[0]), out_ref=str(tmp_path / "r"), out_res=str(tmp_path / "s"), **kw)
