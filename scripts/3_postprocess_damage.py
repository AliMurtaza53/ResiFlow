# %%
from pathlib import Path
import os
import sys

import pandas as pd
import warnings
import logging

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from resiflow.damage_aggregation import add_consolidated_damage_columns
from resiflow.utils import get_results_variant, load_config

warnings.simplefilter("ignore")
base_path = Path(load_config()["paths"]["soge_clusters"])
results_root = base_path.parent / "results" / "damage_analysis" / get_results_variant()


# %%
def compute_edge_damage(intersections):
    intersections = add_consolidated_damage_columns(intersections)
    edges_with_damage = (
        intersections.groupby("e_id", as_index=False)["direct_damage_mean_musd"]
        .sum()
        .rename(columns={"direct_damage_mean_musd": "edge_direct_damage_mean_musd"})
    )
    return edges_with_damage


def main() -> None:
    intersections_list = []
    for root, _, files in os.walk(results_root):
        for file in files:
            intersection_path = Path(root) / file
            if (
                intersection_path.suffix.lower() == ".csv"
                and "with_damage_values" in intersection_path.name
            ):
                intersections_list.append(intersection_path)

    if not intersections_list:
        logging.warning("No damage CSVs found under %s", results_root)
        return

    event_list = []
    min_cost_list = []
    max_cost_list = []
    for event_path in intersections_list:
        intersections = pd.read_csv(event_path)
        edges_with_damage = compute_edge_damage(intersections)
        flood_key = event_path.stem.split("_")[1]
        min_cost = float(edges_with_damage["edge_direct_damage_mean_musd"].sum())
        event_list.append(flood_key)
        min_cost_list.append(min_cost)
        max_cost_list.append(min_cost)

    temp = pd.DataFrame(
        {
            "event_id": event_list,
            "damage_cost_min_musd": min_cost_list,
            "damage_cost_max_musd": max_cost_list,
        }
    )
    temp["damage_cost_mean_musd"] = temp[
        ["damage_cost_min_musd", "damage_cost_max_musd"]
    ].mean(axis=1)
    temp["damage_cost_mean_usd"] = temp["damage_cost_mean_musd"] * 1_000_000.0

    summary_path = results_root / "damage_summary.csv"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write (tmp file + os.replace): every hazard job runs this script
    # and rewrites this SAME shared aggregate path each time, walking every
    # scenario's damage CSV it finds on disk -- concurrent jobs' writes can
    # otherwise interleave/truncate each other. This is the second instance
    # of the same race-condition class fixed in 3_damage_analysis.py's
    # per-scenario CSV write (2026-08-26): confirmed here too by a real
    # mismatch (2026-08-27) between this file's value for scenario 403
    # ($198.5B) and 403's own, trustworthy cost_matrix_by_scenario.csv
    # ($1.94B, computed via the already-atomic per-scenario CSV).
    tmp_path = summary_path.parent / f".damage_summary.csv.tmp{os.getpid()}"
    temp.to_csv(tmp_path, index=False)
    os.replace(tmp_path, summary_path)
    print(f"Saved damage summary to {summary_path}")
    print(temp.to_string(index=False))


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s %(process)d %(filename)s %(message)s",
        level=logging.INFO,
    )
    main()
