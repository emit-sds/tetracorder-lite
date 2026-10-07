"""
Render a quicklook of a whole granule with the demo's window drawn on it.

The demo runs on a 300x150 crop, which is easy to mistake for the size of an
EMIT product. This produces the picture that puts it in proportion: the full
granule, with the subset outlined where it was actually cut from.

Run at development time, not in the codespace -- the full granule is 1.8 GB per
cube and is never downloaded there. The result is committed under
.devcontainer/page/ and served alongside the results.

    python make_context_image.py in/emit20250327t212148_rfl \
        .devcontainer/page/full-scene.jpg --line 565 --sample 471
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

from make_subset import memmap_cube, read_hdr

NODATA = -9999


def stretch(band: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Linear 2-98 percentile stretch to [0, 1], invalid pixels at 0."""
    if not valid.any():
        return np.zeros_like(band)
    lo, hi = np.percentile(band[valid], (2, 98))
    if hi <= lo:
        return np.zeros_like(band)
    return np.clip((band - lo) / (hi - lo), 0, 1) * valid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("rfl", type=Path, help="full granule reflectance (the data, not the .hdr)")
    parser.add_argument("out", type=Path, help="PNG to write")
    parser.add_argument("--line", type=int, default=565)
    parser.add_argument("--sample", type=int, default=471)
    parser.add_argument("--height", type=int, default=200)
    parser.add_argument("--width-px", dest="win_w", type=int, default=300)
    parser.add_argument("--width", type=int, default=700, help="target width in pixels")
    args = parser.parse_args()

    fields = read_hdr(Path(f"{args.rfl}.hdr"))
    cube = memmap_cube(args.rfl, fields)          # (lines, bands, samples)
    wl = np.array([float(v) for v in fields["wavelength"].strip("{}").split(",")])
    lines, _, samples = cube.shape

    # Only three bands are needed, and the cube is far too big to hold. Stride
    # rather than average: this is a locator image, not a measurement.
    # ceil, not floor: floor gives a stride of 1 whenever the granule is less
    # than twice the target width, which is no downsampling at all.
    step = max(1, -(-samples // args.width))
    idx = [int(np.argmin(abs(wl - t))) for t in (640.0, 550.0, 470.0)]
    planes = [np.asarray(cube[::step, i, ::step], dtype=np.float32) for i in idx]

    valid = (planes[0] != NODATA) & np.isfinite(planes[0])
    rgb = np.dstack([stretch(p, valid) for p in planes])

    fig, ax = plt.subplots(figsize=(6, 6 * rgb.shape[0] / rgb.shape[1]), dpi=120)
    ax.imshow(rgb, interpolation="nearest")
    ax.add_patch(Rectangle(
        (args.sample / step, args.line / step),
        args.win_w / step, args.height / step,
        fill=False, edgecolor="#ff3b30", linewidth=1.6,
    ))
    ax.set_title(f"{args.rfl.name} - {samples}x{lines}, the demo's window outlined",
                 fontsize=9)
    ax.axis("off")
    fig.tight_layout()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    print(f"{args.out}: {rgb.shape[1]}x{rgb.shape[0]} from {samples}x{lines} "
          f"({args.out.stat().st_size / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()
