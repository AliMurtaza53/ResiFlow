"""Build the 4th finale figure: small-multiple CONUS damage-extent maps, one
panel per hazard, following Bor et al. 2026 (arXiv:2605.23053,
github.com/denniesbor/mhtran)'s Fig. 3/6 pattern -- see
plot_multihazard_damage_maps()'s own docstring in viz_data_loaders.py for why
that pattern (shared color scale, damage_level_max ordinal) was chosen.

Companion to build_finale_figures.py: same hazard selection, from the shared
finale_hazards.py (previously each script hand-typed its own copy of the
label/hazard_type/hazard_subtype mapping -- confirmed those two copies had
already drifted apart, e.g. hazard_subtype hand-typed here for depth_keys
401/501/601 didn't match what's actually in the registry). This one loads
each hazard's post-Script-2 road_links_{event_key}.gpq (link geometry +
damage_level_max) instead of the dollar-cost tables, so it needs real network
access -- run this on Hopper (or wherever conus_nandu_v1's
results/disruption_analysis tree is reachable), not on a machine that only
has the small dollar-summary CSVs.

Each file is CONUS-scale (~484k links, ~350MB) -- subset_links_for_map()
caps what actually gets drawn per panel (default DEFAULT_MAX_MAP_EDGES from
viz_data_loaders.py) while always keeping every damaged link, so the map
never silently drops real damage to fit the edge budget.

Bug fixed 2026-09-04: road_links_{event_key}.gpq's own damage_level_max
column (under disruption_analysis/) is only Script 2's preliminary flag, NOT
the real per-link damage -- confirmed against a real run where 5 of 6 hazards
reported n=0 damaged despite known nonzero direct-damage dollars in
build_finale_figures.py's own hand-entered HAZARDS table. Script 4 itself
never trusts that column directly either: it separately loads Script 3's
damage CSV (damage_analysis/<variant>/<depth>/intersections_<event>_with_
damage_values.csv) via load_event_damage_from_script3() and merges the real
damage_level_max in at runtime. This now imports and reuses that exact
function (via importlib, since the script's filename starts with a digit and
isn't a valid module name) rather than re-deriving the same logic separately
and risking it drifting out of sync with Script 4's own behavior.
"""

import importlib.util
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "visualizations"))

import geopandas as gpd

from viz_data_loaders import plot_multihazard_damage_maps, subset_links_for_map

from finale_hazards import VARIANT, finale_hazards


def _load_script4_module():
    script4_path = Path(__file__).resolve().parents[2] / "scripts" / "4_rerouting_and_recovery_scenario_loop.py"
    spec = importlib.util.spec_from_file_location("_script4_for_damage_maps", script4_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

OUT_DIR = Path(__file__).resolve().parent


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
    script4 = _load_script4_module()
    hazards = finale_hazards()

    links_by_hazard: dict[str, gpd.GeoDataFrame] = {}
    hazard_meta: dict[str, dict[str, str]] = {}
    missing: list[str] = []

    # load_event_damage_from_script3() resolves its own damage-CSV path via
    # get_results_variant(), which reads RESIFLOW_RESULTS_VARIANT/
    # NIRD_RESULTS_VARIANT from the environment (default "revision") -- NOT a
    # parameter it takes. Set it once here rather than relying on ambient
    # shell state: confirmed this was the second half of a real n=0-damaged
    # bug (the first half was road_links_path()'s own stale damage_level_max
    # column) -- without RESIFLOW_RESULTS_VARIANT exported, this looked in
    # results/damage_analysis/revision/... instead of .../conus_nandu_v1/...,
    # found nothing, and silently returned 0.
    os.environ["RESIFLOW_RESULTS_VARIANT"] = VARIANT
    os.environ["NIRD_RESULTS_VARIANT"] = VARIANT

    for hz in hazards:
        path = road_links_path(base_path, VARIANT, hz.scenario_param, hz.event_key)
        if not path.exists():
            missing.append(f"{hz.hazard_label}: {path}")
            continue
        gdf = gpd.read_parquet(path, columns=["e_id", "geometry"])
        gdf["e_id"] = gdf["e_id"].astype(str)

        damage_by_edge, _direct_damage_total = script4.load_event_damage_from_script3(
            base_path, hz.scenario_param, hz.event_key
        )
        if not damage_by_edge.empty:
            damage_by_edge = damage_by_edge[["e_id", "damage_level_max"]].copy()
            damage_by_edge["e_id"] = damage_by_edge["e_id"].astype(str)
            gdf = gdf.merge(damage_by_edge, on="e_id", how="left")
        else:
            gdf["damage_level_max"] = "no"
        gdf["damage_level_max"] = gdf["damage_level_max"].fillna("no")

        links_by_hazard[hz.hazard_label] = subset_links_for_map(
            gdf, flow_col="__none__", max_edges=max_edges, min_flow=-1.0
        )
        hazard_meta[hz.hazard_label] = {
            "hazard_type": hz.hazard_type,
            "hazard_subtype": hz.hazard_subtype,
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
    print(f"Wrote {out_file} ({len(links_by_hazard)} of {len(hazards)} hazards)")
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
