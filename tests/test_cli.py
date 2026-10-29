import logging

import click
import pytest
from click.testing import CliRunner

import synthetic
from tetrapy import utils
from tetrapy.__main__ import cli


@pytest.fixture
def runner():
    return CliRunner()


def test_version(runner):
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "version" in result.output


@pytest.mark.parametrize("cmd", ["run", "export-matrix", "convolve", "sensor", "setup", "tetrun",
                                 "postprocess", "aggregate", "preview"])
def test_subcommand_help(runner, cmd):
    result = runner.invoke(cli, [cmd, "--help"])
    assert result.exit_code == 0
    assert "CONFIG" in result.output


def test_preview_applies_overrides(runner, caplog):
    with caplog.at_level(logging.INFO):
        result = runner.invoke(cli, ["preview", str(synthetic.REPO / "config.yml"), "--output.base", "/elsewhere"])
    assert result.exit_code == 0, result.output
    assert "/elsewhere/aggregate/agg.nc" in caplog.text


@pytest.mark.parametrize("append, expected", [(False, "new\n"), (True, "old\nnew\n")])
def test_log_append(tmp_path, monkeypatch, append, expected):
    """``log.append: False`` resets the log file; ``True`` appends to it."""
    import tetrapy

    log = tmp_path / "tetrapy.log"
    log.write_text("old\n")
    config = tmp_path / "config.yml"
    config.write_text(f"log: {{file: {log}, append: {append}, config: null, level: INFO}}\n")

    # init() hands its handlers to basicConfig, which is a no-op once the root logger
    # has handlers (e.g. pytest's), so capture the file handler it builds instead
    handlers = []
    monkeypatch.setattr(tetrapy.logging, "basicConfig", lambda **kw: handlers.extend(kw["handlers"]))
    tetrapy.init(str(config), None, click.Context(cli))

    (fh,) = [h for h in handlers if isinstance(h, logging.FileHandler)]
    fh.setFormatter(logging.Formatter("%(message)s"))
    fh.emit(logging.makeLogRecord({"msg": "new"}))
    fh.close()

    assert log.read_text() == expected


def test_preview_noflow(runner, caplog):
    with caplog.at_level(logging.INFO):
        result = runner.invoke(cli, ["preview", str(synthetic.REPO / "config.yml"), "--noflow"])
    assert result.exit_code == 0, result.output

    # Scalar lists are condensed to flow style
    assert "groups: [1, 2]" in caplog.text
    assert "args: [band, '20', gif]" in caplog.text


def test_stage_disabled_steps_skipped(runner, tmp_path, monkeypatch):
    """``run`` only dispatches stages whose ``enabled`` flag is set."""
    from tetrapy import pipeline

    called = []
    for step in ("export_matrix", "convolve", "sensor", "setup", "tetrun", "postprocess", "aggregate"):
        monkeypatch.setitem(pipeline.__dict__, step, lambda c, step=step: called.append(step))

    config = tmp_path / "config.yml"
    config.write_text(
        f"output: {{tetracorder: {tmp_path}/tc, tetrapy: {tmp_path}/tp}}\n"
        "log: {file: null, config: null}\n"
        + "".join(f"{s}: {{enabled: {s in ('convolve', 'aggregate')}}}\n"
                  for s in ("export_matrix", "convolve", "sensor", "setup", "tetrun", "postprocess", "aggregate"))
    )
    (tmp_path / "tc").mkdir()
    (tmp_path / "tp").mkdir()

    result = runner.invoke(cli, ["run", str(config)])
    assert result.exit_code == 0, result.output
    assert called == ["convolve", "aggregate"]


@pytest.mark.parametrize("args, expected", [
    (["cmd", "sub"], "cmd sub"),
    (["cmd", "sub", "--opt", "val", "--flag", "pos"],
     "cmd sub \\\n  --opt val \\\n  --flag pos"),
])
def test_format_args(args, expected):
    # rstrip: format_args leaves the space that preceded the final dropped backslash
    assert utils.format_args(args).rstrip() == expected


def test_log_elapse(caplog):
    @utils.log_elapse
    def double(x):
        """Doc."""
        return x * 2

    with caplog.at_level(logging.DEBUG, logger="tetrapy.utils"):
        assert double(4) == 8
    assert double.__name__ == "double" and double.__doc__ == "Doc."
    assert "Beginning double" in caplog.text
    assert "Finished double" in caplog.text
