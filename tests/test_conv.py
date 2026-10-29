import numpy as np
import pytest

import synthetic
from tetrapy.conv import Convolver, SpecprFile, SpecprWriter, build_library, index_master, read_grid
from tetrapy.conv.library import CHAN_RECNO, FIRST_SPECTRUM, RES_RECNO, WAVE_RECNO, _convolved_title
from tetrapy.conv.specpr import DELETED, RECORD_BYTES


class TestSpecpr:
    @pytest.mark.parametrize("n", [10, 256, 257, 639, 640, 1000])
    def test_round_trip_across_continuations(self, tmp_path, n):
        values = np.linspace(0, 1, n, dtype=np.float32)
        w = SpecprWriter()
        recno = w.append_spectrum(values, "Test spectrum", itchan=n, irwav=6, irespt=12)
        w.append_pads(2)
        w.write(tmp_path / "lib")

        lib = SpecprFile.open(tmp_path / "lib")
        assert (tmp_path / "lib").stat().st_size == lib.nrecords * RECORD_BYTES
        assert list(lib.spectra()) == [recno]

        rec = lib.record(recno)
        assert rec.title == "Test spectrum"
        assert (rec.itchan, rec.irwav, rec.irespt) == (n, 6, 12)
        np.testing.assert_array_equal(lib.read_spectrum(recno), values)

    def test_label_record(self, tmp_path):
        SpecprWriter().write(tmp_path / "lib")
        assert (tmp_path / "lib").read_bytes().startswith(b"SPECPR_FS=2.0")

    def test_title_truncated_to_40(self, tmp_path):
        w = SpecprWriter()
        w.append_spectrum(np.zeros(3), "x" * 60, itchan=3)
        w.write(tmp_path / "lib")
        assert SpecprFile.open(tmp_path / "lib").record(1).title == "x" * 40

    def test_itchan_mismatch_raises(self):
        with pytest.raises(ValueError, match="expected 5 values"):
            SpecprWriter().append_spectrum(np.zeros(3), "t", itchan=5)

    def test_read_non_header_raises(self, tmp_path):
        w = SpecprWriter()
        w.append_pads(1)
        w.write(tmp_path / "lib")
        with pytest.raises(ValueError, match="not a data header"):
            SpecprFile.open(tmp_path / "lib").read_spectrum(1)

    def test_record_out_of_range(self, tmp_path):
        SpecprWriter().write(tmp_path / "lib")
        with pytest.raises(IndexError):
            SpecprFile.open(tmp_path / "lib").record(5)


class TestConvolver:
    wave = np.linspace(0.4, 2.5, 2101)
    fwhm = np.full(wave.size, 0.001)

    def test_flat_spectrum_stays_flat(self):
        out = Convolver(np.linspace(0.5, 2.4, 50), np.full(50, 0.01))
        res = out.convolve(self.wave, self.fwhm, np.full(self.wave.size, 0.42))
        np.testing.assert_allclose(res, 0.42, rtol=1e-5)

    def test_linear_spectrum_preserved(self):
        target = np.linspace(0.6, 2.3, 40)
        res = Convolver(target, np.full(40, 0.01)).convolve(self.wave, self.fwhm, self.wave)
        np.testing.assert_allclose(res, target, rtol=1e-4)

    def test_broadening_reduces_depth(self):
        spec = synthetic.absorption(self.wave, 1.5, 0.01, 0.5)
        narrow = Convolver([1.5], [0.005]).convolve(self.wave, self.fwhm, spec)[0]
        broad = Convolver([1.5], [0.05]).convolve(self.wave, self.fwhm, spec)[0]
        assert spec.min() < narrow < broad < synthetic.CONTINUUM

    def test_outside_native_range_is_deleted(self):
        res = Convolver([0.3, 1.0, 2.6], [0.01] * 3).convolve(self.wave, self.fwhm, np.ones(self.wave.size))
        assert res[0] == pytest.approx(DELETED, rel=1e-6)
        assert res[2] == pytest.approx(DELETED, rel=1e-6)
        assert res[1] == pytest.approx(1.0)

    def test_deleted_input_channels_ignored(self):
        spec = np.full(self.wave.size, 0.3)
        spec[1000:1010] = DELETED
        res = Convolver([self.wave[1005]], [0.01]).convolve(self.wave, self.fwhm, spec)
        assert res[0] == pytest.approx(0.3, rel=1e-5)

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="mismatch"):
            Convolver([1.0], [0.01]).convolve(self.wave, self.fwhm[:-1], self.wave)


class TestReadGrid:
    def test_nanometers_converted(self, scene):
        grid = read_grid(scene[0])
        np.testing.assert_allclose(grid.wavelengths, synthetic.SCENE_WAVE / 1000)
        np.testing.assert_allclose(grid.fwhm, synthetic.SCENE_FWHM / 1000)
        assert grid.nbands == synthetic.SCENE_WAVE.size

    def test_accepts_hdr_path_and_micron_units(self, tmp_path):
        hdr = tmp_path / "r.hdr"
        hdr.write_text(synthetic.envi_header((3, 1, 1), 4, [0.5, 1.0, 1.5], [0.01] * 3, units="Micrometers"))
        np.testing.assert_allclose(read_grid(hdr).wavelengths, [0.5, 1.0, 1.5])

    def test_missing_field_raises(self, tmp_path):
        (tmp_path / "r.hdr").write_text(synthetic.envi_header((3, 1, 1), 4, [500, 1000, 1500]))
        with pytest.raises(ValueError, match="fwhm"):
            read_grid(tmp_path / "r")

    def test_length_mismatch_raises(self, tmp_path):
        (tmp_path / "r.hdr").write_text(synthetic.envi_header((3, 1, 1), 4, [500, 1000, 1500], [10, 10]))
        with pytest.raises(ValueError, match="mismatch"):
            read_grid(tmp_path / "r")


@pytest.mark.parametrize("title, expected", [
    ("Acmite NMNH133746 Pyroxene   W1R1Ba AREF", "Acmite NMNH133746 Pyroxene s06tetra=a"),
    ("Kaolinite CM9 W5R4N___ AREF", "Kaolinite CM9 s06tetra=___"),
    ("Single", "Single"),
])
def test_convolved_title(title, expected):
    assert _convolved_title(title, "s06tetra") == expected


class TestBuildLibrary:
    def test_layout_and_content(self, tmp_path, scene):
        master = synthetic.write_master(
            tmp_path / "splib06b",
            synthetic.library_members("splib06"),
            extra=[("Orphan NOGRID W1R1Ba AREF", np.ones(17, dtype=np.float32))],
        )
        out = tmp_path / "conv"
        build_library(master, out, scene[0])

        lib = SpecprFile.open(out)
        nb = synthetic.SCENE_WAVE.size
        np.testing.assert_allclose(lib.read_spectrum(WAVE_RECNO), synthetic.SCENE_WAVE / 1000, rtol=1e-6)
        np.testing.assert_allclose(lib.read_spectrum(RES_RECNO), synthetic.SCENE_FWHM / 1000, rtol=1e-6)
        np.testing.assert_array_equal(lib.read_spectrum(CHAN_RECNO), np.arange(1, nb + 1))

        members = synthetic.library_members("splib06")
        expected = [WAVE_RECNO, RES_RECNO, CHAN_RECNO] + [
            synthetic.convolved_recno(k, nb) for k in range(len(members) + 1)  # + orphan
        ]
        assert list(lib.spectra()) == expected
        assert expected[3] == FIRST_SPECTRUM

        # Each mineral lands in its expected slot, family-tagged, with its absorption
        wave = synthetic.SCENE_WAVE / 1000
        for m in members:
            recno = synthetic.record_of(m)
            assert lib.record(recno).title.startswith(f"{m.name} SYN{m.index} s06tetra=a")
            spec = lib.read_spectrum(recno)
            assert wave[spec.argmin()] == pytest.approx(m.center, abs=0.02)
            assert spec.min() < synthetic.CONTINUUM * (1 - m.depth / 2)

        # The spectrum without a native grid is kept as an all-deleted placeholder
        orphan = synthetic.convolved_recno(len(members), nb)
        assert lib.record(orphan).title.startswith("Orphan")
        assert (lib.read_spectrum(orphan) < -1e30).all()

    def test_shipped_master_index(self):
        """The vendored master libraries index into spectra plus native grids."""
        master = synthetic.REPO / "tetracorder/sl1/usgs/library06.conv/sprlb06b"
        if not master.exists():
            pytest.skip("vendored sprlb06b not available")
        index = index_master(SpecprFile.open(master))
        assert index.spectra
        assert index.wave_by_channels and index.band_by_channels
