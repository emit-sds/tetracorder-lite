import numpy as np
import pytest
from tetrapy.convolve import resolve_grid


def test_resolve_grid_from_tuple():
    wl = np.array([0.38, 0.39]); fwhm = np.array([0.008, 0.008])
    out_wl, out_fwhm = resolve_grid(envi_header=None, grid=(wl, fwhm))
    np.testing.assert_array_equal(out_wl, wl)
    np.testing.assert_array_equal(out_fwhm, fwhm)


def test_resolve_grid_requires_exactly_one():
    with pytest.raises(ValueError):
        resolve_grid(envi_header=None, grid=None)
    with pytest.raises(ValueError):
        resolve_grid(envi_header="x.hdr", grid=(np.array([1.0]), np.array([0.1])))
