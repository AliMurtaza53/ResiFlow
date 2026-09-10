"""2x2 CONUS panel of hazard footprints, all at ONE shared US-scale extent.

Companion to plot_hazard_footprints_native_res.py, which zooms each panel to
its own footprint to show native PIXEL SIZE heterogeneity. This figure holds
every panel to the SAME CONUS-wide map extent instead, so relative FOOTPRINT
SIZE is directly comparable -- Harvey's Houston-area extent next to
Cascadia's Pacific-Northwest-spanning M9 shaking footprint next to Jonas's
Mid-Atlantic corridor, all on one consistent basemap/scale.

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
    # One shared CONUS extent for every panel, with a little padding --
    # states.total_bounds is (minx, miny, maxx, maxy) in EPSG:9311 meters.
    minx, miny, maxx, maxy = states.total_bounds
    pad_x, pad_y = (maxx - minx) * 0.03, (maxy - miny) * 0.03
    conus_extent = (minx - pad_x, maxx + pad_x, miny - pad_y, maxy + pad_y)

    fig, axes = plt.subplots(2, 2, figsize=(11, 8), facecolor=SURFACE)

    cas_arr, cas_transform, _ = load_cascadia_pga()
    draw_panel(
        axes[0, 1], letter="b", title=f"Earthquake -- {CASCADIA_TITLE}",
        arr=cas_arr, transform=cas_transform, native_res_m=None, states=states,
        cmap="viridis", unit_label="PGA (g)", fixed_extent=conus_extent,
        res_note_override="",
    )

    ls_arr, ls_transform, _ = load_cascadia_landslide_pgd_cm()
    draw_panel(
        axes[1, 0], letter="c", title="Co-seismic landslide -- Newmark PGD (same EQ)",
        arr=ls_arr, transform=ls_transform, native_res_m=None, states=states,
        cmap="viridis", unit_label="Newmark PGD (cm)", fixed_extent=conus_extent,
        res_note_override="",
    )

    ws_arr, ws_transform, _ = load_snodas_jonas()
    draw_panel(
        axes[1, 1], letter="d", title="Winter Storm Jonas -- SNODAS snow depth",
        arr=ws_arr, transform=ws_transform, native_res_m=None, states=states,
        cmap="viridis", unit_label="Snow depth (m)", vmax=1.2, fixed_extent=conus_extent,
        res_note_override="",
    )

    ax = axes[0, 0]
    try:
        h_arr, h_transform, _ = load_harvey()
        draw_panel(
            ax, letter="a", title="Hurricane Harvey -- flood depth",
            arr=h_arr, transform=h_transform, native_res_m=None, states=states,
            cmap="viridis", unit_label="Depth (m)", fixed_extent=conus_extent,
            res_note_override="",
        )
    except FileNotFoundError:
        ax.text(
            0.5, 0.5,
            "Harvey panel pending:\ninputs/multihazard_raw/Harvey_Depths_3m_Final.gdb.zip\n"
            "not yet extracted (84 GB uncompressed).",
            ha="center", va="center", transform=ax.transAxes, fontsize=9.5, color=INK_SECONDARY,
        )
        ax.set_title("(a) Hurricane Harvey -- flood depth", fontsize=12.5,
                     color=INK_PRIMARY, fontweight="bold", loc="left")
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

    fig.suptitle(
        "CONUS hazard footprints at a shared US-scale extent",
        fontsize=15.5, color=INK_PRIMARY, x=0.02, ha="left", y=0.99, fontweight="bold",
    )
    fig.text(
        0.02, 0.955,
        "Every panel shares one CONUS-wide map extent and display CRS (EPSG:9311) -- "
        "compare relative FOOTPRINT SIZE here; see the companion native-resolution "
        "figure for pixel-size heterogeneity.",
        fontsize=10, color=INK_SECONDARY, ha="left", va="top",
    )
    # (b)'s magnitude caveat as a figure-level footnote, not embedded in the
    # panel itself: the zoomed-out panel is too narrow for that full string
    # without it visually spilling into the colorbar (matplotlib doesn't
    # clip axes text by default) -- confirmed this exact overlap and fixed
    # it here rather than truncating the caveat or shrinking its font.
    fig.text(
        0.02, 0.01, CASCADIA_NOTE, fontsize=9, color=INK_SECONDARY, ha="left", va="bottom",
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.93))

    fig.savefig(OUT_DIR / "hazard_footprints_us_scale.pdf", bbox_inches="tight")
    fig.savefig(OUT_DIR / "hazard_footprints_us_scale.png", dpi=200, bbox_inches="tight")
    print("Wrote", OUT_DIR / "hazard_footprints_us_scale.pdf")
    print("Wrote", OUT_DIR / "hazard_footprints_us_scale.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
