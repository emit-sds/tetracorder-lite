"""
Stand-in for the tetracorder binary, invoked by the synthetic ``cmd.runtet``.

Run from inside a tetracorder output directory (as ``cmd.runtet`` is) with
``<mode> <rfl>``. It reads the same inputs real tetracorder does -- the expert system,
restart file (for the convolved library paths), and DISABLE file -- and writes the
outputs tetrapy consumes: per-material ``.depth.gz`` / ``.fit.gz`` ENVI rasters
under each group directory, a ``results.masses/*.png``, and a few intermediate
paths for the postprocess stage to prune.

The matching is a simplified tetracorder: continuum-remove each material's single
feature in both the observed and library spectra, least-squares scale the library
onto the observation, and within each group award every pixel to the passing
material with the highest fit * depth.
"""

import re
import sys
from pathlib import Path

import numpy as np
import rasterio
import xarray as xr

sys.path.insert(0, str(Path(__file__).parent))

from synthetic import write_envi  # noqa: E402
from tetrapy.conv import SpecprFile  # noqa: E402
from tetrapy.tetracorder import TetraDecoder  # noqa: E402


MIN_DEPTH = 0.02
MIN_FIT = 0.5


def continuum_removed(wave, spectra, continuum):
    a, b, c, d = continuum
    left = (wave >= a) & (wave <= b)
    right = (wave >= c) & (wave <= d)
    feature = (wave >= a) & (wave <= d)

    lx, rx = wave[left].mean(), wave[right].mean()
    ly, ry = spectra[..., left].mean(-1), spectra[..., right].mean(-1)

    slope = (ry - ly) / (rx - lx)
    cont = ly[..., None] + slope[..., None] * (wave[feature] - lx)
    return spectra[..., feature] / cont


def match(wave, obs, lib, continuum):
    """Per-pixel (fit, depth) of a library spectrum against observed spectra."""
    o = 1 - continuum_removed(wave, obs, continuum)    # (n, k) absorption profile
    l = 1 - continuum_removed(wave, lib, continuum)    # (k,)

    scale = (o @ l) / (l @ l)
    depth = scale * l.max()

    resid = o - scale[:, None] * l
    ss_tot = ((o - o.mean(-1, keepdims=True)) ** 2).sum(-1)
    fit = np.clip(1 - (resid ** 2).sum(-1) / np.where(ss_tot > 0, ss_tot, np.inf), 0, 1)

    return fit, depth


def main(mode, rfl):
    root = Path.cwd()

    restart = Path("r1").read_text()
    libs = {
        "sprlb06": SpecprFile.open(re.search(r"^iwfl=(\S+)", restart, re.M)[1]),
        "splib06": SpecprFile.open(re.search(r"^iyfl=(\S+)", restart, re.M)[1]),
    }

    enabled = {
        int(m[1])
        for m in re.finditer(r"^ENABLE\s+grp\s+(\d+)", Path("DISABLE").read_text(), re.M)
    }

    tc = TetraDecoder(root, groups=())

    with xr.open_dataset(rfl, engine="rasterio") as ds:
        cube = ds["band_data"].load()
    wave = cube.wavelength.data / 1000
    bands, lines, samples = cube.shape
    obs = cube.data.reshape(bands, -1).T                # (pixels, bands)

    print(f"fake tetracorder: mode={mode} rfl={rfl} {lines}x{samples}x{bands}")

    winners = {}
    for group in sorted(tc.groups):
        blocks = tc.get_groups([group])
        if group not in enabled:
            print(f"group {group} DISABLED, skipping {len(blocks)} materials")
            continue

        (root / tc.groups[group]).mkdir(parents=True, exist_ok=True)

        scores = []
        for block in blocks:
            lib = libs[block["library"]].read_spectrum(block["record"])
            fit, depth = match(wave, obs, lib, block["features"][0]["continuum"])
            ok = (fit > MIN_FIT) & (depth > MIN_DEPTH)
            scores.append((np.where(ok, fit * depth, 0), fit, depth))

        best = np.stack([s for s, _, _ in scores]).argmax(0)
        won = np.stack([s for s, _, _ in scores]).max(0) > 0
        winners[group] = np.where(won, best + 1, 0).reshape(lines, samples)

        for i, (block, (_, fit, depth)) in enumerate(zip(blocks, scores)):
            mine = won & (best == i)
            scale = block["data_type_scaling"]
            ddn = np.where(mine, np.clip(np.round(depth / scale * 255), 1, 255), 0)
            fdn = np.where(mine, np.clip(np.round(fit * 255), 1, 255), 0)

            base = root / block["path"]
            write_envi(f"{base}.depth.gz", ddn.reshape(lines, samples).astype(np.uint8), gz=True)
            write_envi(f"{base}.fit.gz", fdn.reshape(lines, samples).astype(np.uint8), gz=True)
            print(f"  group {group}: {block['id']} won {mine.sum()} pixels")

    # 8-bit quicklook, as the postprocess stage expects under results.masses/
    masses = root / "results.masses"
    masses.mkdir(exist_ok=True)
    for group, win in winners.items():
        with rasterio.open(
            masses / f"group{group}-winners.png", "w", driver="PNG",
            width=samples, height=lines, count=1, dtype="uint8",
        ) as dst:
            dst.write(win.astype(np.uint8), 1)

    # Bulky intermediates the default config prunes
    (root / "results.group1").mkdir(exist_ok=True)
    (root / "results.group1/list").write_text("intermediate\n")
    (root / "color.results-envi").write_text("intermediate\n")

    print("fake tetracorder: done")


if __name__ == "__main__":
    main(*sys.argv[1:3])
