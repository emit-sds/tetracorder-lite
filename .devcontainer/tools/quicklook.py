"""
Render the demo's result imagery from a finished ``tetrapy run``.

Runs inside the tetracorder-lite image, which already carries numpy, matplotlib
and xarray, so the devcontainer itself needs no Python environment of its own.

Produces, into --out:
  rfl_rgb.png        true-colour quicklook of the input reflectance
  group1.png         group 1 mineral identifications, with a legend
  group2.png         group 2 mineral identifications, with a legend
  group1_depth.png   group 1 band depth
  group2_depth.png   group 2 band depth
  results.json       per-group statistics the results page reads
  color/*.png        Tetracorder's own colour products, copied from the run

Mineral ID values in the aggregate product are ``index`` values from the
reference matrix (tetrapy/data/v6.00a6.csv); 0 means "nothing identified".
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap, to_hex, to_rgb, rgb_to_hsv, hsv_to_rgb

# Families beyond this many per group are folded into a single "other" class so
# the legend stays readable. They are still counted in the totals.
LEGEND_LIMIT = 12
OTHER = "#8a8a8a"
NODATA = -9999

# Readable names for the family prefixes the reference matrix encodes in its
# `path` column. Only prefixes needing more than capitalisation are listed --
# a chemical class that should read as a plural, an abbreviation, or an iron
# variant that belongs with an existing family. Everything else falls through to
# a title-cased prefix, which is already the mineral's name: `actinolite` ->
# `Actinolite`. That covers the long tail without enumerating it.
FAMILY_NAMES = {
    # iron, including the variants that belong with the main families
    "fe3+": "Fe3+ oxides", "fe3+bearing1": "Fe3+ bearing", "fe3+bearing2": "Fe3+ bearing",
    "fe3+mix": "Fe3+ mixtures", "fe3+mn": "Fe3+ / Mn oxides",
    "fe3+copper-hydroxide": "Fe3+ / copper hydroxides",
    "fe2+": "Fe2+ minerals", "fe2+generic": "Fe2+ minerals",
    "fe2+fe3+": "Fe2+/Fe3+ mixed", "fe3+fe2+": "Fe2+/Fe3+ mixed",
    "fe2+fe3+mix": "Fe2+/Fe3+ mixed",
    # clay and mica groups
    "kaolgrp": "Kaolin group", "kaolin": "Kaolin group", "kaol": "Kaolin group",
    "kaolin-smect": "Kaolin-smectite", "micagrp": "Micas", "smectite": "Smectites",
    "chlorite": "Chlorite", "chlorite-skarn": "Chlorite (skarn)", "clay": "Clays",
    "musc": "Muscovite", "pyroph": "Pyrophyllite", "dick": "Dickite",
    # chemical classes, which read better as plurals than as the bare prefix
    "carbonate": "Carbonates", "sulfate": "Sulfates", "sulfate-mix": "Sulfates",
    "sulfate-bloedite": "Sulfates", "sulfide": "Sulfides", "nitrate": "Nitrates",
    "borate": "Borates", "chloride": "Chlorides", "halide": "Halides",
    "phosphate": "Phosphates", "oxide": "Oxides", "hydroxide": "Hydroxides",
    "perchlorate": "Perchlorates", "feldspar": "Feldspars", "zeolite": "Zeolites",
    "amphibole": "Amphiboles", "pyroxene": "Pyroxenes", "garnet": "Garnets",
    "inosilicate": "Inosilicates", "phyllosilicate": "Phyllosilicates",
    "cyanide": "Cyanides", "cyanide-trihydrate": "Cyanides",
    # abbreviations and everything else that is not simply its own name
    "sioh": "Si-OH hydrated silica", "ree": "Rare-earth elements",
    "mn": "Manganese minerals", "mn2+": "Mn2+ minerals",
    "Mn-Coating": "Manganese coatings", "methane-gas": "Methane and gases",
    # Tetracorder's own wording for these two, from the colour recipes' legends
    "Kalun+kaol.intmx": "K-alunite", "Na-alun+kaol.intmx": "Na-alunite",
    "serpentine": "Serpentine", "organic": "Organic / vegetation",
    "copper": "Copper minerals", "white": "Surface crusts",
}


def shades(base: str, n: int) -> list[str]:
    """
    n tones of one hue, dark-saturated through light-desaturated.

    Family alone is too coarse: colouring 17 Fe3+ entries identically turned a
    map with real structure -- distinct fan surfaces carrying different
    goethite/hematite mixes -- into one flat blue. Per-entry colour is too fine,
    and renders near-identical library entries as speckle. One hue per family
    with a tone per entry keeps both readings: the family is obvious at a
    glance, the within-family variation survives.
    """
    h, sat, val = rgb_to_hsv(to_rgb(base))
    if n <= 1:
        return [to_hex(hsv_to_rgb((h, sat, val)))]
    out = []
    for i in range(n):
        f = i / (n - 1)
        # A deliberately tight ramp. Wider (0.60->1.15 of value) recovered the
        # within-family structure but darkened and desaturated enough that the
        # families themselves stopped being distinguishable from each other,
        # which is the thing this is for.
        v = float(np.clip(val * (0.82 + 0.30 * f), 0.0, 1.0))
        t = float(np.clip(sat * (1.08 - 0.34 * f), 0.0, 1.0))
        out.append(to_hex(hsv_to_rgb((h, t, v))))
    return out


def family(path: str) -> str:
    """
    Mineral family for a reference-matrix entry, from its `path` column.

    Tetracorder groups its products as ``group.<region>/<family>_<material>``, so
    the family is already there: `fe3+_goethite.thincoat`,
    `kaolgrp_kaolinite_wxl`, `carbonate_calcite`. Colouring by this rather than
    by individual library entry is what stops a coherent unit looking like
    speckle -- Kaolinite CM9 and Kaolinite KGa-2 are adjacent indices and nearly
    the same mineral, but as separate colours they flicker pixel to pixel.
    """
    tail = path.split("/")[-1]
    m = re.match(r"([a-z0-9+\-]+?)_", tail)
    if m:
        key = m.group(1)
    else:
        # No underscore, so the whole tail is the entry: take its leading
        # alphabetic components. Splitting on "." instead truncated mid-formula,
        # turning calcite+0.5Ca-mont into the family "calcite+0".
        m2 = re.match(r"([a-z][a-z0-9]*(?:[+\-][a-z][a-z0-9]*)*)", tail)
        key = m2.group(1) if m2 else tail

    if key in FAMILY_NAMES:
        return FAMILY_NAMES[key]

    # A mixture takes the family of its leading component, so talc+calcite is
    # Talc. Tried only after the exact lookup, or fe3+ would lose its "+" and
    # stop matching.
    head = key.split("+")[0]
    if head in FAMILY_NAMES:
        return FAMILY_NAMES[head]

    # Otherwise the prefix is already the mineral's name and only needs casing.
    return (head or key).replace("-", " ").capitalize()


# ENVI data type codes, for showing the header in human terms.
DTYPE_NAMES = {1: "8-bit unsigned int", 2: "16-bit signed int", 3: "32-bit signed int",
               4: "32-bit float", 5: "64-bit float", 12: "16-bit unsigned int",
               13: "32-bit unsigned int"}
INTERLEAVE_NAMES = {"bil": "band interleaved by line", "bip": "band interleaved by pixel",
                    "bsq": "band sequential"}


def read_envi(prefix: Path) -> tuple[np.ndarray, np.ndarray, dict[str, str]]:
    """Read an ENVI cube as (lines, samples, bands), its wavelengths, and its header."""
    fields: dict[str, str] = {}
    for match in re.finditer(r"^([\w ]+?)\s*=\s*(\{.*?\}|.*?)$", Path(f"{prefix}.hdr").read_text(), re.M | re.S):
        fields[match.group(1).strip().lower()] = match.group(2).strip()

    samples, lines, bands = (int(fields[k]) for k in ("samples", "lines", "bands"))
    endian = ">" if fields.get("byte order", "0").strip() == "1" else "<"
    dtype = np.dtype(endian + {1: "u1", 2: "i2", 3: "i4", 4: "f4", 5: "f8", 12: "u2", 13: "u4"}[int(fields["data type"])])

    interleave = fields.get("interleave", "bsq").strip().lower()
    shapes = {"bil": (lines, bands, samples), "bip": (lines, samples, bands), "bsq": (bands, lines, samples)}
    cube = np.memmap(prefix, dtype=dtype, mode="r", offset=int(fields.get("header offset", 0)), shape=shapes[interleave])
    axes = {"bil": (0, 2, 1), "bip": (0, 1, 2), "bsq": (1, 2, 0)}[interleave]

    wl = np.array([float(v) for v in fields["wavelength"].strip("{}").split(",")])
    return np.asarray(cube.transpose(axes), dtype=np.float32), wl, fields


def vector(fields: dict[str, str], key: str) -> np.ndarray:
    """Parse an ENVI `key = { a, b, ... }` numeric vector, or an empty array."""
    if key not in fields:
        return np.array([])
    return np.array([float(v) for v in fields[key].strip("{}").split(",") if v.strip()])


def describe_header(fields: dict[str, str]) -> list[dict]:
    """
    Summarise the header fields the pipeline actually depends on.

    Two groups, and the distinction matters. The first are what any ENVI reader
    needs to make sense of the bytes at all. The second are specific to this
    pipeline: tetrapy/conv/library.py reads `wavelength` and `fwhm` from this
    very file to build the grid it convolves the spectral library onto, and
    raises if either is missing or if their lengths disagree.
    """
    wl, fwhm, bbl = vector(fields, "wavelength"), vector(fields, "fwhm"), vector(fields, "bbl")
    dt = int(fields.get("data type", 0))
    order = fields.get("byte order", "0").strip()
    units = fields.get("wavelength units", "(absent - assumed nanometres)")

    rows = [
        ("samples", fields.get("samples", "-"), "pixels across track", "geometry"),
        ("lines", fields.get("lines", "-"), "pixels along track", "geometry"),
        ("bands", fields.get("bands", "-"), "spectral channels", "geometry"),
        ("data type", f"{dt} - {DTYPE_NAMES.get(dt, 'unknown')}", "how each value is stored", "geometry"),
        ("interleave", f"{fields.get('interleave','-').upper()} - "
                       f"{INTERLEAVE_NAMES.get(fields.get('interleave','').lower(),'?')}",
         "the order values are written in", "geometry"),
        ("byte order", f"{order} - {'big' if order == '1' else 'little'}-endian",
         "byte order of each value", "geometry"),
        ("header offset", fields.get("header offset", "0"), "bytes to skip before the data", "geometry"),
    ]
    if wl.size:
        rows.append(("wavelength", f"{wl.size} values, {wl.min():.1f}-{wl.max():.1f}",
                     "centre wavelength of every channel", "spectral"))
    rows.append(("wavelength units", units, "nanometres unless stated otherwise", "spectral"))
    if fwhm.size:
        rows.append(("fwhm", f"{fwhm.size} values, {fwhm.min():.2f}-{fwhm.max():.2f}",
                     "width of each channel's response", "spectral"))
    if bbl.size:
        rows.append(("bbl", f"{int((bbl == 0).sum())} of {bbl.size} channels flagged bad",
                     "bad band list", "spectral"))
    return [{"key": k, "value": str(v), "note": n, "group": g} for k, v, n, g in rows]


def stretch(band: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Linear 2-98 percentile stretch to [0, 1], with invalid pixels at 0."""
    if not valid.any():
        return np.zeros_like(band)
    lo, hi = np.percentile(band[valid], (2, 98))
    if hi <= lo:
        return np.zeros_like(band)
    return np.clip((band - lo) / (hi - lo), 0, 1) * valid


def render_rgb(cube: np.ndarray, wl: np.ndarray, out: Path) -> dict:
    """True-colour composite from the red, green and blue EMIT channels."""
    idx = [int(np.argmin(abs(wl - target))) for target in (640.0, 550.0, 470.0)]
    valid = (cube[:, :, idx[0]] != NODATA) & np.isfinite(cube[:, :, idx[0]])
    rgb = np.dstack([stretch(cube[:, :, i], valid) for i in idx])

    fig, ax = plt.subplots(figsize=(6, 6), dpi=140)
    ax.imshow(rgb, interpolation="nearest")
    ax.set_title("L2A reflectance (true colour)", fontsize=11)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    return {"lines": int(cube.shape[0]), "samples": int(cube.shape[1]), "bands": int(cube.shape[2]),
            "valid_pixels": int(valid.sum())}


def render_group(ids: np.ndarray, depth: np.ndarray, titles: dict[int, str],
                 fams: dict[int, str], group: int, out: Path) -> dict:
    """Render one group's mineral-ID map and band-depth map; return its stats."""
    values, counts = np.unique(ids[ids > 0].astype(int), return_counts=True)
    order = np.argsort(-counts)
    values, counts = values[order], counts[order]

    # Colour by mineral family, not by library entry. Comparing this tile
    # against the operational L2B V001 product, group 1 agrees on the exact
    # library entry only 45% of the time but on the family 98.6% -- the
    # disagreement is which nanohematite or goethite variant won. Colouring per
    # entry renders that as speckle; colouring per family renders the geology.
    per_family: dict[str, int] = {}
    for v, c in zip(values, counts):
        per_family[fams.get(int(v), "unknown")] = per_family.get(fams.get(int(v), "unknown"), 0) + int(c)
    fam_order = [f for f, _ in sorted(per_family.items(), key=lambda kv: -kv[1])]
    shown_fams = fam_order[:LEGEND_LIMIT]

    # Two qualitative colormaps back to back give 40 distinct hues, comfortably
    # more than LEGEND_LIMIT, without inventing a palette.
    palette = [to_hex(c) for c in list(plt.get_cmap("tab20").colors) + list(plt.get_cmap("tab20b").colors)]
    fam_color = {f: palette[i % len(palette)] for i, f in enumerate(shown_fams)}

    # Each entry gets a tone of its family's hue. Capped at SHADES distinct
    # tones per family; rarer entries beyond that share the lightest.
    SHADES = 6
    entry_color: dict[int, str] = {}
    for f in shown_fams:
        members = [int(v) for v in values if fams.get(int(v), "unknown") == f]
        ramp = shades(fam_color[f], min(len(members), SHADES))
        for k, v in enumerate(members):
            entry_color[v] = ramp[min(k, len(ramp) - 1)]

    # Index 0 is the background (nothing identified); families past the legend
    # limit collapse onto a single "other" index.
    order_list = [int(v) for v in values if int(v) in entry_color]
    slot = {v: i + 1 for i, v in enumerate(order_list)}
    lut = np.zeros(int(values.max()) + 1 if values.size else 1, dtype=int)
    for v in values:
        lut[int(v)] = slot.get(int(v), len(order_list) + 1)

    indexed = lut[np.clip(ids.astype(int), 0, len(lut) - 1)]
    cmap = ListedColormap(["#101010"] + [entry_color[v] for v in order_list] + [OTHER])

    fig, ax = plt.subplots(figsize=(6, 6), dpi=140)
    ax.imshow(indexed, cmap=cmap, vmin=0, vmax=len(order_list) + 1, interpolation="nearest")
    ax.set_title(f"Group {group} mineral families", fontsize=11)
    ax.axis("off")

    # No legend inside the image: the results page renders one as a table, and
    # an external matplotlib legend widens the figure so much that the map
    # itself ends up far smaller than the band-depth map beside it.
    fig.tight_layout()
    fig.savefig(out / f"group{group}.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 6), dpi=140)
    image = ax.imshow(np.where(depth > 0, depth, np.nan), cmap="magma", interpolation="nearest")
    ax.set_title(f"Group {group} band depth", fontsize=11)
    ax.axis("off")
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(out / f"group{group}_depth.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)

    total = int(ids.size)
    # One entry per family, each carrying the library entries that fell into it,
    # so the map reads as geology while the table keeps every distinction.
    families = []
    for f in shown_fams:
        members = [{"id": int(v), "title": titles.get(int(v), f"id {v}"), "pixels": int(c),
                    "color": entry_color.get(int(v), fam_color[f])}
                   for v, c in zip(values, counts) if fams.get(int(v), "unknown") == f]
        families.append({"family": f, "pixels": per_family[f], "color": fam_color[f],
                         "materials": len(members), "members": members[:6]})
    stats = {
        "group": group,
        "classified": int((ids > 0).sum()),
        "total": total,
        "percent": round(100.0 * (ids > 0).sum() / total, 1) if total else 0.0,
        "materials": int(values.size),
        "families_total": len(per_family),
        "families": families,
    }
    if len(fam_order) > LEGEND_LIMIT:
        stats["other"] = {"pixels": sum(per_family[f] for f in fam_order[LEGEND_LIMIT:]),
                          "families": len(fam_order) - LEGEND_LIMIT, "color": OTHER}
    return stats


# Readable titles for Tetracorder's own colour products. The filenames are
# terse and the catalogue in cmds.color.support/AAA-product-list.txt gives no
# prose, so these are written here -- the only thing on this page that is.
PRODUCT_NAMES = {
    "1micron-minerals-a": ("Iron minerals, 1 µm",
        "Fe3+ and Fe2+ minerals separated by grain size: hematite and goethite "
        "coarse through nano, plus jarosite and the iron sulphates."),
    "2micron-mins-emit8": ("The EMIT eight, 2 µm",
        "The eight minerals EMIT reports, each pooling every library entry that "
        "counts as that mineral. Mixtures appear as additive colour."),
    "2micron-minerals": ("Clays, micas and carbonates, 2 µm",
        "The full 2 µm mineral set rather than the EMIT subset."),
    "2micron-minerals-b4": ("Clays, micas and carbonates, 2 µm (b4)",
        "A later recipe for the same 2 µm minerals, with more classes separated."),
    "2micron-minerals-detail2": ("2 µm minerals, detailed",
        "The 2 µm set again, split finer still."),
    "2micron-minerals-muscovite-comp": ("Muscovite composition",
        "Muscovite sorted by Al content, which tracks alteration temperature."),
    "hematite+goethite.grain.size-a": ("Hematite and goethite grain size",
        "Grain size alone, for the two commonest iron oxides."),
    "acid-minerals-buffering-minerals.a": ("Acid and buffering minerals",
        "Minerals that generate acid against those that neutralise it."),
    "prehnite-chlorite-mix+perchlorate": ("Prehnite, chlorite and perchlorate", ""),
    "pyroxene.2um.band.position": ("Pyroxene composition",
        "Band position at 2 µm, which tracks calcium and iron content."),
    "1.5um.broadfeats": ("Broad 1.5 µm features", ""),
    "water-a": ("Water", ""),
    "ree.b-g21": ("Rare-earth elements", ""),
    "snow-grain-size-water.a": ("Snow grain size and water", ""),
    "veg,water,snow": ("Vegetation, water and snow", ""),
    "veg-spectral-type": ("Vegetation spectral type", ""),
    "veg-water-rgb": ("Vegetation and water, false colour", ""),
    "vegetation-cover-a": ("Vegetation cover", ""),
    "red-edge-shift-a": ("Red-edge shift",
        "A stress indicator: where the vegetation red edge sits."),
    "organics-veg-2um-a": ("Organics and vegetation, 2 µm", ""),
}

PREFIX = "tet_color-results_"

LEADS = ("2micron-mins-emit8", "1micron-minerals-a")


def colour_products(tetracorder: Path, out: Path, width: int) -> list[dict]:
    """
    Copy Tetracorder's own colour products to the site and describe them.

    These are produced by every cube-mode run without asking -- ``cmd.runtet``
    calls ``cmds.color.support/make.color.results.all`` once the expert system
    is done -- so nothing here generates anything. It copies and measures.

    Each product comes in three forms. ``color.results`` is a dual panel: the
    colour map beside the same window in true colour. ``color.results+labels``
    is that with the published key concatenated underneath, which is the
    form worth showing. ``color.results.overlays`` composites the map over the
    grayscale base instead, which reads better on a small scene because the
    terrain shows through.

    Coverage is measured on the *left half* of the dual panel -- the colour map
    -- because the right half is the true-colour base and is never black. It is
    what lets the page rank the products that actually fired on this scene above
    the ones that came out empty.

    ``width`` is the scene's own width, from the ENVI header, and is what tells
    a dual panel from a single one. Guessing from the aspect ratio instead gets
    a 300x150 scene wrong every time, because a single panel of it is exactly as
    wide as it is tall twice over, which is also what a dual panel looks like.
    """
    plain = tetracorder / "color.results"
    if not plain.is_dir():
        return []

    dest = out / "color"
    dest.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import Image
    except ImportError:                                  # pragma: no cover
        Image = None

    def coverage(path: Path) -> float:
        """Fraction of the colour panel carrying an identification."""
        if Image is None:
            return -1.0
        try:
            a = np.asarray(Image.open(path).convert("RGB"))
        except OSError:
            return -1.0
        w = a.shape[1]
        left = a[:, :width] if w >= 2 * width else a
        return float((left.sum(axis=2) > 12).mean())

    stems = {s.name[len(PREFIX):-4] if s.name.startswith(PREFIX) else s.stem
             for s in plain.glob("*.png")}

    products = []
    for src in sorted(plain.glob("*.png")):
        stem = src.name[len(PREFIX):-4] if src.name.startswith(PREFIX) else src.stem

        # "<product>+bw" is the same map composited on the grayscale base. It is
        # a rendering of a product already in the list, and measuring it says
        # nothing -- the base is never black, so it scores ~100% whether or not
        # anything was identified. Dropped, so an empty product cannot lead the
        # page on the strength of its own backdrop.
        if stem.endswith("+bw") and stem[:-3] in stems:
            continue
        name, blurb = PRODUCT_NAMES.get(stem, (stem.replace(".", " "), ""))

        entry = {"key": stem, "name": name, "blurb": blurb,
                 "coverage": round(coverage(src), 4)}

        # Prefer the labelled composite; fall back to the bare product. The
        # +labels directory is not a strict superset -- a product whose key is
        # missing from AAA-product-list.txt never gets one.
        for role, folder, suffix in (
            ("labelled", "color.results+labels", "+labels.png"),
            ("plain", "color.results", ".png"),
            ("overlay", "color.results.overlays", "-overlay-on-bw.png"),
        ):
            cand = tetracorder / folder / f"{PREFIX}{stem}{suffix}"
            if not cand.is_file() and role == "labelled":
                # Several labelled files are written without the +labels suffix.
                cand = tetracorder / folder / f"{PREFIX}{stem}.png"
            if cand.is_file():
                target = dest / f"{stem}.{role}.png"
                shutil.copyfile(cand, target)
                entry[role] = f"color/{target.name}"

        products.append(entry)

    # The two leads first, then busiest first so the page ranks what fired above
    # what did not. Name breaks ties, for a stable order between runs.
    products.sort(key=lambda p: (LEADS.index(p["key"]) if p["key"] in LEADS else len(LEADS),
                                 -p["coverage"], p["name"]))
    return products


def describe_outputs(agg: Path) -> list[dict]:
    """
    Enumerate what the run actually produced, from the output tree itself.

    Worth stating plainly on the page, because there are two real products and
    one that only exists for the page:

      * Tetracorder writes a gzipped ENVI raster per material per quantity --
        .depth, .fit and .fd, each with its own .hdr. Thousands of them.
      * `tetrapy aggregate` reduces those to NetCDF (or GeoTIFF, if out_min is
        named .tif) -- the L2B mineral products.
      * results.json is neither. quicklook.py writes it from agg.nc purely to
        render this page.
    """
    out: list[dict] = []
    aggdir = agg.parent
    tetdir = aggdir.parent / "tetracorder"

    def mb(path: Path) -> str:
        return f"{path.stat().st_size / 1e6:.1f} MB"

    for name, what in (("agg.nc", "band depth and mineral ID per group"),
                       ("agg-uncert.nc", "band depth uncertainty and fit per group")):
        f = aggdir / name
        if f.exists():
            out.append({"name": name, "format": "NetCDF", "detail": mb(f), "what": what})

    if tetdir.is_dir():
        for suffix, what in ((".depth.gz", "depth of the matched absorption feature"),
                             (".fit.gz", "goodness of fit to the library spectrum"),
                             (".fd.gz", "fit times depth")):
            files = list(tetdir.glob(f"group.*/*{suffix}"))
            if files:
                total = sum(f.stat().st_size for f in files)
                out.append({"name": f"group.*/*{suffix}", "format": "ENVI (gzipped)",
                            "detail": f"{len(files):,} files, {total / 1e6:.1f} MB",
                            "what": what})

        # Tetracorder's own colour products. Listed with the rest because they
        # are real outputs of the run, not something this page generates -- a
        # reader who wants them is looking for a directory, not a page section.
        for folder, what in (
            ("color.results+labels", "colour mineral map with its published key"),
            ("color.results", "colour mineral map beside the true-colour base"),
            ("color.results.overlays", "colour mineral map over the grayscale base"),
            ("color.results-envi", "the same colour maps as ENVI rasters, for GIS"),
        ):
            files = list((tetdir / folder).glob("*")) if (tetdir / folder).is_dir() else []
            if files:
                total = sum(f.stat().st_size for f in files if f.is_file())
                out.append({"name": f"{folder}/", "format": "PNG" if "envi" not in folder else "ENVI",
                            "detail": f"{len(files):,} files, {total / 1e6:.1f} MB",
                            "what": what})

    out.append({"name": "results.json", "format": "JSON", "detail": "written by quicklook.py",
                "what": "summary of agg.nc for this page only - not a pipeline product"})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rfl", type=Path, required=True, help="input reflectance ENVI prefix")
    parser.add_argument("--agg", type=Path, required=True, help="aggregate product (agg.nc)")
    parser.add_argument("--reference", type=Path, default=Path("/root/tetrapy/data/v6.00a6.csv"))
    parser.add_argument("--out", type=Path, required=True, help="directory to write imagery into")
    parser.add_argument("--tetracorder", type=Path, default=None,
                        help="the tetracorder run directory, for its colour products")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    cube, wl, fields = read_envi(args.rfl)
    results = {"scene": render_rgb(cube, wl, args.out / "rfl_rgb.png"), "groups": []}
    results["scene"]["header"] = describe_header(fields)
    results["scene"]["description"] = fields.get("description", "").strip("{}").strip()

    # The reference matrix is generated by `tetrapy export-matrix` from
    # Tetracorder's own cmd.lib.setup file, so `title` is Tetracorder's TITLE=
    # field (the library record title) rather than anything invented here.
    # `id` is the name Tetracorder knows the material by and `path` is where it
    # writes the product, so carrying all three makes the provenance visible on
    # the page instead of leaving the reader to guess.
    reference = pd.read_csv(args.reference)
    meta = {
        int(r["index"]): {
            "title": str(r["title"]),
            "id": str(r["id"]),
            "path": str(r.get("path", "")),
            "library": str(r.get("library", "")),
            "record": str(r.get("record", "")),
            "url": str(r.get("url", "")) if isinstance(r.get("url", ""), str) else "",
        }
        for _, r in reference.iterrows()
    }
    titles = {k: v["title"] for k, v in meta.items()}
    fams = {k: family(v.get("path", "")) for k, v in meta.items()}

    # Imported here so a missing aggregate product still leaves the RGB behind.
    import xarray as xr

    with xr.open_dataset(args.agg) as ds:
        for group in (1, 2):
            ids, depth = f"group_{group}_mineral_id", f"group_{group}_band_depth"
            if ids not in ds:
                continue
            stats = render_group(ds[ids].values, ds[depth].values, titles, fams,
                                 group, args.out)
            for fam_row in stats["families"]:
                for m in fam_row["members"]:
                    m.update({k: v for k, v in meta.get(m["id"], {}).items() if k != "title"})
            results["groups"].append(stats)

    results["outputs"] = describe_outputs(args.agg)

    # Tetracorder's own colour products. Absent on a run that predates this, or
    # one where the base image could not be built, so the page treats an empty
    # list as "nothing to show" rather than an error.
    results["colour"] = (colour_products(args.tetracorder, args.out,
                                        int(fields["samples"]))
                         if args.tetracorder else [])

    (args.out / "results.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
