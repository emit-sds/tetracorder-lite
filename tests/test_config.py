import logging

import pytest
from box import Box

import synthetic
from tetrapy import config


@pytest.fixture
def write_yaml(tmp_path):
    def write(text, name="config.yml"):
        path = tmp_path / name
        path.write_text(text)
        return str(path)
    return write


class TestInterpolate:
    def test_absolute_reference(self):
        c = config.interpolate(Box({"a": {"b": "x"}, "c": "${a.b}/y"}))
        assert c.c == "x/y"

    def test_relative_reference(self):
        c = config.interpolate(Box({"sect": {"base": "/out", "path": "${.base}/file"}}))
        assert c.sect.path == "/out/file"

    def test_chained_references(self):
        c = config.interpolate(Box({"a": "/root", "b": "${a}/b", "c": "${b}/c"}))
        assert c.c == "/root/b/c"

    def test_references_inside_lists(self):
        c = config.interpolate(Box({"a": "x", "l": ["${a}", "lit", ["${a}1"]]}))
        assert c.l == ["x", "lit", ["x1"]]

    def test_fully_substituted_value_parses_as_literal(self):
        c = config.interpolate(Box({"n": 5, "m": "${n}", "flag": True, "f": "${flag}"}))
        assert c.m == 5
        assert c.f is True

    def test_missing_reference_raises(self):
        with pytest.raises(KeyError, match="not found"):
            config.interpolate(Box({"a": "${missing}"}))

    def test_circular_reference_raises(self):
        with pytest.raises(ValueError, match="Circular"):
            config.interpolate(Box({"a": "${b}", "b": "${a}"}))

    def test_strings_without_references_untouched(self):
        c = config.interpolate(Box({"a": "plain", "b": "[not, parsed]"}))
        assert c.a == "plain"
        assert c.b == "[not, parsed]"


class TestOverride:
    def test_nested_dotted_key(self):
        c = config.override(Box({"a": {"b": 1}}), ["--a.b", "2"])
        assert c.a.b == 2

    def test_creates_new_keys(self):
        c = config.override(Box({}), ["--x.y.z", "v"])
        assert c.x.y.z == "v"

    @pytest.mark.parametrize("raw, expected", [
        ("10", 10),
        ("1.5", 1.5),
        ("True", True),
        ("None", None),
        ('["band", 10]', ["band", 10]),
        ("hello", "hello"),
        ("/data/path", "/data/path"),
    ])
    def test_value_parsing(self, raw, expected):
        c = config.override(Box({"k": "old"}), ["--k", raw])
        assert c.k == expected

    def test_none_replaces_existing_value(self):
        c = config.override(Box({"log": {"file": "/x.log"}}), ["--log.file", "None"])
        assert c.log.file is None

    def test_bare_flags_are_true(self):
        c = config.override(Box({}), ["--a", "--b", "val", "--c"])
        assert c.a is True and c.b == "val" and c.c is True

    def test_malformed_literal_warns_and_falls_back_to_string(self, caplog):
        with caplog.at_level(logging.WARNING, logger="tetrapy.config"):
            c = config.override(Box({}), ["--k", "[1, 2"])
        assert c.k == "[1, 2"
        assert "Could not parse" in caplog.text

    def test_non_flag_args_ignored(self):
        c = config.override(Box({"a": 1}), ["positional", "--a", "2"])
        assert c.a == 2


class TestPatch:
    def test_single_parent(self):
        full = Box({"base": {"x": 1, "y": 1}, "child": {"^^": "base", "y": 2}}, default_box=True)
        c = config.patch(full.child, full)
        assert c.to_dict() == {"x": 1, "y": 2}

    def test_precedence_across_parents(self):
        full = Box({
            "D": {"k": "D", "d": 1},
            "B": {"^^": "D", "k": "B", "b": 1},
            "C": {"k": "C", "c": 1},
            "A": {"^^": ["B", "C"], "a": 1},
        }, default_box=True)
        c = config.patch(full.A, full)
        assert c.k == "C"
        assert {"a", "b", "c", "d"} <= set(c)

    def test_unknown_section_raises(self):
        full = Box({"A": {"^^": "nope"}}, default_box=True)
        with pytest.raises(KeyError, match="unknown section"):
            config.patch(full.A, full)

    def test_circular_reference_raises(self):
        full = Box({"A": {"^^": "B"}, "B": {"^^": "C"}, "C": {"^^": "B"}}, default_box=True)
        with pytest.raises(ValueError, match="Circular"):
            config.patch(full.A, full)


class TestLoad:
    def test_section_with_patch_and_interp(self, write_yaml):
        path = write_yaml(
            "defaults:\n"
            "  out: /out\n"
            "  file: ${.out}/f.txt\n"
            "run:\n"
            "  ^^: defaults\n"
            "  out: /custom\n"
        )
        c = config.load(path, section="run")
        assert c.out == "/custom"
        assert c.file == "/custom/f.txt"

    def test_override_applied_before_interpolation(self, write_yaml):
        path = write_yaml("base: /a\nfile: ${base}/f\n")
        c = config.load(path, ctx=["--base", "/b"])
        assert c.file == "/b/f"

    def test_no_interp(self, write_yaml):
        c = config.load(write_yaml("a: x\nb: ${a}\n"), interp=False)
        assert c.b == "${a}"

    def test_repo_config_resolves(self):
        c = config.load(str(synthetic.REPO / "config.yml"))
        assert c.output.tetracorder == "/output/test/tetracorder"
        assert c.aggregate.out_min == "/output/test/aggregate/agg.nc"
        assert c.sensor.reflib == "/conv/reflib"
        assert c.tetracorder.sensor == c.sensor.name
