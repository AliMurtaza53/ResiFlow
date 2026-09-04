"""Build the 4th finale figure: small-multiple CONUS damage-extent maps, one
panel per hazard, following Bor et al. 2026 (arXiv:2605.23053,
github.com/denniesbor/mhtran)'s Fig. 3/6 pattern -- see
plot_multihazard_damage_maps()'s own docstring in viz_data_loaders.py for why
that pattern (shared color scale, damage_level_max ordinal) was chosen.

Companion to build_finale_figures.py: same HAZARDS registry (label,
hazard_type, hazard_subtype, variant, depth_key/event_key), but this one
loads each hazard's post-Script-2 road_links_{event_key}.gpq (link geometry +
damage_level_max) instead of the dollar-cost tables, so it needs real network
access -- run this on Hopper (or wherever conus_nandu_v1's
results/disruption_analysis tree is reachable), not on a machine that only
has the small dollar-summary CSVs.

Each file is CONUS-scale (~484k links, ~350MB) -- subset_links_for_map()
caps what actually gets drawn per panel (default DEFAULT_MAX_MAP_EDGES from
viz_data_loaders.py) while always keeping every damaged link, so the map
never silently drops real damage to fit the edge budget.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "visualizations"))

import geopandas as gpd

from viz_data_loaders import plot_multihazard_damage_maps, subset_links_for_map

OUT_DIR = Path(__file__).resolve().parent

# Same 6 hazards as build_finale_figures.py (see that file's module docstring
# for why 602/603/604 are excluded as of this batch -- still in flight / just
# killed on Hopper, not yet a completed scenario).
HAZARDS = [
    {"hazard_label": "Flood", "hazard_type": "flood", "hazard_subtype": "flood_surface",
     "variant": "conus_nandu_v1", "depth_key": 301, "event_key": 1},
    {"hazard_label": "Harvey", "hazard_type": "flood", "hazard_subtype": "flood_harvey_houston",
     "variant": "conus_nandu_v1", "depth_key": 304, "event_key": 1},
    {"hazard_label": "Earthquake (Mineral)", "hazard_type": "earthquake",
     "hazard_subtype": "earthquake_shakemap_mineral", "variant": "conus_nandu_v1",
     "depth_key": 401, "event_key": 1},
    {"hazard_label": "Earthquake (New Madrid)", "hazard_type": "earthquake",
     "hazard_subtype": "earthquake_new_madrid_m75_scenario", "variant": "conus_nandu_v1",
     "depth_key": 403, "event_key": 1},
    {"hazard_label": "Landslide", "hazard_type": "landslide", "hazard_subtype": "landslide",
     "variant": "conus_nandu_v1", "depth_key": 501, "event_key": 1},
    {"hazard_label": "Winter storm (Jonas)", "hazard_type": "winter_storm",
     "hazard_subtype": "winter_storm", "variant": "conus_nandu_v1",
     "depth_key": 601, "event_key": 1},
]


def road_links_path(base_path: Path, variant: str, depth_key: int, event_key: int) -> Path:
    return (
        base_path.parent
        / "results"
        / "disruption_analysis"
        / variant
        / str(depth_key)
        / "links"
        / f"road_links_{event_key}.gpq"
    )


def main(base_path: Path, max_edges: int | None = 60_000) -> int:
    links_by_hazard: dict[str, gpd.GeoDataFrame] = {}
    hazard_meta: dict[str, dict[str, str]] = {}
    missing: list[str] = []

    for hz in HAZARDS:
        path = road_links_path(base_path, hz["variant"], hz["depth_key"], hz["event_key"])
        if not path.exists():
            missing.append(f"{hz['hazard_label']}: {path}")
            continue
        gdf = gpd.read_parquet(
            path,
            columns=["e_id", "geometry", "damage_level_max"],
        )
        links_by_hazard[hz["hazard_label"]] = subset_links_for_map(
            gdf, flow_col="__none__", max_edges=max_edges, min_flow=-1.0
        )
        hazard_meta[hz["hazard_label"]] = {
            "hazard_type": hz["hazard_type"],
            "hazard_subtype": hz["hazard_subtype"],
        }

    if missing:
        print("Missing road_links for:")
        for m in missing:
            print(" -", m)

    if not links_by_hazard:
        print("No hazard link files found -- nothing to plot.")
        return 1

    fig, _ = plot_multihazard_damage_maps(links_by_hazard, hazard_meta=hazard_meta)
    out_file = OUT_DIR / "04_multihazard_damage_maps.png"
    fig.savefig(out_file, dpi=150, bbox_inches="tight")
    print(f"Wrote {out_file} ({len(links_by_hazard)} of {len(HAZARDS)} hazards)")
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-path",
        default=None,
        help="soge_clusters base path (default: resiflow config's paths.soge_clusters)",
    )
    parser.add_argument("--max-edges", type=int, default=60_000)
    args = parser.parse_args()

    if args.base_path:
        base = Path(args.base_path)
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
        from resiflow.utils import load_config

        base = Path(load_config()["paths"]["soge_clusters"])

    sys.exit(main(base, max_edges=args.max_edges))
