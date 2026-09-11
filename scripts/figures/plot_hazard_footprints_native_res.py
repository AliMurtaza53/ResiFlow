"""4x2 CONUS panel of hazard footprints at native (pre-resampling) resolution.

Every hazard in the ResiFlow pipeline gets resampled to a common 50m EPSG:9311
grid before use (align_hazard_rasters.py). This figure deliberately shows each
hazard BEFORE that step, at whatever resolution its own source data actually
came in at, reprojected to a shared display CRS (EPSG:9311) WITHOUT resampling
pixel size -- the point is to make the real heterogeneity in native input
resolution visually obvious, not to compare them on equal footing. Each panel
is zoomed to its OWN footprint (see plot_hazard_footprints_us_scale.py for the
companion figure at one shared CONUS-wide scale, for comparing relative size).

4 rows (hazard type) x 2 columns (two contrasting real events per type):

  FLOOD
    a. Hurricane Harvey flood depth -- ~3 m (Harvey_Depths_3m_Final.gdb,
       Houston/Harris County TX, CUAHSI/FEMA, public/open per source
       confirmation). 84 GB uncompressed; not tractable to read via
       /vsizip/ (confirmed: even a decimated read over the zip hangs past
       90s) -- requires inputs/multihazard_raw/Harvey_Depths_3m_Final.gdb
       extracted locally first. Registered pipeline scenario 304
       (flood_harvey_houston).
    b. Hurricane Sandy coastal flood depth -- ~3 m native (4 FEMA
       state-clipped depth grids for CT/NJ/NY/RI, mosaicked onto one
       EPSG:9311 grid via scripts/prepare_sandy_depths.py's
       build_sandy_mosaic(), decimated here for display). Registered
       pipeline scenario 305 (flood_sandy_northeast).

  EARTHQUAKE
    c. USGS Earthquake Scenarios M7.5 New Madrid central fault (BSSC2014)
       -- registered pipeline scenario 403. Labeled "Missouri 1811-12*"
       with an explicit caveat (see NEW_MADRID_NOTE): this is a physically
       modeled SCENARIO on a real fault, not an actual ShakeMap from the
       real 1811-12 earthquakes (which predate ShakeMap-quality
       instrumentation).
    d. USGS M9.0 Cascadia Subduction Zone scenario, event cszm9ensemble_se,
       the MEDIAN (50th percentile) of an ensemble of 30 M9 rupture
       realizations (Frankel et al. 2018) -- not a single deterministic
       ShakeMap. Read directly from the user's downloaded shake_result.hdf
       (ShakeMap 4.x format, not a GeoTIFF) -- see
       _hazard_footprints_common.py's load_cascadia_pga_raw(). Confirmed
       the array's units are ln(g), not g (exp(raw max 0.327) = 1.387,
       matching the file's own dictionaries/info.json max_grid exactly)
       before using it. NOT a registered pipeline scenario_param (no
       scenario_param exists for Cascadia).

  LANDSLIDE (co-seismic -- paired with the EQ directly above it)
    e. Newmark PGD (cm) computed fresh for this figure from the New Madrid
       M7.5 scenario (panel c) + the USGS n10 susceptibility layer, via
       resiflow.hazards.landslide_pgd's real HAZUS code (Eq. 4-14/4-15,
       Table 4-16) -- same method/parameters the pipeline uses for Mineral
       (scenario_param=501), just paired with New Madrid instead. NOT a
       registered pipeline scenario_param.
    f. Same method, paired with the Cascadia M9 scenario (panel d) instead.
       Using the SAME national n10 layer (not a PNW-specific product) for
       both e and f is deliberate: n10 already carries real, much higher
       susceptibility across the Cascade/Coast/Olympic ranges than over New
       Madrid's flat Mississippi embayment -- the steep-terrain signal
       comes from evaluating the right region, not a different
       susceptibility dataset. PGD has no native resolution of its own
       (both inputs must share a grid); computed on each EQ's own PGA grid,
       the binding-constraint resolution vs. susceptibility's finer
       ~90-110m.

  WINTER STORM
    g. Winter Storm Jonas -- SNODAS snow depth, 2016-01-23 (~720-930 m,
       NSIDC G02158), cropped to the Mid-Atlantic/Northeast corridor it
       actually hit. Registered pipeline scenario 601 (winter_storm).
    h. Winter Storm Elliott -- SNODAS snow depth, 2022-12-24, full CONUS
       extent (a genuine bomb-cyclone/Arctic outbreak, not a regional
       storm -- confirmed even a >500mm threshold spans coast to coast, so
       no regional crop is applied, unlike Jonas). Registered pipeline
       scenario 603 (winter_storm_elliott). Capped at 2.0m (same cap as
       Jonas) for a known SNODAS model-instability artifact over Mount
       Adams, WA's glaciated summit (true max 31.25m at full resolution --
       see load_elliott_snow()'s docstring) that also survives, undiminished
       enough to matter, in the real pipeline's own 50m-aligned input.
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
    NEW_MADRID_NOTE,
    NEW_MADRID_TITLE,
    SANDY_NOTE,
    SANDY_TITLE,
    SURFACE,
    draw_panel,
    load_cascadia_landslide_pgd_cm,
    load_cascadia_pga,
    load_conus_states,
    load_elliott_snow,
    load_harvey,
    load_new_madrid_landslide_pgd_cm,
    load_new_madrid_pga,
    load_sandy_flood,
    load_snodas_jonas,
)

OUT_DIR = Path(__file__).resolve().parent

ROW_LABEL_KW = dict(fontsize=11.5, color=INK_PRIMARY, fontweight="bold", labelpad=10)


def _missing_panel(ax, letter: str, title: str, message: str) -> None:
    ax.text(
        0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes,
        fontsize=9.5, color=INK_SECONDARY,
    )
    ax.set_title(f"({letter}) {title}", fontsize=12.5, color=INK_PRIMARY, fontweight="bold", loc="left")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def main() -> int:
    states = load_conus_states()
    fig, axes = plt.subplots(
        4, 2, figsize=(11, 18.5), facecolor=SURFACE,
        gridspec_kw=dict(wspace=0.5, hspace=0.4),
    )

    # Row 0: FLOOD
    ax = axes[0, 0]
    try:
        h_arr, h_transform, scale = load_harvey()
        draw_panel(
            ax, letter="a", title="Hurricane Harvey (Houston/Harris County, TX)",
            arr=h_arr, transform=h_transform, native_res_m=3.0, states=states,
            cmap="viridis", unit_label="Depth (m)",
            extra_note=f"display decimated {scale}x for tractability (84 GB source)",
        )
    except FileNotFoundError:
        _missing_panel(
            ax, "a", "Hurricane Harvey (Houston/Harris County, TX)",
            "Harvey panel pending:\ninputs/multihazard_raw/Harvey_Depths_3m_Final.gdb.zip\n"
            "not yet extracted (84 GB uncompressed).",
        )
    axes[0, 0].set_ylabel("FLOOD", **ROW_LABEL_KW)

    s_arr, s_transform, s_res = load_sandy_flood()
    draw_panel(
        axes[0, 1], letter="b", title="Hurricane Sandy (CT/NJ/NY/RI mosaic)",
        arr=s_arr, transform=s_transform, native_res_m=3.0, states=states,
        cmap="viridis", unit_label="Depth (m)",
        extra_note=f"{SANDY_NOTE}\ndisplayed at ~{s_res:.0f}m (source ~3m)",
    )

    # Row 1: EARTHQUAKE
    nm_arr, nm_transform, nm_res = load_new_madrid_pga()
    draw_panel(
        axes[1, 0], letter="c", title=NEW_MADRID_TITLE,
        arr=nm_arr, transform=nm_transform, native_res_m=nm_res, states=states,
        cmap="viridis", unit_label="PGA (g)", extra_note=NEW_MADRID_NOTE,
    )
    axes[1, 0].set_ylabel("EARTHQUAKE", **ROW_LABEL_KW)

    cas_arr, cas_transform, cas_res = load_cascadia_pga()
    draw_panel(
        axes[1, 1], letter="d", title=CASCADIA_TITLE,
        arr=cas_arr, transform=cas_transform, native_res_m=cas_res, states=states,
        cmap="viridis", unit_label="PGA (g)", extra_note=CASCADIA_NOTE,
    )

    # Row 2: LANDSLIDE (co-seismic, paired with the EQ directly above)
    nm_ls_arr, nm_ls_transform, nm_ls_res = load_new_madrid_landslide_pgd_cm()
    draw_panel(
        axes[2, 0], letter="e", title="Newmark PGD -- Missouri 1811-12* EQ",
        arr=nm_ls_arr, transform=nm_ls_transform, native_res_m=nm_ls_res, states=states,
        cmap="viridis", unit_label="Newmark PGD (cm)",
        extra_note="Computed fresh (not a registered pipeline scenario); on PGA's\n"
                    "own native grid, the binding constraint vs. susceptibility's ~90-110m",
    )
    axes[2, 0].set_ylabel("LANDSLIDE\n(co-seismic)", **ROW_LABEL_KW)

    cas_ls_arr, cas_ls_transform, cas_ls_res = load_cascadia_landslide_pgd_cm()
    draw_panel(
        axes[2, 1], letter="f", title="Newmark PGD -- Cascadia M9 EQ",
        arr=cas_ls_arr, transform=cas_ls_transform, native_res_m=cas_ls_res, states=states,
        cmap="viridis", unit_label="Newmark PGD (cm)",
        extra_note="Computed fresh (not a registered pipeline scenario); on PGA's\n"
                    "own native grid, the binding constraint vs. susceptibility's ~90-110m",
    )

    # Row 3: WINTER STORM
    ws_arr, ws_transform, ws_res = load_snodas_jonas()
    draw_panel(
        axes[3, 0], letter="g", title="Winter Storm Jonas (2016-01-23)",
        arr=ws_arr, transform=ws_transform, native_res_m=ws_res, states=states,
        cmap="viridis", unit_label="Snow depth (m)", vmax=1.2,
    )
    axes[3, 0].set_ylabel("WINTER STORM", **ROW_LABEL_KW)

    el_arr, el_transform, el_res = load_elliott_snow()
    draw_panel(
        axes[3, 1], letter="h", title="Winter Storm Elliott (2022-12-24)",
        arr=el_arr, transform=el_transform, native_res_m=el_res, states=states,
        cmap="viridis", unit_label="Snow depth (m)",
        extra_note="Capped at 2.0m (matches Jonas): known SNODAS artifact\n"
                    "over Mt. Adams, WA glaciated terrain, true max 31.25m",
    )

    fig.suptitle(
        "CONUS hazard footprints at native (pre-resampling) resolution",
        fontsize=16, color=INK_PRIMARY, x=0.02, ha="left", y=0.995, fontweight="bold",
    )
    fig.text(
        0.02, 0.975,
        "Each panel reprojected to a shared display CRS (EPSG:9311) preserving native pixel size -- "
        "not resampled to the model's common 50 m grid. Each row is one hazard type; the two "
        "columns are two contrasting real events for that type.",
        fontsize=10, color=INK_SECONDARY, ha="left", va="top",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.965))

    fig.savefig(OUT_DIR / "hazard_footprints_native_res.pdf", bbox_inches="tight")
    fig.savefig(OUT_DIR / "hazard_footprints_native_res.png", dpi=200, bbox_inches="tight")
    print("Wrote", OUT_DIR / "hazard_footprints_native_res.pdf")
    print("Wrote", OUT_DIR / "hazard_footprints_native_res.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
