#!/usr/bin/env python3
"""Compute one hazard event's REAL freight commodity mix.

Replaces the flat national SCTG-share proxy `plot_freight_industry_breakdown()`
(scripts/visualizations/viz_data_loaders.py) previously used for every hazard --
which made that panel a scalar rescale of the direct-vs-indirect panel and
carried no information beyond it (flagged 2026-08-03).

Method: join Script 4's own disrupted freight OD pairs (same candidates that
produce this event's rerouting_cost_freight_usd) against
faf5_od_matrix_by_sctg.pq on (origin_node, destination_node), and sum that
matrix's Car21 by sctgG5 over just those disrupted pairs. This is a real
per-hazard commodity mix, not a proxy: locally verified (2026-08-03) that
summing faf5_od_matrix_by_sctg.pq's Car21 across its 5 sctgG5 groups for a
given OD pair reproduces the base faf5_od_matrix.pq's Car21 for that pair
EXACTLY (zero difference across all ~9.77M pairs) -- it's a true partition of
the same flow variable the assignment already uses, not an independent
estimate, so weighting by disrupted-pair Car21 correctly attributes commodity
shares of the flow that is actually being rerouted.

Deliberately reuses scripts/4_rerouting_and_recovery_scenario_loop.py's own
candidate-loading functions (load_odpfc_source, load_path_index_disrupted_
candidates, overlay_assignment_flows, and the odpfc/path-index fallback-path
resolution in main()) via importlib rather than duplicating them, so the OD
pairs joined here are IDENTICAL to what Script 4 used for the cost this panel
is meant to decompose -- not an independently-derived set that could quietly
diverge. Loaded by path (not `import`) because that script's filename starts
with a digit. Does not call Script 4's main() and does not touch its file, so
it's safe to run alongside an in-progress Script 4 SLURM job.

Usage::

    python scripts/compute_freight_industry_mix.py 301 1 \
        --sctg-matrix /path/to/faf5_od_matrix_by_sctg.pq \
        --hazard-label flood \
        --output industry_mix_301_1.json

Run once per hazard event (same scenario_param/event_id args already used for
Script 4), after that event's Script 4 run has completed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import duckdb  # noqa: E402
import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402

from resiflow.config import get_env  # noqa: E402
from resiflow.demand import demand_spec_from_env, load_assignment_demand  # noqa: E402
from resiflow.demand.load import first_existing  # noqa: E402
from resiflow.utils import get_results_variant  # noqa: E402

SCTG_LABELS = {
    "sctg0109": "Agriculture, fishing, forestry",
    "sctg1014": "Mining",
    "sctg1519": "Petroleum & coal products",
    "sctg2033": "Manufactured goods",
    "sctg3499": "Mixed freight & other",
}


def resolve_sctg_matrix_path(base_path: Path) -> Path:
    """Same resolution pattern as resiflow.demand.load.resolve_freight_od_path."""
    env_path = get_env("RESIFLOW_FAF5_SCTG_MATRIX_PATH", "NIRD_FAF5_SCTG_MATRIX_PATH")
    if env_path:
        path = Path(env_path)
        if path.exists():
            return path
    found = first_existing(
        [
            base_path / "census_datasets" / "faf5_od_matrix_by_sctg.pq",
            base_path / "inputs" / "census_datasets" / "faf5_od_matrix_by_sctg.pq",
        ]
    )
    if found is None:
        raise FileNotFoundError(
            "Could not find faf5_od_matrix_by_sctg.pq in standard input paths; "
            "pass --sctg-matrix explicitly or set RESIFLOW_FAF5_SCTG_MATRIX_PATH."
        )
    return found


def _load_script4_module():
    script_path = REPO_ROOT / "scripts" / "4_rerouting_and_recovery_scenario_loop.py"
    spec = importlib.util.spec_from_file_location("resiflow_script4", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_disrupted_freight_candidates(
    script4, base_path: Path, scenario_param: int, event_id: str
) -> pd.DataFrame:
    """Reproduce Script 4's own freight disrupted-candidate set for one event.

    Mirrors main()'s candidate-source resolution (lines ~577-652) and initial
    damaged_edges derivation (~653-692) exactly, EXCEPT the "event_candidates"
    (Pass B) branch -- the current orchestrator no longer produces those
    artifacts (Pass B was eliminated, docs/CONUS_MULTIHAZARD_METHODOLOGY.md), so
    that branch is intentionally omitted rather than dead code copied for its
    own sake. If a legacy event_disrupted_candidates directory is ever found
    again this will fall through to the odpfc/path_index branches below it,
    same as it would if that directory were simply absent.
    """
    results_variant = get_results_variant()

    road_links = gpd.read_parquet(
        base_path.parent
        / "results"
        / "disruption_analysis"
        / results_variant
        / str(scenario_param)
        / "links"
        / f"road_links_{event_id}.gpq"
    )
    road_links["e_id"] = road_links["e_id"].astype(str)
    damaged_edges = set(
        road_links.loc[road_links["damage_level_max"] != "no", "e_id"].astype(str)
    )
    logging.info(
        "Event scenario_param=%s event_id=%s: %s damaged edges",
        scenario_param,
        event_id,
        len(damaged_edges),
    )

    odpfc_path = (
        base_path.parent
        / "results"
        / "disruption_analysis"
        / results_variant
        / "od"
        / f"odpfc_{scenario_param}_{event_id}.pq"
    )
    odpfc_parts_path = odpfc_path.parent / "odpfc_parts"
    candidate_source_mode = "legacy_odpfc"
    candidate_source_path = odpfc_path
    if not odpfc_path.exists() and script4.odpfc_source_exists(odpfc_parts_path):
        candidate_source_path = odpfc_parts_path
    if not script4.odpfc_source_exists(candidate_source_path):
        base_odpfc_path = (
            base_path.parent / "results" / "base_scenario" / results_variant / "odpfc.pq"
        )
        base_odpfc_parts = (
            base_path.parent / "results" / "base_scenario" / results_variant / "odpfc_parts"
        )
        base_path_index_dir = base_path.parent / "results" / "base_scenario" / results_variant
        if script4.odpfc_source_exists(base_odpfc_path):
            candidate_source_mode = "legacy_odpfc"
            candidate_source_path = base_odpfc_path
        elif script4.odpfc_source_exists(base_odpfc_parts):
            candidate_source_mode = "legacy_odpfc"
            candidate_source_path = base_odpfc_parts
        elif (
            (base_path_index_dir / "baseline_od_meta.pq").exists()
            and (base_path_index_dir / "baseline_path_index_parts").exists()
            and (base_path_index_dir / "edge_lookup.pq").exists()
        ):
            candidate_source_mode = "path_index"
            candidate_source_path = base_path_index_dir
        else:
            raise FileNotFoundError(
                f"No odpfc/path_index candidate source found for "
                f"scenario_param={scenario_param} event_id={event_id} under "
                f"results_variant={results_variant}. Checked {base_odpfc_path}, "
                f"{base_odpfc_parts}, and {base_path_index_dir}."
            )
    logging.info(
        "Candidate source mode=%s path=%s", candidate_source_mode, candidate_source_path
    )

    if candidate_source_mode == "path_index":
        disrupted_candidates = script4.load_path_index_disrupted_candidates(
            Path(candidate_source_path), damaged_edges
        )
    else:
        disrupted_candidates = script4.load_odpfc_source(
            Path(candidate_source_path), damaged_edges
        )

    if disrupted_candidates.empty:
        logging.info("No disrupted candidates for this event; commodity mix is empty.")
        return disrupted_candidates

    demand_result = load_assignment_demand(base_path, demand_spec_from_env(base_path))
    freight_od_df = demand_result.freight_od
    if freight_od_df is None:
        freight_od_df = demand_result.assignment_od
    if freight_od_df is None:
        raise RuntimeError(
            "No freight/assignment OD demand found -- cannot restrict candidates to freight."
        )

    freight_candidates = script4.overlay_assignment_flows(disrupted_candidates, freight_od_df)
    logging.info(
        "Restricted to %s disrupted freight OD pairs (of %s total disrupted candidates).",
        len(freight_candidates),
        len(disrupted_candidates),
    )
    return freight_candidates


def compute_commodity_mix(freight_candidates: pd.DataFrame, sctg_matrix_path: Path) -> dict:
    """Sum faf5_od_matrix_by_sctg.pq's Car21 by sctgG5 over the disrupted OD pairs."""
    if freight_candidates.empty:
        return {
            "shares": {},
            "n_disrupted_pairs": 0,
            "n_matched_pairs": 0,
            "matched_car21_total": 0.0,
        }

    pairs = freight_candidates[["origin_node", "destination_node"]].drop_duplicates().copy()
    pairs["origin_node"] = pairs["origin_node"].astype(str)
    pairs["destination_node"] = pairs["destination_node"].astype(str)

    con = duckdb.connect()
    con.register("disrupted_pairs", pairs)
    sctg_sql = str(sctg_matrix_path).replace("'", "''")
    by_commodity = con.execute(
        f"""
        SELECT s.sctgG5 AS sctg_code, SUM(s.Car21) AS car21_total
        FROM read_parquet('{sctg_sql}') s
        JOIN disrupted_pairs p
          ON p.origin_node = s.origin_node AND p.destination_node = s.destination_node
        GROUP BY s.sctgG5
        """
    ).fetchdf()
    n_matched_pairs = con.execute(
        f"""
        SELECT COUNT(*) FROM (
            SELECT DISTINCT s.origin_node, s.destination_node
            FROM read_parquet('{sctg_sql}') s
            JOIN disrupted_pairs p
              ON p.origin_node = s.origin_node AND p.destination_node = s.destination_node
        )
        """
    ).fetchone()[0]
    con.close()

    total = float(by_commodity["car21_total"].sum())
    shares = (
        {
            str(row.sctg_code): float(row.car21_total) / total
            for row in by_commodity.itertuples(index=False)
        }
        if total > 0
        else {}
    )
    return {
        "shares": shares,
        "n_disrupted_pairs": int(len(pairs)),
        "n_matched_pairs": int(n_matched_pairs),
        "matched_car21_total": total,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("scenario_param", type=int)
    parser.add_argument("event_id")
    parser.add_argument("--results-variant", default=None)
    parser.add_argument(
        "--sctg-matrix",
        type=Path,
        default=None,
        help="Defaults to <soge_clusters>/census_datasets/faf5_od_matrix_by_sctg.pq "
        "(or RESIFLOW_FAF5_SCTG_MATRIX_PATH/NIRD_FAF5_SCTG_MATRIX_PATH).",
    )
    parser.add_argument(
        "--hazard-label",
        default=None,
        help="Key to store this event's shares under in the output JSON "
        "(e.g. 'flood', 'earthquake'). Defaults to scenario_param.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    logging.basicConfig(
        format="%(asctime)s %(process)d %(filename)s %(message)s", level=logging.INFO
    )

    if args.results_variant:
        os.environ["RESIFLOW_RESULTS_VARIANT"] = args.results_variant
        os.environ["NIRD_RESULTS_VARIANT"] = args.results_variant

    script4 = _load_script4_module()
    base_path = script4.base_path

    sctg_matrix_path = args.sctg_matrix or resolve_sctg_matrix_path(base_path)
    if not sctg_matrix_path.exists():
        raise FileNotFoundError(f"SCTG matrix not found: {sctg_matrix_path}")

    freight_candidates = resolve_disrupted_freight_candidates(
        script4, base_path, args.scenario_param, args.event_id
    )
    mix = compute_commodity_mix(freight_candidates, sctg_matrix_path)
    mix["hazard_label"] = args.hazard_label or str(args.scenario_param)
    mix["scenario_param"] = args.scenario_param
    mix["event_id"] = args.event_id
    mix["results_variant"] = get_results_variant()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(mix, indent=2))
    logging.info("Wrote %s", args.output)
    logging.info("Shares: %s", mix["shares"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
