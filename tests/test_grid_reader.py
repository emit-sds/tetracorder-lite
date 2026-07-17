import numpy as np
import pytest
from tetrapy.convolve import read_wavelengths_fwhm_txt
from tests.conftest import FIXTURES


def test_reads_nm_and_converts_to_microns():
    wl, fwhm = read_wavelengths_fwhm_txt(
        FIXTURES / "emit_wl_test.txt", FIXTURES / "emit_fwhm_test.txt"
    )
    assert wl.shape == (3,) and fwhm.shape == (3,)
    np.testing.assert_allclose(wl[0], 0.38085787, rtol=1e-6)
    np.testing.assert_allclose(fwhm[0], 0.008415, rtol=1e-6)


def test_microns_units_no_conversion():
    wl, _ = read_wavelengths_fwhm_txt(
        FIXTURES / "emit_wl_test.txt", FIXTURES / "emit_fwhm_test.txt", units="microns"
    )
    np.testing.assert_allclose(wl[0], 380.85787, rtol=1e-6)


def test_length_mismatch_raises(tmp_path):
    wl = tmp_path / "wl.txt"; wl.write_text("1.0\n2.0\n")
    fwhm = tmp_path / "fwhm.txt"; fwhm.write_text("0.1\n")
    with pytest.raises(ValueError):
        read_wavelengths_fwhm_txt(wl, fwhm)
