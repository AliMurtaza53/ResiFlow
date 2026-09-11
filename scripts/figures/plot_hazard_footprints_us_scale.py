"""4x2 CONUS panel of hazard footprints, all at ONE shared US-scale extent.

Companion to plot_hazard_footprints_native_res.py, which zooms each panel to
its own footprint to show native PIXEL SIZE heterogeneity. This figure holds
every panel to the SAME CONUS-wide map extent instead, so relative FOOTPRINT
SIZE is directly comparable -- Harvey's Houston-area extent next to Sandy's
CT/NJ/NY/RI coastal extent, New Madrid's 8-state Central US footprint next to
Cascadia's Pacific-Northwest-spanning M9 shaking footprint, Jonas's
Mid-Atlantic corridor next to Elliott's near-continental reach, all on one
consistent basemap/scale. Same 4-row (hazard type) x 2-column (two
contrasting real events) layout as the native-resolution figure -- see that
script's module docstring for what each panel actually is.

Uses the same source loaders as the native-resolution figure
(_hazard_footprints_common.py) -- same data, same reprojection (still
preserving each raster's own native pixel size within its footprint; only the
AXIS EXTENT changes here, not the underlying pixel data).
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
    # One shared CONUS extent for every panel, with a little padding --
    # states.total_bounds is (minx, miny, maxx, maxy) in EPSG:9311 meters.
    minx, miny, maxx, maxy = states.total_bounds
    pad_x, pad_y = (maxx - minx) * 0.03, (maxy - miny) * 0.03
    conus_extent = (minx - pad_x, maxx + pad_x, miny - pad_y, maxy + pad_y)

    fig, axes = plt.subplots(
        4, 2, figsize=(11, 15.5), facecolor=SURFACE,
        gridspec_kw=dict(wspace=0.5, hspace=0.35),
    )

    # Row 0: FLOOD
    ax = axes[0, 0]
    try:
        h_arr, h_transform, _ = load_harvey()
        draw_panel(
            ax, letter="a", title="Hurricane Harvey (Houston/Harris County, TX)",
            arr=h_arr, transform=h_transform, native_res_m=None, states=states,
            cmap="viridis", unit_label="Depth (m)", fixed_extent=conus_extent,
            res_note_override="",
        )
    except FileNotFoundError:
        _missing_panel(
            ax, "a", "Hurricane Harvey (Houston/Harris County, TX)",
            "Harvey panel pending:\ninputs/multihazard_raw/Harvey_Depths_3m_Final.gdb.zip\n"
            "not yet extracted (84 GB uncompressed).",
        )
    axes[0, 0].set_ylabel("FLOOD", **ROW_LABEL_KW)

    s_arr, s_transform, _ = load_sandy_flood()
    draw_panel(
        axes[0, 1], letter="b", title="Hurricane Sandy (CT/NJ/NY/RI mosaic)",
        arr=s_arr, transform=s_transform, native_res_m=None, states=states,
        cmap="viridis", unit_label="Depth (m)", fixed_extent=conus_extent,
        res_note_override="",
    )

    # Row 1: EARTHQUAKE
    nm_arr, nm_transform, _ = load_new_madrid_pga()
    draw_panel(
        axes[1, 0], letter="c", title=NEW_MADRID_TITLE,
        arr=nm_arr, transform=nm_transform, native_res_m=None, states=states,
        cmap="viridis", unit_label="PGA (g)", fixed_extent=conus_extent,
        res_note_override="",
    )
    axes[1, 0].set_ylabel("EARTHQUAKE", **ROW_LABEL_KW)

    cas_arr, cas_transform, _ = load_cascadia_pga()
    draw_panel(
        axes[1, 1], letter="d", title=CASCADIA_TITLE,
        arr=cas_arr, transform=cas_transform, native_res_m=None, states=states,
        cmap="viridis", unit_label="PGA (g)", fixed_extent=conus_extent,
        res_note_override="",
    )

    # Row 2: LANDSLIDE (co-seismic, paired with the EQ directly above)
    nm_ls_arr, nm_ls_transform, _ = load_new_madrid_landslide_pgd_cm()
    draw_panel(
        axes[2, 0], letter="e", title="Newmark PGD -- Missouri 1811-12* EQ",
        arr=nm_ls_arr, transform=nm_ls_transform, native_res_m=None, states=states,
        cmap="viridis", unit_label="Newmark PGD (cm)", fixed_extent=conus_extent,
        res_note_override="",
    )
    axes[2, 0].set_ylabel("LANDSLIDE\n(co-seismic)", **ROW_LABEL_KW)

    cas_ls_arr, cas_ls_transform, _ = load_cascadia_landslide_pgd_cm()
    draw_panel(
        axes[2, 1], letter="f", title="Newmark PGD -- Cascadia M9 EQ",
        arr=cas_ls_arr, transform=cas_ls_transform, native_res_m=None, states=states,
        cmap="viridis", unit_label="Newmark PGD (cm)", fixed_extent=conus_extent,
        res_note_override="",
    )

    # Row 3: WINTER STORM
    ws_arr, ws_transform, _ = load_snodas_jonas()
    draw_panel(
        axes[3, 0], letter="g", title="Winter Storm Jonas (2016-01-23)",
        arr=ws_arr, transform=ws_transform, native_res_m=None, states=states,
        cmap="viridis", unit_label="Snow depth (m)", vmax=1.2, fixed_extent=conus_extent,
        res_note_override="",
    )
    axes[3, 0].set_ylabel("WINTER STORM", **ROW_LABEL_KW)

    el_arr, el_transform, _ = load_elliott_snow()
    draw_panel(
        axes[3, 1], letter="h", title="Winter Storm Elliott (2022-12-24)",
        arr=el_arr, transform=el_transform, native_res_m=None, states=states,
        cmap="viridis", unit_label="Snow depth (m)", fixed_extent=conus_extent,
        res_note_override="",
    )

    fig.suptitle(
        "CONUS hazard footprints at a shared US-scale extent",
        fontsize=16, color=INK_PRIMARY, x=0.02, ha="left", y=0.995, fontweight="bold",
    )
    fig.text(
        0.02, 0.975,
        "Every panel shares one CONUS-wide map extent and display CRS (EPSG:9311) -- compare "
        "relative FOOTPRINT SIZE here; see the companion native-resolution figure for pixel-size "
        "heterogeneity. Each row is one hazard type; the two columns are two contrasting real "
        "events for that type.",
        fontsize=10, color=INK_SECONDARY, ha="left", va="top",
    )
    # (c)/(d)'s magnitude/scenario caveats as figure-level footnotes, not
    # embedded in the panels themselves: the zoomed-out panels are too narrow
    # for the full strings without spilling into the colorbar (matplotlib
    # doesn't clip axes text by default) -- confirmed this exact overlap and
    # fixed it here rather than truncating either caveat or shrinking font.
    fig.text(
        0.02, 0.012, f"(c) {NEW_MADRID_NOTE}\n(d) {CASCADIA_NOTE}",
        fontsize=9, color=INK_SECONDARY, ha="left", va="bottom",
    )
    fig.tight_layout(rect=(0, 0.035, 1, 0.965))

    fig.savefig(OUT_DIR / "hazard_footprints_us_scale.pdf", bbox_inches="tight")
    fig.savefig(OUT_DIR / "hazard_footprints_us_scale.png", dpi=200, bbox_inches="tight")
    print("Wrote", OUT_DIR / "hazard_footprints_us_scale.pdf")
    print("Wrote", OUT_DIR / "hazard_footprints_us_scale.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
