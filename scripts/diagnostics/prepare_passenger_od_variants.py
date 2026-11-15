"""Build passenger-only assignment OD variants for baseline profiling runs.

Outputs in --output-dir:
  passenger_conus_od.pq, passenger_conus_split_od.pq     (all counties)
  passenger_harvey15_od.pq, passenger_harvey15_split_od.pq (both ends in the 15 Harvey states)
  report.json
Jobs (LODES S000) are converted to daily vehicle trips (default: central_with_round_trip,
x1.46). The "split" files spread multi-connector counties equally over their official
connector road ends (see resiflow.demand.connector_split).
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from resiflow.demand.connector_split import build_node_targets, split_od
from resiflow.demand.passenger_conversion import SENSITIVITY_SCENARIOS, convert_jobs_to_vehicle_trips

HARVEY_STATES = ["48", "22", "49", "40", "06", "12", "39", "17", "13", "05", "42", "36", "28", "26", "18"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--od", type=Path, required=True, help="lodes_passenger_od_matrix_conterminous.pq")
    p.add_argument("--county-crosswalk", type=Path, required=True)
    p.add_argument("--connector-crosswalk", type=Path, required=True)
    p.add_argument("--scenario", default="central_with_round_trip", choices=sorted(SENSITIVITY_SCENARIOS))
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    a.output_dir.mkdir(parents=True, exist_ok=True)

    od = pd.read_parquet(a.od)
    od["origin_node"] = od["origin_node"].astype(str)
    od["destination_node"] = od["destination_node"].astype(str)
    jobs = float(od["Car21"].sum())
    od["Car21"] = convert_jobs_to_vehicle_trips(od["Car21"], SENSITIVITY_SCENARIOS[a.scenario])
    cw = pd.read_csv(a.county_crosswalk, dtype=str)
    conn = pd.read_csv(a.connector_crosswalk)
    targets = build_node_targets(cw, conn)
    node_state = cw.drop_duplicates("node_id").assign(node_id=lambda d: d.node_id.astype(str)).set_index("node_id")["state_fips"]
    in15 = od["origin_node"].map(node_state).isin(HARVEY_STATES) & od["destination_node"].map(node_state).isin(HARVEY_STATES)
    sets = {"conus": od, "harvey15": od[in15]}

    report = {"scenario": a.scenario, "jobs_in": jobs, "split_nodes": int(targets.groupby("node").size().gt(1).sum())}
    for name, frame in sets.items():
        split = split_od(frame, targets)
        assert abs(split["Car21"].sum() - frame["Car21"].sum()) < 1e-6 * frame["Car21"].sum()
        frame.to_parquet(a.output_dir / f"passenger_{name}_od.pq", index=False)
        split.to_parquet(a.output_dir / f"passenger_{name}_split_od.pq", index=False)
        self_flow = float(frame.loc[frame.origin_node == frame.destination_node, "Car21"].sum())
        report[name] = {
            "rows": len(frame), "rows_split": len(split),
            "vehicle_trips": float(frame["Car21"].sum()), "intrazonal_vehicle_trips": self_flow,
        }
    (a.output_dir / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
