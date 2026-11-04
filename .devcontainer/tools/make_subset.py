"""
Crop a spatial window out of an ENVI cube pair (reflectance + uncertainty).

Used to build the small scene the Codespaces demo runs on. The full EMIT L2A
granule is 1242x1280x285 float32 (1.8 GB per cube); a 300x150 window is ~68 MB
per cube.

Keep the window at least 299 samples wide: Tetracorder's ENVI headers disagree
with its own VICAR labels below that, and every product raster comes back two
rows out of alignment. See .devcontainer/README.md.

The crop is spatial only -- every band is kept, because the ``convolve`` stage
reads its target wavelength/FWHM grid straight out of the reflectance header
and the convolved library has to match the scene channel for channel.

    python make_subset.py in/emit20250327t212148 out/subset --line 600 --sample 500 --size 100
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np

# ENVI data type code -> numpy dtype. Only the codes EMIT products actually use;
# anything else is rejected rather than guessed at.
DTYPES = {1: "u1", 2: "i2", 3: "i4", 4: "f4", 5: "f8", 12: "u2", 13: "u4"}


def read_hdr(path: Path) -> dict[str, str]:
    """Parse an ENVI header into a dict, keeping brace-delimited values whole."""
    text = path.read_text()
    if not text.lstrip().startswith("ENVI"):
        raise ValueError(f"{path} does not look like an ENVI header")

    fields: dict[str, str] = {}
    # A value is either brace-delimited (and may span lines) or runs to the end
    # of its line. Matching both in one pass keeps multi-line wavelength and
    # fwhm lists intact.
    for match in re.finditer(r"^([\w ]+?)\s*=\s*(\{.*?\}|.*?)$", text, re.M | re.S):
        fields[match.group(1).strip().lower()] = match.group(2).strip()
    return fields


def write_hdr(path: Path, fields: dict[str, str], samples: int, lines: int) -> None:
    """Write a header back out with new spatial dimensions."""
    fields = dict(fields, samples=str(samples), lines=str(lines))
    body = "\n".join(f"{key} = {value}" for key, value in fields.items())
    path.write_text(f"ENVI\n{body}\n")


def memmap_cube(data: Path, fields: dict[str, str]) -> np.ndarray:
    """Memory-map a cube as (lines, bands, samples), whatever its interleave."""
    samples, lines, bands = (int(fields[k]) for k in ("samples", "lines", "bands"))

    code = int(fields["data type"])
    if code not in DTYPES:
        raise ValueError(f"unsupported ENVI data type {code} in {data}")
    # byte order 0 is little-endian, 1 is big-endian (IEEE network order).
    endian = ">" if fields.get("byte order", "0").strip() == "1" else "<"
    dtype = np.dtype(endian + DTYPES[code])

    offset = int(fields.get("header offset", 0))
    interleave = fields.get("interleave", "bsq").strip().lower()
    shapes = {"bil": (lines, bands, samples), "bip": (lines, samples, bands), "bsq": (bands, lines, samples)}
    if interleave not in shapes:
        raise ValueError(f"unsupported interleave {interleave!r} in {data}")

    cube = np.memmap(data, dtype=dtype, mode="r", offset=offset, shape=shapes[interleave])
    # Normalise to (lines, bands, samples) so the caller can slice uniformly.
    if interleave == "bip":
        return cube.transpose(0, 2, 1)
    if interleave == "bsq":
        return cube.transpose(1, 0, 2)
    return cube


def crop(src: Path, dst: Path, line: int, sample: int, height: int, width: int) -> tuple[int, int, int]:
    """Crop one cube and write it back out as BIL, returning its dimensions."""
    fields = read_hdr(Path(f"{src}.hdr"))
    cube = memmap_cube(src, fields)

    lines, bands, samples = cube.shape
    if line + height > lines or sample + width > samples:
        raise ValueError(f"window ({line}, {sample}) +{height}x{width} exceeds {src} ({lines}x{samples})")

    window = np.asarray(cube[line : line + height, :, sample : sample + width])

    dst.parent.mkdir(parents=True, exist_ok=True)
    window.tofile(dst)
    # Always emit BIL: the window was normalised to (lines, bands, samples), and
    # a single interleave keeps the demo's readers simple.
    write_hdr(Path(f"{dst}.hdr"), dict(fields, interleave="bil"), width, height)
    return height, width, bands


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prefix", type=Path, help="input path prefix, e.g. in/emit20250327t212148")
    parser.add_argument("outprefix", type=Path, help="output path prefix")
    parser.add_argument("--line", type=int, default=600, help="first line of the window")
    parser.add_argument("--sample", type=int, default=500, help="first sample of the window")
    parser.add_argument("--size", type=int, default=100, help="window size in pixels (square)")
    parser.add_argument("--height", type=int, help="window height, overrides --size")
    parser.add_argument("--width", type=int, help="window width, overrides --size")
    args = parser.parse_args()

    height = args.height or args.size
    width = args.width or args.size

    for suffix in ("rfl", "uncert"):
        src = Path(f"{args.prefix}_{suffix}")
        dst = Path(f"{args.outprefix}_{suffix}")
        shape = crop(src, dst, args.line, args.sample, height, width)
        print(f"{dst}: {shape[0]}x{shape[1]}x{shape[2]} ({dst.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
