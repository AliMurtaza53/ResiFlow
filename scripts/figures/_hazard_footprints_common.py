"""Shared loading/reprojection/styling for the hazard-footprint figure scripts.

Used by both plot_hazard_footprints_native_res.py (each panel zoomed to its
own footprint) and plot_hazard_footprints_us_scale.py (every panel sharing
one CONUS-wide extent, for comparing relative hazard SIZE). Factored out so
the two figures can't drift apart on what each hazard's source file/label/
caveat actually is -- see this project's own history of exactly that kind of
drift (finale_hazards.py, docs/PARAMETER_AUDIT_CHECKLIST.md) for why this
matters enough to bother with a shared module for two scripts.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling

warnings.simplefilter("ignore")

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "inputs" / "multihazard_raw"
DISPLAY_CRS = "EPSG:9311"

_SRC = REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Shared style -- define once, reuse across every panel of both figures.
FONT_FAMILY = ["Lato", "Arial", "sans-serif"]
INK_PRIMARY = "#1a1a1a"
INK_SECONDARY = "#5c5859"
STATE_LINE = "#8a8a8a"
SURFACE = "#ffffff"
plt.rcParams["font.family"] = FONT_FAMILY


def load_conus_states(
    county_shp: Path = Path(r"C:\Users\akothaw\Desktop\data\faf5_data\county_shp\tl_2022_us_county.shp"),
) -> gpd.GeoDataFrame:
    """CONUS state boundaries, dissolved from the TIGER county shapefile.

    Avoids a fresh download -- the county file is already on disk locally
    for the FAF5 pipeline. Excludes AK/HI/territories (FIPS 02, 15, 60, 66,
    69, 72, 78) since every panel here is a CONUS-regional event.
    """
    counties = gpd.read_file(county_shp)
    excluded_fips = {"02", "15", "60", "66", "69", "72", "78"}
    conus = counties[~counties["STATEFP"].isin(excluded_fips)]
    states = conus.dissolve(by="STATEFP")
    return states.to_crs(DISPLAY_CRS)


def reproject_preserve_native_res(
    src_path: Path | None,
    dst_crs: str,
    *,
    band: int = 1,
    src_array: np.ndarray | None = None,
    src_transform=None,
    src_crs_override=None,
    src_nodata_override=None,
) -> tuple[np.ndarray, "rasterio.Affine", float]:
    """Reproject one band to dst_crs, preserving native pixel density.

    calculate_default_transform picks an output resolution that matches the
    source's own pixel density (not a resampling target) -- this is what
    makes coarser sources look visibly blockier than finer ones once both
    are in the same display CRS. Nearest-neighbor only (never
    smooth/bilinear -- that would blur exactly the cell-size information
    these figures exist to show).

    If src_array/src_transform/src_crs_override are given, reprojects that
    in-memory array instead of re-reading src_path (used for Harvey, and for
    SNODAS's pre-crop). Returns (reprojected_array, dst_transform,
    native_res_m) where native_res_m is the approximate ground resolution
    of the ORIGINAL source (for the text annotation), not the display array.
    """
    if src_array is None:
        with rasterio.open(src_path) as src:
            arr = src.read(band).astype("float64")
            nodata = src.nodata
            if nodata is not None and np.isfinite(nodata):
                arr = np.where(arr == nodata, np.nan, arr)
            src_crs = src.crs
            transform = src.transform
            width, height = src.width, src.height
            bounds = src.bounds
    else:
        arr = src_array
        nodata = src_nodata_override
        if nodata is not None and np.isfinite(nodata):
            arr = np.where(arr == nodata, np.nan, arr)
        src_crs = src_crs_override
        transform = src_transform
        height, width = arr.shape
        bounds = rasterio.coords.BoundingBox(
            *rasterio.transform.array_bounds(height, width, transform)
        )

    dst_transform, dst_width, dst_height = calculate_default_transform(
        src_crs, dst_crs, width, height, *bounds
    )
    dst_arr = np.full((dst_height, dst_width), np.nan, dtype="float64")
    reproject(
        source=arr,
        destination=dst_arr,
        src_transform=transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        resampling=Resampling.nearest,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    native_res_m = float(abs(dst_transform.a))
    return dst_arr, dst_transform, native_res_m


def array_extent_9311(transform, height: int, width: int) -> tuple[float, float, float, float]:
    left, top = transform * (0, 0)
    right, bottom = transform * (width, height)
    return (left, right, bottom, top)


CASCADIA_HDF = Path(r"C:\Users\akothaw\Desktop\data\Cascadia9_shake_result.hdf")
CASCADIA_TITLE = "M9.0 Cascadia Subduction Zone (median ensemble)"
CASCADIA_NOTE = (
    "USGS scenario cszm9ensemble_se -- median of 30 M9 rupture realizations\n"
    "(Frankel et al. 2018), not a single deterministic ShakeMap"
)
CASCADIA_MAGNITUDE = 9.0

# HAZUS Newmark PGD inputs matching the real pipeline's own
# compute_landslide_pgd.py invocation for this susceptibility product (see
# experiments/conus_multihazard/hopper/submit_align_hazards.slurm):
# n10's count is 0..81 (9x9 10m sub-cells per 90m cell).
SUSCEPTIBILITY_MAX_COUNT = 81.0


def load_cascadia_pga_raw() -> tuple[np.ndarray, "rasterio.Affine", str]:
    """Read the Cascadia M9 ensemble ShakeMap's PGA grid straight from its
    shake_result.hdf (ShakeMap 4.x format -- not a GeoTIFF, so no rasterio
    path opens it directly). Grid geometry and CRS come from the dataset's
    own attrs (xmin/xmax/ymin/ymax/dx/dy/nx/ny, EPSG:4326 -- ShakeMap grids
    are always geographic). Confirmed the array's ``units: ln(g)`` attr is
    literal (exp(raw max 0.327) = 1.387, matching dictionaries/info.json's
    own reported max_grid exactly) -- most other ShakeMap-derived PGA
    rasters in this project were pre-converted to g by an upstream prep
    script; this one hasn't been, so the exp() happens here instead.
    """
    import h5py

    with h5py.File(CASCADIA_HDF, "r") as f:
        ds = f["arrays/imts/GREATER_OF_TWO_HORIZONTAL/PGA/mean"]
        raw_ln_g = ds[()]
        xmin, xmax = float(ds.attrs["xmin"]), float(ds.attrs["xmax"])
        ymin, ymax = float(ds.attrs["ymin"]), float(ds.attrs["ymax"])
        dx, dy = float(ds.attrs["dx"]), float(ds.attrs["dy"])

    pga_g = np.exp(raw_ln_g).astype("float64")
    # Standard north-up affine: row 0 at ymax, column 0 at xmin.
    transform = rasterio.Affine(dx, 0.0, xmin, 0.0, -dy, ymax)
    return pga_g, transform, "EPSG:4326"


def load_cascadia_pga() -> tuple[np.ndarray, "rasterio.Affine", float]:
    pga_g, transform, crs = load_cascadia_pga_raw()
    return reproject_preserve_native_res(
        None, DISPLAY_CRS, src_array=pga_g, src_transform=transform, src_crs_override=crs,
    )


def load_cascadia_landslide_pgd_cm() -> tuple[np.ndarray, "rasterio.Affine", None]:
    """Co-seismic Newmark PGD (cm) from the Cascadia M9 scenario, computed
    fresh for this figure -- NOT a registered pipeline scenario_param (the
    pipeline only ever pairs landslide with Mineral, scenario_param=501), but
    the exact same method: resiflow.hazards.landslide_pgd's HAZUS Newmark
    code (Eq. 4-14/4-15, Table 4-16), same national susceptibility source
    (USGS n10) and --susceptibility-max-count=81 the real pipeline uses for
    Mineral. Using the SAME national layer here, just recomputed over
    Cascadia's own footprint, is deliberate -- n10 already carries real,
    much higher susceptibility values across the Cascade/Coast/Olympic
    ranges than it does over New Madrid's flat Mississippi embayment; the
    steep-terrain signal comes from evaluating the right region, not from
    swapping to a different susceptibility product.

    PGD has no native resolution of its own -- both inputs have to share one
    grid to combine pixel-by-pixel. Resamples susceptibility (natively
    ~100m) DOWN onto Cascadia PGA's own native grid (~1.7-2.2km) via
    area-averaging, since PGA is the coarser/binding-constraint input.
    """
    from resiflow.hazards.landslide_pgd import bin_fractional_susceptibility_to_class, expected_pgd_mm

    pga, pga_transform, pga_crs = load_cascadia_pga_raw()
    pga_shape = pga.shape

    susc_path = RAW / "landslide" / "n10_susc" / "n10_conus.tif"
    with rasterio.open(susc_path) as susc_ds:
        susc_on_pga_grid = np.full(pga_shape, np.nan, dtype="float64")
        susc_nodata = susc_ds.nodata
        reproject(
            source=rasterio.band(susc_ds, 1),
            destination=susc_on_pga_grid,
            src_transform=susc_ds.transform,
            src_crs=susc_ds.crs,
            dst_transform=pga_transform,
            dst_crs=pga_crs,
            src_nodata=susc_nodata,
            dst_nodata=np.nan,
            resampling=Resampling.average,
        )

    susc_class = bin_fractional_susceptibility_to_class(susc_on_pga_grid, SUSCEPTIBILITY_MAX_COUNT)
    susc_class = np.where(np.isnan(susc_on_pga_grid), np.nan, susc_class)
    pgd_mm = expected_pgd_mm(susc_class, pga, magnitude=CASCADIA_MAGNITUDE)
    pgd_cm = pgd_mm.astype("float64") / 10.0
    pgd_cm = np.where(np.isnan(pga) | np.isnan(susc_class), np.nan, pgd_cm)

    arr9311, transform9311, res_m = reproject_preserve_native_res(
        None, DISPLAY_CRS, src_array=pgd_cm, src_transform=pga_transform, src_crs_override=pga_crs,
    )
    return arr9311, transform9311, res_m


def load_snodas_jonas() -> tuple[np.ndarray, "rasterio.Affine", float]:
    """SNODAS Jonas, cropped to the Mid-Atlantic/Northeast corridor it actually hit.

    The raw CONUS grid has nonzero background snow almost everywhere in
    January, not just where Jonas fell, and has an unmasked sentinel value
    (32767 raw -> 32.767 m after scaling) at some pixels -- both handled here.
    """
    path = RAW / "winter_storm" / "snodas_jan2016" / "SNODAS_snowdepth_m_20160123_conus.tif"
    with rasterio.open(path) as src:
        raw = src.read(1).astype("float64")
        transform = src.transform
        crs = src.crs
    raw = np.where((raw < 0) | (raw > 2.0), np.nan, raw)
    lon_min, lon_max, lat_min, lat_max = -80.5, -69.5, 36.5, 43.5
    col_min, row_max = ~transform * (lon_min, lat_min)
    col_max, row_min = ~transform * (lon_max, lat_max)
    row_min, row_max = int(max(0, row_min)), int(min(raw.shape[0], row_max))
    col_min, col_max = int(max(0, col_min)), int(min(raw.shape[1], col_max))
    cropped = raw[row_min:row_max, col_min:col_max]
    cropped_transform = transform * rasterio.Affine.translation(col_min, row_min)
    return reproject_preserve_native_res(
        None, DISPLAY_CRS, src_array=cropped, src_transform=cropped_transform,
        src_crs_override=crs,
    )


def load_harvey(target_px: int = 1200) -> tuple[np.ndarray, "rasterio.Affine", int]:
    """Harvey flood depth, decimated for tractability (84 GB source).

    Uses Resampling.average (not nearest) for the decimated read: a plain
    nearest-neighbor decimation of a flood-depth grid that has real dry
    parcels interspersed with flooded ones at 3m scale picks whichever
    single native pixel lands on each decimated sample point, which produces
    a speckled/holey "cloud" look at 100x+ decimation even though the true
    flood extent is much more continuous than that -- confirmed visually
    2026-09-09. Resampling.max would be the more direct fix (fill each block
    with its worst-case depth) but rasterio only allows it for warp
    operations, not plain reads; Resampling.average is nodata-aware (this
    source has nodata properly registered) and achieves the same practical
    goal -- any block with at least one flooded native pixel gets a
    representative nonzero depth instead of a hole, at the cost of averaging
    down peak depths within a block rather than preserving the max.

    Returns (reprojected_array, dst_transform, decimation_factor). Raises
    FileNotFoundError if inputs/multihazard_raw/Harvey_Depths_3m_Final.gdb
    hasn't been extracted from its .zip yet (84 GB uncompressed -- caller
    should catch this and render a placeholder rather than fail outright).
    """
    gdb_path = RAW / "Harvey_Depths_3m_Final.gdb"
    if not gdb_path.exists():
        raise FileNotFoundError(
            f"{gdb_path} not extracted yet -- unzip Harvey_Depths_3m_Final.gdb.zip first"
        )
    with rasterio.open(gdb_path) as src:
        scale = max(1, min(src.width, src.height) // target_px)
        out_shape = (max(1, src.height // scale), max(1, src.width // scale))
        arr = src.read(1, out_shape=out_shape, resampling=Resampling.average).astype("float64")
        nodata = src.nodata
        if nodata is not None and np.isfinite(nodata):
            arr = np.where(arr >= nodata * 0.99, np.nan, arr)
        arr = np.where((arr < 0) | (arr > 15), np.nan, arr)
        h_arr, h_transform, _ = reproject_preserve_native_res(
            None, DISPLAY_CRS, src_array=arr,
            src_transform=src.transform * rasterio.Affine.scale(scale, scale),
            src_crs_override=src.crs,
        )
    return h_arr, h_transform, scale


def draw_panel(
    ax,
    *,
    letter: str,
    title: str,
    arr: np.ndarray,
    transform,
    native_res_m: float | None,
    states: gpd.GeoDataFrame,
    cmap: str,
    unit_label: str,
    vmin: float | None = None,
    vmax: float | None = None,
    zoom_pad_frac: float = 0.15,
    fixed_extent: tuple[float, float, float, float] | None = None,
    extra_note: str | None = None,
    res_note_override: str | None = None,
):
    """Draw one panel. fixed_extent (left, right, bottom, top), if given,
    overrides the per-raster zoom -- used by the US-scale figure so every
    panel shares one CONUS-wide extent instead of zooming to its own footprint.
    """
    height, width = arr.shape
    extent = array_extent_9311(transform, height, width)
    left, right, bottom, top = extent

    finite = arr[np.isfinite(arr)]
    if vmin is None:
        vmin = 0.0
    if vmax is None:
        # A field that's genuinely zero almost everywhere (e.g. Newmark PGD --
        # zero unless shaking exceeds a susceptibility-class-specific
        # threshold, true for >99% of pixels here) makes the 99.5th
        # percentile of ALL values collapse to ~0, which makes vmin==vmax
        # degenerate and matplotlib silently auto-expands it to some
        # arbitrary symmetric range (confirmed: produced a -0.1..0.1 colorbar
        # for a quantity that's strictly >=0). Use the percentile of the
        # NONZERO values instead when there are enough of them to be
        # meaningful, so the color scale reflects the real dynamic range of
        # what's actually displayed.
        nonzero = finite[finite > 0]
        if nonzero.size >= 10:
            vmax = float(np.nanpercentile(nonzero, 99.5))
        elif finite.size:
            vmax = float(np.nanpercentile(finite, 99.5))
        else:
            vmax = 1.0
        if vmax <= vmin:
            vmax = vmin + 1.0

    if fixed_extent is not None:
        xlim = (fixed_extent[0], fixed_extent[1])
        ylim = (fixed_extent[2], fixed_extent[3])
    else:
        pad_x = (right - left) * zoom_pad_frac
        pad_y = (top - bottom) * zoom_pad_frac
        xlim = (left - pad_x, right + pad_x)
        ylim = (bottom - pad_y, top + pad_y)

    states.boundary.plot(ax=ax, color=STATE_LINE, linewidth=0.5, zorder=1)
    im = ax.imshow(
        arr, extent=(left, right, bottom, top), origin="upper",
        cmap=cmap, vmin=vmin, vmax=vmax, zorder=2, interpolation="nearest",
    )
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_aspect("equal")

    ax.set_title(f"({letter}) {title}", fontsize=12.5, color=INK_PRIMARY,
                 fontweight="bold", loc="left")

    if res_note_override is not None:
        note = res_note_override
    elif native_res_m is not None:
        note = f"~{native_res_m:,.0f} m native grid spacing" if native_res_m >= 100 else \
               f"~{native_res_m:.1f} m native grid spacing"
    else:
        note = ""
    if extra_note:
        note = f"{note}\n{extra_note}" if note else extra_note
    if note:
        ax.text(
            0.02, 0.02, note, transform=ax.transAxes, fontsize=8.5,
            color=INK_SECONDARY, ha="left", va="bottom",
            bbox=dict(boxstyle="round,pad=0.25", facecolor=SURFACE, edgecolor="none", alpha=0.85),
        )

    cbar = plt.colorbar(im, ax=ax, orientation="vertical", fraction=0.04, pad=0.02, shrink=0.75)
    cbar.set_label(unit_label, fontsize=9, color=INK_SECONDARY)
    cbar.ax.tick_params(labelsize=8, colors=INK_SECONDARY)
    cbar.outline.set_visible(False)
    return im
