import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import xarray as xr
from scipy.interpolate import interp1d

from tetrapy.conv import SpecprFile
from tetrapy.tetracorder import TetraDecoder


Logger = logging.getLogger(__name__)

# Assumed dimension and variable names
Dims = dict(
    y = "downtrack",
    x = "crosstrack"
)

# Fill value stamped into nodata pixels, matching the L2B heritage products
Fill = -9999.0


def get_names(group):
    return SimpleNamespace(
        depth  = f"group_{group}_band_depth",
        minid  = f"group_{group}_mineral_id",
        uncert = f"group_{group}_band_depth_unc",
        fit    = f"group_{group}_fit",
    )


def nodata_mask(rfl: xr.DataArray) -> np.ndarray:
    """
    Locate pixels carrying no usable reflectance.

    Two sentinels are treated as nodata. ENVI-declared fill (``-9999``) covers
    orthorectified products, and an all-zero spectrum covers frames dropped by the
    onboard cloud screening: EMIT L2A writes those as exact zeros in raw space even
    though the header advertises ``-9999``, so a fill-only test never fires on them.

    Both tests require the whole spectrum to match, so a pixel with a single bad
    channel stays valid data rather than being discarded.

    Parameters
    ----------
    rfl : xarray.DataArray
        Observed reflectance as ``(y, x, band)``.

    Returns
    -------
    numpy.ndarray
        Boolean ``(y, x)`` mask, True where the pixel carries no usable data.
    """
    data = rfl.data

    fill = (data == Fill).all(axis=-1)
    zero = (data == 0).all(axis=-1)
    mask = fill | zero

    Logger.info(
        f"Nodata mask: {mask.sum()}/{mask.size} pixels ({mask.mean():.2%}) "
        f"[{fill.sum()} fill, {zero.sum()} all-zero]"
    )

    return mask


def save(ds: xr.Dataset, file: str | Path) -> None:
    """
    Write a product to disk, dispatching on the file extension.

    Parameters
    ----------
    ds : xarray.Dataset
        The product to write, holding named band variables over the
        ``downtrack``/``crosstrack`` dimensions.
    file : str or Path
        Destination path. ``.nc`` is written as NetCDF and ``.tif`` as a GeoTIFF
        (via ``rioxarray``); any other extension is logged as an error and skipped.
    """
    file = Path(file)
    file.parent.mkdir(exist_ok=True, parents=True)

    if file.suffix == ".nc":
        Logger.info(f"Saving {file}")
        # Declare the fill so readers mask it instead of reading it back as data.
        ds.to_netcdf(file, encoding={var: {"_FillValue": Fill} for var in ds})
    elif file.suffix == ".tif":
        Logger.info(f"Saving {file}")
        # GeoTIFF has no concept of named dimensions; point rioxarray at ours.
        ds = ds.rio.set_spatial_dims(x_dim=Dims["x"], y_dim=Dims["y"])
        for var in ds:
            ds[var].rio.write_nodata(Fill, inplace=True)
        ds.rio.to_raster(file)
    else:
        Logger.error(f"File extension unrecognized, must be either .nc or .tif, got: {file.suffix}")


def read_library(path: str) -> dict[str, list[int] | np.ndarray]:
    """
    Read a convolved specpr library into records and reflectance.

    Reads every spectrum from the convolved specpr library directly, keyed by its
    absolute record number (the same number the expert system references), so the
    uncertainty calculation can look up a block's reference spectrum by record.

    Parameters
    ----------
    path : str
        Path to the convolved specpr library (as written by :mod:`tetrapy.conv`).

    Returns
    -------
    dict
        ``{"records": list[int], "rfl": ndarray}`` where ``rfl`` is the reflectance
        array shaped ``(n_records, n_bands)`` and ``records`` are the library record
        numbers in row order. Deleted channels carry the specpr ``-1.23e34`` sentinel.
    """
    lib = SpecprFile.open(path)

    records = list(lib.spectra())
    rfl = np.stack([lib.read_spectrum(recno) for recno in records])

    return {
        "records": records,
        "rfl": rfl,
    }


def cont_rem(
    wavelengths: np.ndarray,
    reflectance: np.ndarray,
    continuum_idx: tuple[np.ndarray, np.ndarray],
    valid_wavelengths: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Continuum-remove a reflectance spectrum (Kaufman and Tanre, 1992).

    Draws a straight line between the mean reflectance of the left and right
    continuum windows and returns ``1 - reflectance / continuum`` over the feature
    bands (those valid channels spanning the two windows).

    Parameters
    ----------
    wavelengths : numpy.ndarray
        Per-band wavelengths, ``(n_bands,)``.
    reflectance : numpy.ndarray
        Reflectance values, ``(n_pixels, n_bands)``.
    continuum_idx : tuple[numpy.ndarray, numpy.ndarray]
        ``(left_inds, right_inds)`` continuum-window index arrays.
    valid_wavelengths : numpy.ndarray
        Boolean mask of usable channels, ``(n_bands,)``.

    Returns
    -------
    tuple[numpy.ndarray, numpy.ndarray]
        ``(depths, feature_inds)``: continuum-removed reflectance
        ``(n_pixels, n_feature_bands)`` and the band indices it spans.
    """
    left_inds, right_inds = continuum_idx

    left_x, right_x = wavelengths[int(left_inds.mean())], wavelengths[int(right_inds.mean())]
    left_y, right_y = reflectance[:, left_inds].mean(), reflectance[:, right_inds].mean()

    band = np.arange(len(valid_wavelengths))
    feature_inds = np.where((band >= left_inds[0]) & (band <= right_inds[-1]) & valid_wavelengths)[0]

    continuum = interp1d([left_x, right_x], [left_y, right_y], fill_value="extrapolate")(wavelengths[feature_inds])
    depths = 1 - reflectance[:, feature_inds] / continuum
    return depths, feature_inds


def get_continuum_idx(
    wavelengths: np.ndarray,
    feature: tuple[float, float, float, float],
    valid_wavelengths: np.ndarray,
) -> tuple[np.ndarray, np.ndarray] | None:
    """
    Locate the continuum-window band indices for a feature.

    A feature is ``(a, b, c, d)``: the left window spans ``[a, b]`` and the right
    ``[c, d]``. When a window contains no valid channels, it falls back to the single
    nearest band just inside it (first band ``>= b`` on the left, last band ``<= c``
    on the right).

    Parameters
    ----------
    wavelengths : numpy.ndarray
        Per-band wavelengths, ``(n_bands,)``.
    feature : tuple[float, float, float, float]
        ``(a, b, c, d)`` continuum-window bounds.
    valid_wavelengths : numpy.ndarray
        Boolean mask of usable channels, ``(n_bands,)``.

    Returns
    -------
    tuple[numpy.ndarray, numpy.ndarray] or None
        ``(left_inds, right_inds)`` index arrays, or ``None`` if no continuum exists.
    """
    a, b, c, d = feature
    left = np.where(valid_wavelengths & (wavelengths >= a) & (wavelengths <= b))[0]
    right = np.where(valid_wavelengths & (wavelengths >= c) & (wavelengths <= d))[0]

    if left.size == 0:
        nearest = np.where(wavelengths >= b)[0]
        if nearest.size == 0:
            return None
        left = nearest[:1]

    if right.size == 0:
        nearest = np.where(wavelengths <= c)[0]
        if nearest.size == 0:
            return None
        right = nearest[-1:]

    return left, right


def calculate_uncertainty(
    wl: np.ndarray,
    rfl: np.ndarray,
    uncert: np.ndarray,
    lib: np.ndarray,
    features: list[dict],
) -> np.ndarray:
    """
    Per-pixel uncertainty of the Clark (2003) continuum-normalized band depth.

    The band depth is modelled as ``bd = a * L(w_star)``, where ``L`` is the
    continuum-removed library spectrum and ``a`` is the least-squares scale fitting
    the observed continuum-removed spectrum to ``L``::

        a = L(w_star) / (n * Σ L² − (Σ L)²)

    Treating each band's continuum-removed uncertainty as its reflectance
    uncertainty ``σ`` and assuming bands are independent, the band-depth variance is::

        var = a² * ( n² * Σ(L² σ²) + (Σ L)² * Σ σ² )

    Each ``MLw``/``DLw`` feature contributes ``sqrt(var)``; the features are combined
    as a weighted mean, weighted by the number of bands in each feature.

    Parameters
    ----------
    wl : numpy.ndarray
        Per-band wavelengths in microns, ``(n_bands,)``.
    rfl : numpy.ndarray
        Observed reflectance for the valid pixels, ``(n_pixels, n_bands)``.
    uncert : numpy.ndarray
        Observed reflectance uncertainty, same shape as ``rfl``.
    lib : numpy.ndarray
        Library reference reflectance for the record, ``(n_bands,)``.
    features : list[dict]
        The block's feature definitions.

    Returns
    -------
    numpy.ndarray
        Band-depth uncertainty per pixel, ``(n_pixels,)``.
    """
    good = rfl[0] != -0.01  # deleted channels share the -0.01 sentinel

    uncertainties, weights = [], []
    for feature in features:
        if feature["feature_type"] not in ("MLw", "DLw"):
            continue

        idx = get_continuum_idx(wl, feature["continuum"], good)
        if idx is None:
            continue

        lib_cont, bands = cont_rem(wl, lib[None, :], idx, good)
        lib_cont = np.squeeze(lib_cont)
        sigma = uncert[:, bands]
        n = len(lib_cont)

        a = lib_cont.max() / (n * np.sum(lib_cont**2) - lib_cont.sum() ** 2)
        var = n**2 * (sigma**2 @ lib_cont**2) + lib_cont.sum() ** 2 * np.sum(sigma**2, axis=1)

        uncertainties.append(abs(a) * np.sqrt(var))
        weights.append(n)

    if not uncertainties:
        return np.zeros(len(rfl))

    return np.average(uncertainties, axis=0, weights=weights)


def aggregate(
    decoder: TetraDecoder,
    group: int,
    rfl: xr.DataArray | None = None,
    uncert: xr.DataArray | None = None,
    libs: dict[str, dict] | None = None,
    ref: pd.DataFrame | None = None,
    mask: np.ndarray | None = None,
) -> tuple[xr.Dataset | None, xr.Dataset | None]:
    """
    Aggregate one tetracorder group into band-depth / mineral-id maps.

    Walks every decoded block in ``group``, loads its ``.depth``/``.fit`` outputs,
    and composites them into a two-band ``(band, y, x)`` array: band 0 is the scaled
    band depth, band 1 is the (1-based) mineral index of the winning block per pixel.
    A matching uncertainty array carries the Clark-2003 band-depth uncertainty (band
    0) and the fit (band 1). Uncertainty is only computed when the reflectance inputs
    and libraries are supplied.

    Parameters
    ----------
    decoder : TetraDecoder
        Decoded expert system providing the blocks and their output paths.
    group : int
        Group number to aggregate (e.g. ``1`` or ``2``).
    rfl : xarray.DataArray, optional
        Observed reflectance as ``(y, x, band)`` carrying a ``wavelength`` coordinate,
        aligned with the depth/fit rasters. Required (with ``uncert`` and ``libs``)
        for uncertainty.
    uncert : xarray.DataArray, optional
        Observed reflectance uncertainty, same shape/ordering as ``rfl``.
    libs : dict[str, dict], optional
        Library id -> ``{"records": [...], "rfl": ndarray}`` as produced by
        :func:`read_library`. Its presence is what enables the uncertainty band.
    ref : pandas.DataFrame, optional
        Reference matrix mapping material ``title`` to a stable ``index``. When
        given, the mineral-id band uses that index instead of the running block
        counter; a material missing from the matrix is assigned a negative id and
        logged.
    mask : numpy.ndarray, optional
        Boolean ``(y, x)`` nodata mask from :func:`nodata_mask`. Pixels it marks are
        stamped with ``Fill`` in every output band after the block loop. Without it
        nodata pixels keep the zero-seeded value and are indistinguishable from real
        pixels where nothing was detected.

    Returns
    -------
    tuple[xarray.Dataset | None, xarray.Dataset | None]
        ``(mins, minuncert)`` over the ``(downtrack, crosstrack)`` dimensions, or
        ``(None, None)`` if the group had no valid input. ``mins`` carries the scaled
        band depth (``group_{group}_band_depth``) and mineral id
        (``group_{group}_mineral_id``); ``minuncert`` carries the band-depth
        uncertainty (``group_{group}_band_depth_unc``) and fit (``group_{group}_fit``).
    """
    # Variable names
    names = get_names(group)

    Logger.debug(f"Aggregating group {group}")
    blocks = decoder.get_groups([group])

    # libs only exists if we're calculating uncertainty
    if libs:
        wl = rfl.wavelength.data
        if (wl > 100).any():
            wl = wl / 1000

    # Tracking statistics
    c = 0
    t = len(blocks)

    # Union of every block's valid pixels, so the summary below can tell a pixel
    # that was masked out from one that was simply never detected
    claimed = None

    mins = None
    minuncert = None
    for i, block in enumerate(blocks, start=1):
        name = block["title"]
        base = decoder.root / block["path"]

        idx = i
        if ref is not None:
            query = ref.query("id == @block['id']")
            if not query.empty:
                idx = int(query["index"].iloc[0])
                name = query["title"].iloc[0]
            else:
                idx = -i
                Logger.warning(f"[{i:03}/{t:03}] ? Reference matrix does not contain an index for {name}, setting ID to {idx}")

        # Find the data files
        if not (depth := base.with_name(f"{base.name}.depth.gz")).exists():
            Logger.debug(f"[{i:03}/{t:03}] - Depth file not found for {name}")
            continue

        if not (fit := base.with_name(f"{base.name}.fit.gz")).exists():
            Logger.debug(f"[{i:03}/{t:03}] - Fit file not found for {name}")
            continue

        # GDAL raises a (harmless) exception if not closed like this
        with xr.open_dataset(depth, engine="rasterio") as ds:
            depth = ds["band_data"].squeeze().load().rename(Dims)

        valid = depth > 0
        if not valid.any():
            Logger.debug(f"[{i:03}/{t:03}] - No valid data for {name}")
            continue

        if claimed is None:
            claimed = np.zeros(valid.shape, dtype=bool)
        claimed |= valid.data

        # Copy shape (and downtrack/crosstrack coords) from first valid input
        if mins is None:
            template = xr.zeros_like(depth, dtype=float)
            mins = xr.Dataset({names.depth: template, names.minid: template.copy()})
            minuncert = xr.Dataset({names.uncert: template.copy(), names.fit: template.copy()})

        with xr.open_dataset(fit, engine="rasterio") as ds:
            fit = ds["band_data"].squeeze().load().rename(Dims)

        # Apply scaling factor
        depth = depth / 255.0 * 0.5
        fit = fit / 255.0 * 0.5

        # Band Depth
        mins[names.depth] = mins[names.depth].where(~valid, depth)

        # Mineral ID
        mins[names.minid] = mins[names.minid].where(~valid, idx)

        # Uncertainty
        if libs:
            lib = libs[block["library"]]
            rec = block["record"]
            if rec in lib["records"]:
                unc = calculate_uncertainty(
                    wl = wl,
                    rfl = rfl.data[valid.data],
                    uncert = uncert.data[valid.data],
                    lib = lib["rfl"][lib["records"].index(rec)],
                    features = block["features"],
                )

                full = xr.zeros_like(valid, dtype=float)
                full.data[valid] = unc

                minuncert[names.uncert] = minuncert[names.uncert].where(~valid, full)
            else:
                Logger.warning(f"[{i:03}/{t:03}] * Library record {rec} not found in {block['library']}, cannot calculate uncertainty for {name}")

        # Fit
        minuncert[names.fit] = minuncert[names.fit].where(~valid, fit)

        c += 1
        Logger.debug(f"[{i:03}/{t:03}] + [ID: {idx}] Added {name}")

    Logger.debug(f"{c}/{t} ({c / t:.1%}) Blocks successfully aggregated")

    if mins is None:
        return None, None

    if mask is None:
        Logger.warning(f"Group {group}: no nodata mask supplied, nodata pixels will read as 0")
        return mins, minuncert

    # This has to happen after the block loop, not inside it. The accumulators are
    # seeded with zeros and only written where a block is valid, so until the input
    # mask is stamped over them a nodata pixel is indistinguishable from a real
    # pixel where nothing was detected.
    if claimed is not None:
        unclaimed = ~claimed
        Logger.info(
            f"Group {group}: {int((unclaimed & mask).sum())} nodata pixels flagged {Fill:.0f}, "
            f"{int((unclaimed & ~mask).sum())} valid pixels with no detection left at 0"
        )
        if overlap := int((claimed & mask).sum()):
            Logger.warning(f"Group {group}: {overlap} masked pixels were claimed by a block, overriding to {Fill:.0f}")

    for ds in (mins, minuncert):
        for var in ds:
            ds[var].data[mask] = Fill

    return mins, minuncert


def build(
    tetracorder: str,
    out_min: str | None = None,
    out_minuncert: str | None = None,
    rfl: str | None = None,
    rfluncert: str | None = None,
    reflib: str | None = None,
    reslib: str | None = None,
    reference: str | None = None,
) -> tuple[xr.DataArray, xr.DataArray]:
    """
    Aggregate groups 1 and 2 into the L2B mineral / uncertainty products.

    \b
    Parameters
    ----------
    tetracorder : str
        Path to the tetracorder output directory (holding the expert system file).
    out_min, out_minuncert : str or None
        Explicit output paths for the mineral and uncertainty products. Take
        precedence over ``output``; the extension of each path decides its format.
    rfl, rfluncert : str, optional
        Paths to the observed reflectance and reflectance-uncertainty rasters. Both
        must be given (and exist, alongside the libraries) to enable band-depth
        uncertainty calculation. ``rfl`` alone drives the nodata mask, which is
        applied regardless of whether uncertainty is calculated; without it nodata
        pixels are indistinguishable from real zeros in the products.
    reflib, reslib : str, optional
        Paths to the convolved reference (``splib06``) and research (``sprlb06``)
        specpr libraries. Only read when uncertainty is being calculated.
    reference : str, optional
        Path to a reference matrix CSV (with ``title`` and ``index`` columns). When
        given, it is read into a DataFrame and passed to :func:`aggregate` so the
        mineral-id band uses each material's stable ``index``.

    \b
    Returns
    -------
    tuple[xarray.Dataset, xarray.Dataset]
        The abundance and uncertainty products over the ``(downtrack, crosstrack)``
        dimensions. ``mins`` holds ``group_1_band_depth``/``group_1_mineral_id`` and the
        group 2 equivalents; ``uncert`` holds ``group_1_band_depth_unc``/``group_1_fit``
        and the group 2 equivalents. Returned regardless of whether they were written to
        disk.
    """
    tc = TetraDecoder(tetracorder)

    if reference:
        reference = pd.read_csv(reference)

    # Resolved before rfl is replaced by its loaded DataArray, because truthiness on
    # a DataArray is elementwise and would raise here. Tested by truthiness rather
    # than `is not None` because the config loader is a default_box Box: an absent or
    # null key arrives as an empty Box, so the inputs are never literally None.
    uncertainty = all((rfl, rfluncert, reflib, reslib))
    if uncertainty:
        # The shipped config carries placeholder paths, so being set is not proof of
        # being present. Degrade to no-uncertainty rather than dying on a missing file
        # the caller never intended to supply -- the nodata mask does not depend on it.
        if missing := [str(f) for f in (rfluncert, reflib, reslib) if not Path(f).exists()]:
            Logger.warning(f"Skipping uncertainty, inputs not found: {', '.join(missing)}")
            uncertainty = False
    supplied = bool(rfl)

    # The nodata mask depends only on the reflectance, so load it whenever one is
    # given rather than gating it on the uncertainty inputs being complete too
    mask = None
    if supplied:
        Logger.info("Loading reflectance")

        # Transpose to stay consistent with the tetracorder products
        with xr.open_dataset(rfl, engine="rasterio") as ds:
            rfl = ds["band_data"].transpose("y", "x", "band").load()

        mask = nodata_mask(rfl)
    else:
        Logger.warning("No reflectance supplied, nodata pixels cannot be flagged")

    libs = None
    if uncertainty:
        Logger.info("Loading reflectance uncertainty")

        with xr.open_dataset(rfluncert, engine="rasterio") as ds:
            rfluncert = ds["band_data"].transpose("y", "x", "band").load()

        libs = {
            "sprlb06": read_library(reslib),
            "splib06": read_library(reflib),
        }
    else:
        # Never hand aggregate() an unloaded path
        rfluncert = None

    mins1, uncert1 = aggregate(tc, 1, rfl, rfluncert, libs, reference, mask)
    mins2, uncert2 = aggregate(tc, 2, rfl, rfluncert, libs, reference, mask)

    # Variables: group_1_band_depth, group_1_mineral_id, group_2_band_depth, group_2_mineral_id
    mins = xr.merge([mins1, mins2], compat="override")

    # Variables: group_1_band_depth_unc, group_1_fit, group_2_band_depth_unc, group_2_fit
    uncert = xr.merge([uncert1, uncert2], compat="override")

    # Save products
    if out_min:
        save(mins, out_min)
    if out_minuncert:
        save(uncert, out_minuncert)

    return mins, uncert
