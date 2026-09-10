"""2x2 CONUS panel of hazard footprints at native (pre-resampling) resolution.

Every hazard in the ResiFlow pipeline gets resampled to a common 50m EPSG:9311
grid before use (align_hazard_rasters.py). This figure deliberately shows each
hazard BEFORE that step, at whatever resolution its own source data actually
came in at, reprojected to a shared display CRS (EPSG:9311) WITHOUT resampling
pixel size -- the point is to make the real heterogeneity in native input
resolution visually obvious, not to compare them on equal footing. Each panel
is zoomed to its OWN footprint (see plot_hazard_footprints_us_scale.py for the
companion figure at one shared CONUS-wide scale, for comparing relative size).

Panels:
  a. Hurricane Harvey flood depth  -- ~3 m (Harvey_Depths_3m_Final.gdb,
     CUAHSI/FEMA, public/open per source confirmation). 84 GB uncompressed;
     not tractable to read via /vsizip/ (confirmed: even a decimated read
     over the zip hangs past 90s -- the FileGDB raster driver needs an
     extracted copy). Requires
     inputs/multihazard_raw/Harvey_Depths_3m_Final.gdb extracted locally
     first (see the .zip alongside it).
  b. Earthquake -- USGS M9.0 Cascadia Subduction Zone scenario, event
     cszm9ensemble_se, the MEDIAN (50th percentile) of an ensemble of 30 M9
     rupture realizations (Frankel et al. 2018) -- not a single deterministic
     ShakeMap. Read directly from the user's downloaded shake_result.hdf
     (ShakeMap 4.x format, not a GeoTIFF) -- see
     _hazard_footprints_common.py's load_cascadia_pga_raw(). Confirmed the
     array's units are ln(g), not g (exp(raw max 0.327) = 1.387, matching the
     file's own dictionaries/info.json max_grid exactly) before using it.
  c. Co-seismic landslide -- Newmark PGD (cm) computed fresh for this figure
     from the SAME Cascadia M9 scenario as panel (b) + the USGS n10
     susceptibility layer, via resiflow.hazards.landslide_pgd's real HAZUS
     code (Eq. 4-14/4-15, Table 4-16) -- same method the pipeline uses for
     Mineral (scenario_param=501), just paired with Cascadia instead, since
     pairing landslide with a DIFFERENT earthquake than the one shown in
     panel (b) would be confusing. NOT a registered pipeline scenario_param
     (the pipeline only ever computes this for Mineral) -- see
     _hazard_footprints_common.py's load_cascadia_landslide_pgd_cm(). Using
     the same national n10 layer (not a PNW-specific product) is deliberate:
     it already carries real, much higher susceptibility across the
     Cascade/Coast/Olympic ranges than over New Madrid's flat terrain -- the
     steep-terrain signal comes from evaluating the right region, not a
     different susceptibility dataset. PGD has no native resolution of its
     own (both inputs must share a grid to combine); computed here on
     Cascadia PGA's own ~1.7-2.2km grid, the binding-constraint resolution,
     not susceptibility's finer ~90-110m.
  d. Winter Storm Jonas -- SNODAS snow depth, 2016-01-23 (~720-930 m, NSIDC
     G02158). Natively geographic (EPSG:4326, 30 arcsec) -- NOT reprojected
     from a NOHRSC sinusoidal grid as sometimes assumed; this CONUS GeoTIFF
     already reflects SNODAS's native grid, just parsed from NOHRSC's raw
     binary into a real GeoTIFF.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib.pyplot as plt

from _hazard_footprints_common import (
    CASCADIA_NOTE,
    CASCADIA_TITLE,
    INK_PRIMARY,
    INK_SECONDARY,
    SURFACE,
    draw_panel,
    load_cascadia_landslide_pgd_cm,
    load_cascadia_pga,
    load_conus_states,
    load_harvey,
    load_snodas_jonas,
)

OUT_DIR = Path(__file__).resolve().parent


def main() -> int:
    states = load_conus_states()
    fig, axes = plt.subplots(2, 2, figsize=(11, 9.5), facecolor=SURFACE)

    cas_arr, cas_transform, cas_res = load_cascadia_pga()
    draw_panel(
        axes[0, 1], letter="b", title=f"Earthquake -- {CASCADIA_TITLE}",
        arr=cas_arr, transform=cas_transform, native_res_m=cas_res, states=states,
        cmap="viridis", unit_label="PGA (g)", extra_note=CASCADIA_NOTE,
    )

    ls_arr, ls_transform, ls_res = load_cascadia_landslide_pgd_cm()
    draw_panel(
        axes[1, 0], letter="c", title="Co-seismic landslide -- Newmark PGD (same EQ)",
        arr=ls_arr, transform=ls_transform, native_res_m=ls_res, states=states,
        cmap="viridis", unit_label="Newmark PGD (cm)",
        extra_note="Computed fresh (not a registered pipeline scenario); on PGA's\n"
                    "~1.7-2.2km grid, the binding constraint vs. susceptibility's ~90-110m",
    )

    ws_arr, ws_transform, ws_res = load_snodas_jonas()
    draw_panel(
        axes[1, 1], letter="d", title="Winter Storm Jonas -- SNODAS snow depth",
        arr=ws_arr, transform=ws_transform, native_res_m=ws_res, states=states,
        cmap="viridis", unit_label="Snow depth (m)", vmax=1.2,
    )

    ax = axes[0, 0]
    try:
        h_arr, h_transform, scale = load_harvey()
        draw_panel(
            ax, letter="a", title="Hurricane Harvey -- flood depth",
            arr=h_arr, transform=h_transform, native_res_m=3.0, states=states,
            cmap="viridis", unit_label="Depth (m)",
            extra_note=f"display decimated {scale}x for tractability (84 GB source)",
        )
    except FileNotFoundError:
        ax.text(
            0.5, 0.5,
            "Harvey panel pending:\ninputs/multihazard_raw/Harvey_Depths_3m_Final.gdb.zip\n"
            "not yet extracted (84 GB uncompressed).\nRe-run this script once extraction completes.",
            ha="center", va="center", transform=ax.transAxes, fontsize=9.5, color=INK_SECONDARY,
        )
        ax.set_title("(a) Hurricane Harvey -- flood depth", fontsize=12.5,
                     color=INK_PRIMARY, fontweight="bold", loc="left")
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

    fig.suptitle(
        "CONUS hazard footprints at native (pre-resampling) resolution",
        fontsize=15.5, color=INK_PRIMARY, x=0.02, ha="left", y=0.99, fontweight="bold",
    )
    fig.text(
        0.02, 0.955,
        "Each panel reprojected to a shared display CRS (EPSG:9311) preserving native pixel size -- "
        "not resampled to the model's common 50 m grid.",
        fontsize=10, color=INK_SECONDARY, ha="left", va="top",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))

    fig.savefig(OUT_DIR / "hazard_footprints_native_res.pdf", bbox_inches="tight")
    fig.savefig(OUT_DIR / "hazard_footprints_native_res.png", dpi=200, bbox_inches="tight")
    print("Wrote", OUT_DIR / "hazard_footprints_native_res.pdf")
    print("Wrote", OUT_DIR / "hazard_footprints_native_res.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
