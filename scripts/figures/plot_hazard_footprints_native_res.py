"""2x2 CONUS panel of hazard footprints at native (pre-resampling) resolution.

Every hazard in the ResiFlow pipeline gets resampled to a common 50m EPSG:9311
grid before use (align_hazard_rasters.py). This figure deliberately shows each
hazard BEFORE that step, at whatever resolution its own source data actually
came in at, reprojected to a shared display CRS (EPSG:9311) WITHOUT resampling
pixel size -- the point is to make the real heterogeneity in native input
resolution visually obvious, not to compare them on equal footing.

Panels:
  a. Hurricane Harvey flood depth  -- ~3 m (Harvey_Depths_3m_Final.gdb,
     CUAHSI/FEMA, public). 84 GB uncompressed; not tractable to read via
     /vsizip/ (confirmed: even a decimated read over the zip hangs past 90s --
     the FileGDB raster driver needs an extracted copy). Requires
     inputs/multihazard_raw/Harvey_Depths_3m_Final.gdb extracted locally
     first (see the .zip alongside it).
  b. Earthquake -- New Madrid M7.5 scenario ShakeMap PGA (~1.7-2.1 km,
     USGS ShakeMap Scenario Catalog, earthquake_new_madrid_m75_scenario --
     the only New Madrid scenario wired into the pipeline, no ambiguity).
  c. Landslide -- the Mineral, VA (2011, M5.8) ShakeMap PGA (~1.5-1.9 km),
     NOT the Newmark PGD output. PGD has no native resolution of its own --
     scripts/compute_landslide_pgd.py only ever runs on the ALIGNED 50m
     susceptibility+PGA rasters (see its own docstring/example paths), so
     showing "PGD at native resolution" isn't a meaningful thing to do. PGA
     is also the real binding constraint: the susceptibility layer feeding
     the same calculation is far finer (~90-110m) but the PGA driving the
     Newmark displacement estimate is what actually limits spatial detail.
  d. Winter Storm Jonas -- SNODAS snow depth, 2016-01-23 (~720-930 m, NSIDC
     G02158). Natively geographic (EPSG:4326, 30 arcsec) -- NOT reprojected
     from a NOHRSC sinusoidal grid as sometimes assumed; this CONUS GeoTIFF
     already reflects SNODAS's native grid, just parsed from NOHRSC's raw
     binary into a real GeoTIFF. The raw file has an unmasked sentinel
     (32767 raw -> 32.767 m after scaling) at some pixels -- clipped here at
     a physically-plausible max, not treated as real depth.

Style: Urban Institute-inspired (shared with scripts/visualizations/
viz_data_loaders.py) -- but this is a standalone figure script, not
dependent on that module, since it needs raster/basemap handling
viz_data_loaders.py doesn't have.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from rasterio.warp import calculate_default_transform, reproject, Resampling

warnings.simplefilter("ignore")

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "inputs" / "multihazard_raw"
OUT_DIR = Path(__file__).resolve().parent
DISPLAY_CRS = "EPSG:9311"

# Shared style -- define once, reuse across all four panels.
_FONT_FAMILY = ["Lato", "Arial", "sans-serif"]
_INK_PRIMARY = "#1a1a1a"
_INK_SECONDARY = "#5c5859"
_STATE_LINE = "#8a8a8a"
_SURFACE = "#ffffff"
plt.rcParams["font.family"] = _FONT_FAMILY


def load_conus_states(county_shp: Path) -> gpd.GeoDataFrame:
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
    src_path: Path,
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
    are in the same display CRS, which is the entire point of this figure.
    Nearest-neighbor only (never smooth/bilinear -- that would blur exactly
    the cell-size information this figure exists to show).

    If src_array/src_transform/src_crs_override are given, reprojects that
    in-memory array instead of re-reading src_path (used for Harvey, where
    the source read already happened with its own windowing logic).
    Returns (reprojected_array, dst_transform, native_res_m) where
    native_res_m is the approximate ground resolution of the ORIGINAL
    source (for the text annotation), not the display array.
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
        bounds = rasterio.transform.array_bounds(height, width, transform)
        bounds = rasterio.coords.BoundingBox(*bounds)

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
    # Approximate native ground resolution in meters (for the text label),
    # via the same transform rasterio just derived for the display array --
    # its pixel size directly reflects the source's own density.
    native_res_m = float(abs(dst_transform.a))
    return dst_arr, dst_transform, native_res_m


def array_extent_9311(transform, height: int, width: int) -> tuple[float, float, float, float]:
    left, top = transform * (0, 0)
    right, bottom = transform * (width, height)
    return (left, right, bottom, top)


def draw_panel(
    ax,
    *,
    letter: str,
    title: str,
    arr: np.ndarray,
    transform,
    native_res_m: float,
    states: gpd.GeoDataFrame,
    cmap: str,
    unit_label: str,
    vmin: float | None = None,
    vmax: float | None = None,
    zoom_pad_frac: float = 0.15,
    extra_note: str | None = None,
):
    height, width = arr.shape
    extent = array_extent_9311(transform, height, width)
    left, right, bottom, top = extent

    finite = arr[np.isfinite(arr)]
    if vmin is None:
        vmin = 0.0
    if vmax is None:
        vmax = float(np.nanpercentile(finite, 99.5)) if finite.size else 1.0

    # zoom to the raster's own footprint, not full CONUS
    pad_x = (right - left) * zoom_pad_frac
    pad_y = (top - bottom) * zoom_pad_frac
    xlim = (left - pad_x, right + pad_x)
    ylim = (bottom - pad_y, top + pad_y)

    states.boundary.plot(ax=ax, color=_STATE_LINE, linewidth=0.5, zorder=1)
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

    ax.set_title(f"({letter}) {title}", fontsize=12.5, color=_INK_PRIMARY,
                 fontweight="bold", loc="left")

    res_label = f"~{native_res_m:,.0f} m native grid spacing" if native_res_m >= 100 else \
                f"~{native_res_m:.1f} m native grid spacing"
    note = res_label if extra_note is None else f"{res_label}\n{extra_note}"
    ax.text(
        0.02, 0.02, note, transform=ax.transAxes, fontsize=8.5,
        color=_INK_SECONDARY, ha="left", va="bottom",
        bbox=dict(boxstyle="round,pad=0.25", facecolor=_SURFACE, edgecolor="none", alpha=0.85),
    )

    cbar = plt.colorbar(im, ax=ax, orientation="vertical", fraction=0.04, pad=0.02, shrink=0.75)
    cbar.set_label(unit_label, fontsize=9, color=_INK_SECONDARY)
    cbar.ax.tick_params(labelsize=8, colors=_INK_SECONDARY)
    cbar.outline.set_visible(False)
    return im


def main() -> int:
    county_shp = Path(r"C:\Users\akothaw\Desktop\data\faf5_data\county_shp\tl_2022_us_county.shp")
    states = load_conus_states(county_shp)

    fig, axes = plt.subplots(2, 2, figsize=(11, 9.5), facecolor=_SURFACE)

    # --- (b) New Madrid scenario ShakeMap PGA ---
    nm_path = RAW / "earthquake" / "new_madrid_scenario" / "pga_g.tif"
    nm_arr, nm_transform, nm_res = reproject_preserve_native_res(nm_path, DISPLAY_CRS)
    draw_panel(
        axes[0, 1], letter="b", title="Earthquake -- New Madrid M7.5 scenario",
        arr=nm_arr, transform=nm_transform, native_res_m=nm_res, states=states,
        cmap="viridis", unit_label="PGA (g)",
    )

    # --- (c) Mineral, VA ShakeMap PGA (co-seismic landslide driver) ---
    mn_path = RAW / "earthquake" / "mineral_shakemap" / "pga_g.tif"
    mn_arr, mn_transform, mn_res = reproject_preserve_native_res(mn_path, DISPLAY_CRS)
    draw_panel(
        axes[1, 0], letter="c", title="Co-seismic landslide -- Mineral VA ShakeMap PGA",
        arr=mn_arr, transform=mn_transform, native_res_m=mn_res, states=states,
        cmap="viridis", unit_label="PGA (g)",
        extra_note="Newmark PGD has no native res. (aligned-grid-only product);\nsusceptibility input is ~90-110 m, PGA is the binding constraint",
    )

    # --- (d) Winter Storm Jonas SNODAS ---
    ws_path = RAW / "winter_storm" / "snodas_jan2016" / "SNODAS_snowdepth_m_20160123_conus.tif"
    with rasterio.open(ws_path) as src:
        raw = src.read(1).astype("float64")
        transform = src.transform
        crs = src.crs
    raw = np.where((raw < 0) | (raw > 2.0), np.nan, raw)  # drop the unmasked 32.767 sentinel
    # Crop to the Jonas-affected Mid-Atlantic/Northeast corridor (lon/lat) --
    # the raw CONUS grid has nonzero background snow almost everywhere in
    # January, not just where Jonas actually fell.
    lon_min, lon_max, lat_min, lat_max = -80.5, -69.5, 36.5, 43.5
    col_min, row_max = ~transform * (lon_min, lat_min)
    col_max, row_min = ~transform * (lon_max, lat_max)
    row_min, row_max = int(max(0, row_min)), int(min(raw.shape[0], row_max))
    col_min, col_max = int(max(0, col_min)), int(min(raw.shape[1], col_max))
    cropped = raw[row_min:row_max, col_min:col_max]
    cropped_transform = transform * rasterio.Affine.translation(col_min, row_min)
    ws_arr, ws_transform, ws_res = reproject_preserve_native_res(
        None, DISPLAY_CRS, src_array=cropped, src_transform=cropped_transform,
        src_crs_override=crs, src_nodata_override=None,
    )
    draw_panel(
        axes[1, 1], letter="d", title="Winter Storm Jonas -- SNODAS snow depth",
        arr=ws_arr, transform=ws_transform, native_res_m=ws_res, states=states,
        cmap="viridis", unit_label="Snow depth (m)", vmax=1.2,
    )

    # --- (a) Harvey flood depth (requires local extraction, see docstring) ---
    harvey_gdb = RAW / "Harvey_Depths_3m_Final.gdb"
    ax = axes[0, 0]
    if harvey_gdb.exists():
        try:
            with rasterio.open(harvey_gdb) as src:
                # Decimated read for tractability (84 GB source) -- the
                # DISPLAYED grid is decimated; the ANNOTATED resolution
                # reflects the true native ~3 m grid from the source header,
                # not what's actually rendered. See module docstring.
                target = 1200
                scale = max(1, min(src.width, src.height) // target)
                out_shape = (max(1, src.height // scale), max(1, src.width // scale))
                arr = src.read(1, out_shape=out_shape, resampling=Resampling.nearest).astype("float64")
                nodata = src.nodata
                if nodata is not None and np.isfinite(nodata):
                    arr = np.where(arr == nodata, np.nan, arr)
                arr = np.where((arr < 0) | (arr > 15), np.nan, arr)
                h_arr, h_transform, _ = reproject_preserve_native_res(
                    None, DISPLAY_CRS, src_array=arr,
                    src_transform=src.transform * rasterio.Affine.scale(scale, scale),
                    src_crs_override=src.crs,
                )
            draw_panel(
                ax, letter="a", title="Hurricane Harvey -- flood depth",
                arr=h_arr, transform=h_transform, native_res_m=3.0, states=states,
                cmap="viridis", unit_label="Depth (m)",
                extra_note=f"display decimated {scale}x for tractability (84 GB source)",
            )
        except Exception as exc:
            ax.text(0.5, 0.5, f"Harvey panel failed:\n{exc}", ha="center", va="center",
                    transform=ax.transAxes, fontsize=9, color="crimson")
            ax.set_title("(a) Hurricane Harvey -- flood depth", fontsize=12.5,
                         color=_INK_PRIMARY, fontweight="bold", loc="left")
    else:
        ax.text(
            0.5, 0.5,
            "Harvey panel pending:\ninputs/multihazard_raw/Harvey_Depths_3m_Final.gdb.zip\n"
            "not yet extracted (84 GB uncompressed).\nRe-run this script once extraction completes.",
            ha="center", va="center", transform=ax.transAxes, fontsize=9.5, color=_INK_SECONDARY,
        )
        ax.set_title("(a) Hurricane Harvey -- flood depth", fontsize=12.5,
                     color=_INK_PRIMARY, fontweight="bold", loc="left")
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

    fig.suptitle(
        "CONUS hazard footprints at native (pre-resampling) resolution",
        fontsize=15.5, color=_INK_PRIMARY, x=0.02, ha="left", y=0.99, fontweight="bold",
    )
    fig.text(
        0.02, 0.955,
        "Each panel reprojected to a shared display CRS (EPSG:9311) preserving native pixel size -- "
        "not resampled to the model's common 50 m grid.",
        fontsize=10, color=_INK_SECONDARY, ha="left", va="top",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))

    fig.savefig(OUT_DIR / "hazard_footprints_native_res.pdf", bbox_inches="tight")
    fig.savefig(OUT_DIR / "hazard_footprints_native_res.png", dpi=200, bbox_inches="tight")
    print("Wrote", OUT_DIR / "hazard_footprints_native_res.pdf")
    print("Wrote", OUT_DIR / "hazard_footprints_native_res.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
