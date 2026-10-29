import pandas as pd
import pytest

import synthetic
from tetrapy.tetracorder import TetraDecoder


SHIPPED = synthetic.REPO / f"tetracorder/tetracorder.cmds/tetracorder{synthetic.VERSION}.cmds"
REFERENCE = synthetic.REPO / "tetrapy/data/v6.00a6.csv"


@pytest.fixture
def decoder(cmds):
    # The command tree keeps variables under VARIABLES/; a run directory has them
    # alongside the expert system, which is what the decoder looks for.
    (cmds / "cmd.lib.setup.variables").write_text(synthetic.VARIABLES)
    return TetraDecoder(cmds)


class TestDecoder:
    def test_resolves_directory_to_expert_file(self, decoder, cmds):
        assert decoder.file == cmds / f"cmd.lib.setup.t{synthetic.VERSION}6"

    def test_group_paths_and_variables(self, decoder):
        assert decoder.groups == {1: "group.1um/", 2: "group.2um/", 3: "group.veg/"}
        assert decoder.vars["GLBLFITALL"] == "0.2 0.3"

    def test_default_groups_split(self, decoder):
        assert [b["id"] for b in decoder.blocks] == [m.id for m in synthetic.MINERALS if m.group in (1, 2)]
        assert [b["id"] for b in decoder.ignored] == [synthetic.VEG.id]

    def test_empty_groups_keeps_all(self, decoder):
        assert len(TetraDecoder(decoder.file, groups=()).blocks) == len(synthetic.MINERALS)

    def test_block_fields(self, decoder):
        m = synthetic.CALCITE
        block = next(b for b in decoder.blocks if b["id"] == m.id)

        assert block["group"] == 2
        assert block["use"] == "yes"
        assert block["library"] == "sprlb06"
        assert block["record"] == synthetic.record_of(m)
        assert block["name"] == m.name
        assert block["title"] == m.title
        assert block["filename"] == m.filename
        assert block["path"] == f"group.2um/{m.filename}"
        assert block["data_type_scaling"] == 0.5     # substituted from [DNSCALE]

        (feat,) = block["features"]
        assert feat["feature_type"] == "DLw"
        assert feat["continuum"] == list(m.continuum)
        assert feat["ct"] == [0.01]                  # substituted from [CTHRESH]
        assert feat["rcbblc<"] == [0.4, 0.5]

        assert block["constituent_constraints"] == {
            "FD-FIT": [0.3, 0.4],       # [GLBLFDFIT]
            "DEPTH-FIT": [0.5, 0.6],    # [GLBLDPFIT]
            "FITALL": [0.2, 0.3],       # [GLBLFITALL]
            "DEPTHALL": [0.02, 0.03],
        }

    def test_get_groups(self, decoder):
        assert {b["group"] for b in decoder.get_groups([2])} == {2}

    def test_table(self, decoder):
        df = decoder.table(groups=[1, 2, 3], columns=("id", "group"))
        assert list(df.columns) == ["id", "group"]
        assert len(df) == len(synthetic.MINERALS)

        rows = decoder.table(pandas=False)
        assert rows[0] == ("id", "group", "library", "record", "title", "path")

    def test_raise_casts(self, cmds):
        expert = cmds / f"cmd.lib.setup.t{synthetic.VERSION}6"
        expert.write_text(expert.read_text().replace("[DNSCALE]", "[UNDEFINED]", 1))

        with pytest.raises(ValueError):
            TetraDecoder(cmds)
        block = TetraDecoder(cmds, raise_casts=False).blocks[0]
        assert block["data_type_scaling"] == "[UNDEFINED]"


class TestExport:
    def test_export_with_reference(self, decoder, reference, tmp_path):
        out = tmp_path / "matrix.csv"
        decoder.export_csv(out, reference=reference, sortby=["group", "index"])

        df = pd.read_csv(out)
        assert df.columns[0] == "index"
        assert dict(zip(df["id"], df["index"])) == {m.id: m.index for m in synthetic.MINERALS if m.group in (1, 2)}

    def test_new_records_get_fresh_indices(self, decoder, tmp_path):
        ref = tmp_path / "ref.csv"
        known = synthetic.HEMATITE
        pd.DataFrame([{"Index": 7, "ID": known.id}]).to_csv(ref, index=False)  # legacy capitalized columns

        df = decoder.match_ref(ref)
        idx = dict(zip(df["id"], df["index"]))
        assert idx[known.id] == 7
        assert sorted(v for k, v in idx.items() if k != known.id) == [8, 9, 10]

    def test_clean_titles(self, decoder, reference):
        nu = decoder.table()
        nu["title"] = nu["title"] + " s06tetra=a extra"
        df = decoder.match_ref(reference, nu=nu, clean_titles=True)
        assert (df["title"] == decoder.table()["title"] + " extra").all()

    def test_no_records_in_reference(self, decoder, tmp_path):
        ref = tmp_path / "ref.csv"
        pd.DataFrame([{"index": 5, "id": "unrelated"}]).to_csv(ref, index=False)
        df = decoder.match_ref(ref)
        assert sorted(df["index"]) == [6, 7, 8, 9]

    def test_empty_reference(self, decoder, tmp_path):
        ref = tmp_path / "ref.csv"
        pd.DataFrame(columns=["index", "id"]).to_csv(ref, index=False)
        df = decoder.match_ref(ref)
        assert sorted(df["index"]) == [1, 2, 3, 4]

    def test_new_indices_skip_dropped_records(self, decoder, tmp_path):
        """A record dropped from the expert system keeps its index reserved."""
        ref = tmp_path / "ref.csv"
        pd.DataFrame([{"index": 1, "id": synthetic.HEMATITE.id}, {"index": 50, "id": "dropped"}]).to_csv(ref, index=False)
        idx = dict(zip(*decoder.match_ref(ref)[["id", "index"]].values.T))
        assert idx[synthetic.HEMATITE.id] == 1
        assert sorted(v for k, v in idx.items() if k != synthetic.HEMATITE.id) == [51, 52, 53]


@pytest.fixture(scope="module")
def shipped():
    return TetraDecoder(SHIPPED, raise_casts=False)


@pytest.mark.skipif(not SHIPPED.exists(), reason="vendored tetracorder command tree not available")
class TestShippedExpertSystem:
    """Guards that the packaged reference matrix stays in sync with the expert system."""

    def test_decodes_group_1_and_2(self, shipped):
        assert shipped.blocks
        assert {b["group"] for b in shipped.blocks} == {1, 2}
        for block in shipped.blocks:
            assert {"id", "library", "record", "path", "features"} <= set(block)
            assert block["library"] in ("splib06", "sprlb06")

    def test_ids_unique(self, shipped):
        ids = [b["id"] for b in shipped.blocks]
        assert len(ids) == len(set(ids))

    def test_reference_matrix_matches(self, shipped):
        ref = pd.read_csv(REFERENCE)
        assert ref["index"].is_unique
        assert set(ref["id"]) == {b["id"] for b in shipped.blocks}
