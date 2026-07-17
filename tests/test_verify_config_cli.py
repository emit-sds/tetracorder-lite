import shutil
from click.testing import CliRunner
from tetrapy.__main__ import cli
from tests.conftest import FIXTURES


def _make_cmds_dir(tmp_path):
    d = tmp_path / "tetracorder6.00a.cmds"
    (d / "DATASETS" / "restart_files").mkdir(parents=True)
    (d / "DELETED.channels").mkdir(parents=True)
    (d / "DATASETS" / "emit_c").write_text("data= EMITc\nrestart= r1-emitc\n")
    shutil.copy(FIXTURES / "r1-emitc", d / "DATASETS" / "restart_files" / "r1-emitc")
    (d / "DELETED.channels" / "delete_emit_c").write_text("1t4 280t285c  # emit_c\n")
    return d


def test_verify_config_ok(tmp_path):
    d = _make_cmds_dir(tmp_path)
    r = CliRunner().invoke(cli, ["verify-config", "--cmds-dir", str(d),
                                 "--sensor", "emit_c", "--nchans", "285"])
    assert r.exit_code == 0, r.output


def test_verify_config_bad_nchans(tmp_path):
    d = _make_cmds_dir(tmp_path)
    r = CliRunner().invoke(cli, ["verify-config", "--cmds-dir", str(d),
                                 "--sensor", "emit_c", "--nchans", "284"])
    assert r.exit_code != 0
