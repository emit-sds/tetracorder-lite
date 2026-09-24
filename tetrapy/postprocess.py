"""
Post-process a tetracorder run's output directory.

Two independent, config-gated operations over the tetracorder output tree:

- :func:`make_cogs` — repackage the rasters matched by a list of glob strings as
  tiled + compressed Cloud-Optimized GeoTIFFs, mirroring the tetracorder subdirectory
  tree under a dedicated output dir. GDAL can open the gzipped ENVI rasters
  (``*.depth.gz`` / ``*.fit.gz``) and the 8-bit ``.png`` products directly (as
  :mod:`tetrapy.aggregate` does via ``engine="rasterio"``), so no manual gunzip is
  needed. By default the conversion is a raw passthrough — no reprojection is applied,
  so the COGs are valid but not map-projected. When a GLT is supplied, each raster is
  orthorectified onto the GLT's map grid first (see :func:`orthorectify`), producing a
  georeferenced COG.
- :func:`remove_paths` — delete the paths (files or directories) matched by a list of
  glob strings, used to prune bulky intermediate tetracorder output that is not needed
  downstream.

:func:`run` runs whichever of the two are configured.
"""

import logging
import shutil
from pathlib import Path

import numpy as np
import xarray as xr


Logger = logging.getLogger(__name__)

# Raster containers whose extension names the *format* rather than the product, so it
# is replaced by .tif on output. Everything else (e.g. .depth / .fit) is preserved and
# .tif is appended, keeping foo.depth.gz and foo.fit.gz from colliding on foo.tif.
FORMAT_SUFFIXES = {".png", ".gif", ".jpg", ".jpeg", ".tif", ".tiff"}


def cog_dest(rel: Path, output: Path) -> Path:
    """
    Map a matched source raster to its mirrored COG destination path.

    The tetracorder subdirectory tree is preserved under ``output``. A trailing ``.gz``
    compression wrapper is stripped. If what remains ends in a known image-format
    suffix (``.png``/``.gif``/...), that suffix is replaced by ``.tif``; otherwise
    ``.tif`` is appended so the product marker (``.depth`` / ``.fit``) survives.

    Parameters
    ----------
    rel : pathlib.Path
        Source path relative to the tetracorder root.
    output : pathlib.Path
        Destination root.

    Returns
    -------
    pathlib.Path
        The COG path, e.g. ``group.x/foo.depth.gz`` -> ``{output}/group.x/foo.depth.tif``
        and ``results.masses/foo.png`` -> ``{output}/results.masses/foo.tif``.
    """
    name = rel.name[:-3] if rel.name.endswith(".gz") else rel.name

    if Path(name).suffix.lower() in FORMAT_SUFFIXES:
        name = Path(name).stem + ".tif"
    else:
        name = f"{name}.tif"

    return output / rel.parent / name


def orthorectify(da: xr.DataArray, glt: xr.DataArray) -> xr.DataArray:
    """
    Orthorectify a raw raster onto a GLT's map grid.

    An EMIT-style GLT is a 2-band lookup (band 0 = sample/crosstrack index, band 1 =
    line/downtrack index, 1-based, ``0`` = fill) carrying the target CRS and
    geotransform. Each output pixel copies the raw value it points at; fill pixels (and
    any index outside the raw array) are left at ``0``, which is also written as the
    COG's nodata value.

    Parameters
    ----------
    da : xarray.DataArray
        The raw raster as ``(band, y, x)``, on the tetracorder sample/line grid.
    glt : xarray.DataArray
        The GLT as ``(band, y, x)`` with its ``rio`` CRS/transform and ``x``/``y``
        map coordinates, as loaded by :func:`load_glt`.

    Returns
    -------
    xarray.DataArray
        The orthorectified raster as ``(band, y, x)`` on the GLT grid, carrying the
        GLT's CRS, transform, and a nodata value of ``0``.
    """
    raw = da.data
    nb, h, w = raw.shape

    glt_data = glt.data
    sample = np.round(np.abs(glt_data[0])).astype(int) - 1  # -> 0-based x index
    line = np.round(np.abs(glt_data[1])).astype(int) - 1    # -> 0-based y index

    # A pixel is valid only where the GLT is non-fill AND the index lands inside the
    # raw array, so a stray out-of-range lookup can never index past the edge.
    valid = (
        (glt_data[0] != 0) & (glt_data[1] != 0)
        & (line >= 0) & (line < h)
        & (sample >= 0) & (sample < w)
    )

    gy, gx = valid.shape
    out = np.zeros((nb, gy, gx), dtype=raw.dtype)
    out[:, valid] = raw[:, line[valid], sample[valid]]

    ortho = xr.DataArray(
        out,
        dims=("band", "y", "x"),
        coords={"band": da["band"], "y": glt["y"], "x": glt["x"]},
    )
    ortho.rio.write_crs(glt.rio.crs, inplace=True)
    ortho.rio.write_transform(glt.rio.transform(), inplace=True)
    ortho.rio.write_nodata(0, inplace=True)

    return ortho


def load_glt(path: str) -> xr.DataArray:
    """
    Load a GLT ENVI file as a ``(band, y, x)`` DataArray with CRS/transform.

    Parameters
    ----------
    path : str
        Path to the 2-band GLT ENVI file (EMIT L1B GLT).

    Returns
    -------
    xarray.DataArray
        The GLT bands, carrying map ``x``/``y`` coordinates and ``rio`` CRS/transform.
    """
    with xr.open_dataset(path, engine="rasterio") as ds:
        glt = ds["band_data"].load()

    if glt.rio.crs is None:
        Logger.warning(f"GLT {path} has no CRS; orthorectified COGs will carry a geotransform but no projection")

    return glt


def to_cog(src: Path, dest: Path, glt: xr.DataArray | None = None) -> None:
    """
    Convert a single tetracorder raster to a Cloud-Optimized GeoTIFF.

    Opens ``src`` (a gzipped ENVI raster or an ``.png``/``.gif``/``.jpg`` product, read
    directly by GDAL) and writes it to ``dest`` as a COG with DEFLATE compression. When
    ``glt`` is given, the raster is orthorectified onto the GLT grid first. The
    destination's parent directory is created if needed.

    Parameters
    ----------
    src : pathlib.Path
        Path to the source raster (e.g. a ``*.depth.gz`` / ``*.fit.gz`` / ``*.png`` file).
    dest : pathlib.Path
        Path to write the COG to (``.tif``).
    glt : xarray.DataArray, optional
        Pre-loaded GLT (see :func:`load_glt`). When given, ``src`` is orthorectified
        onto the GLT's map grid, yielding a georeferenced COG.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    # GDAL raises a (harmless) exception if not closed like this
    with xr.open_dataset(src, engine="rasterio") as ds:
        da = ds["band_data"].load()

    if glt is not None:
        da = orthorectify(da, glt)

    da.rio.to_raster(dest, driver="COG", compress="DEFLATE")


def make_cogs(
    tetracorder: str,
    glob: str | list[str],
    output: str,
    skip_existing: bool = False,
    glt: str | None = None,
) -> None:
    """
    Convert tetracorder output rasters matched by ``glob`` into COGs.

    Each pattern is resolved under ``tetracorder`` (recursive ``**`` supported).
    Matches are deduped across patterns and ``.hdr`` sidecars are ignored. For every
    matched raster, the mirrored destination under ``output`` is written as a COG (see
    :func:`cog_dest` for the naming). The gzipped ENVI rasters (``*.depth.gz`` /
    ``*.fit.gz``) and the 8-bit ``.png`` products share the same sample/line grid, so a
    single GLT orthorectifies all of them.

    Parameters
    ----------
    tetracorder : str
        Glob root — the tetracorder output directory the patterns resolve against.
    glob : str or list of str
        One or more glob patterns (relative to ``tetracorder``) selecting the rasters
        to convert (e.g. ``group.*/*.depth.gz``, ``results.masses/*.png``).
    output : str
        Destination root; the tetracorder subdirectory tree is mirrored beneath it.
    skip_existing : bool, default=False
        When True, matches whose destination COG already exists are left untouched.
        When False (default), existing COGs are overwritten.
    glt : str, optional
        Path to a GLT ENVI file (EMIT L1B GLT). When given, every raster is
        orthorectified onto the GLT's map grid, producing georeferenced COGs. When
        omitted, COGs are a raw (non-projected) passthrough.
    """
    root = Path(tetracorder)
    out = Path(output)

    if isinstance(glob, str):
        glob = [glob]

    glt_data = None
    if glt:
        Logger.info(f"Loading GLT {glt}")
        glt_data = load_glt(glt)

    # Dedupe matches across patterns while preserving discovery order, and drop the
    # .hdr sidecars so only the rasters themselves are converted.
    matches: list[Path] = []
    seen: set[Path] = set()
    for pattern in glob:
        for src in sorted(root.glob(pattern)):
            if src.suffix == ".hdr" or not src.is_file():
                continue
            if src not in seen:
                seen.add(src)
                matches.append(src)

    t = len(matches)
    Logger.info(f"Found {t} raster(s) to convert under {root}")

    converted = 0
    skipped = 0
    failed = 0
    for i, src in enumerate(matches, start=1):
        dest = cog_dest(src.relative_to(root), out)

        if skip_existing and dest.exists():
            skipped += 1
            Logger.debug(f"[{i:03}/{t:03}] - Skipping existing {dest}")
            continue

        try:
            to_cog(src, dest, glt=glt_data)
        except Exception:
            failed += 1
            Logger.exception(f"[{i:03}/{t:03}] ! Failed to convert {src}")
            continue

        converted += 1
        Logger.debug(f"[{i:03}/{t:03}] + {src} -> {dest}")

    Logger.info(f"COG conversion complete: {converted} converted, {skipped} skipped, {failed} failed of {t}")


def remove_paths(tetracorder: str, patterns: str | list[str]) -> None:
    """
    Delete the paths under ``tetracorder`` matched by ``patterns``.

    Each pattern is resolved under ``tetracorder`` (recursive ``**`` supported) and
    every match — file or directory — is deleted. Directories are removed recursively.
    Used to prune bulky intermediate tetracorder output that downstream stages do not
    need. Matches are deduped across patterns.

    Parameters
    ----------
    tetracorder : str
        Glob root — the tetracorder output directory the patterns resolve against.
    patterns : str or list of str
        One or more glob patterns (relative to ``tetracorder``) selecting the paths to
        delete.
    """
    root = Path(tetracorder)

    if isinstance(patterns, str):
        patterns = [patterns]

    matches: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if path not in seen:
                seen.add(path)
                matches.append(path)

    t = len(matches)
    Logger.info(f"Found {t} path(s) to remove under {root}")

    removed = 0
    failed = 0
    for i, path in enumerate(matches, start=1):
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        except Exception:
            failed += 1
            Logger.exception(f"[{i:03}/{t:03}] ! Failed to remove {path}")
            continue

        removed += 1
        Logger.debug(f"[{i:03}/{t:03}] - Removed {path}")

    Logger.info(f"Removal complete: {removed} removed, {failed} failed of {t}")


def run(
    tetracorder: str,
    cogs: dict | None = None,
    remove: list[str] | None = None,
) -> None:
    """
    Run the configured post-processing operations over a tetracorder output tree.

    Parameters
    ----------
    tetracorder : str
        Glob root — the tetracorder output directory both operations resolve against.
    cogs : dict, optional
        COG conversion options: ``{"output": str, "glob": str | list[str],
        "skip_existing": bool, "glt": str}``. ``glt`` is optional; when set, rasters
        are orthorectified onto the GLT grid. When ``cogs`` is falsy, COG conversion is
        skipped.
    remove : list of str, optional
        Glob patterns whose matching paths are deleted. When falsy, nothing is removed.
    """
    if cogs:
        make_cogs(
            tetracorder   = tetracorder,
            glob          = cogs["glob"],
            output        = cogs["output"],
            skip_existing = cogs.get("skip_existing", False),
            glt           = cogs.get("glt"),
        )

    # Remove last: it may delete the very rasters COG conversion just read from.
    if remove:
        remove_paths(tetracorder, remove)
