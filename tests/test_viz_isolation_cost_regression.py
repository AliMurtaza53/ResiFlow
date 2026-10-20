"""Regression test for the two isolation-cost bugs fixed in d5bad4f.

Both bugs silently zeroed isolation cost/flow in every multihazard summary
this project ever produced: (1) _isolation_metrics looked for
trip_isolations_*_day1.csv, but the real pipeline only ever writes
day0/7/14/30/60/90 checkpoints, so the file never matched; (2) _first_cost_row
whitelisted a fixed set of columns that didn't include isolation_cost, so
even when the column existed in the CSV row it was dropped before reaching
the summary. Neither had test coverage, so both shipped unnoticed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VIZ_DIR = REPO_ROOT / "scripts" / "visualizations"
if str(VIZ_DIR) not in sys.path:
    sys.path.insert(0, str(VIZ_DIR))

from viz_data_loaders import (  # noqa: E402
    _first_cost_row,
    _isolation_metrics,
    summarize_single_scenario,
)

VARIANT = "toy_isolation_regression"
DEPTH_KEY = 30
FLOOD_KEY = 1
SCENARIO_ID = 1


def _write_reroute_fixtures(results_root: Path) -> Path:
    reroute_dir = results_root / "rerouting_analysis" / VARIANT / str(DEPTH_KEY) / str(FLOOD_KEY)
    reroute_dir.mkdir(parents=True, exist_ok=True)

    # Cost matrices: both modes carry a nonzero isolation_cost column, same
    # shape as the real pipeline's cost_matrix_*_by_scenario.csv.
    freight_cost = pd.DataFrame(
        [
            {
                "total_disrupted_flow": 500.0,
                "total_disrupted_flow_unique_od": 480.0,
                "rerouting_cost": 1200.0,
                "direct_damage_total_usd": 50_000.0,
                "combined_total_cost": 53_500.0,
                "isolation_cost": 2_300.0,
            }
        ]
    )
    freight_cost.to_csv(reroute_dir / "cost_matrix_by_scenario.csv", index=False)

    passenger_cost = pd.DataFrame(
        [
            {
                "total_disrupted_flow": 200.0,
                "total_disrupted_flow_unique_od": 190.0,
                "rerouting_cost": 400.0,
                "isolation_cost": 150.0,
            }
        ]
    )
    passenger_cost.to_csv(reroute_dir / "cost_matrix_passenger_by_scenario.csv", index=False)

    # Isolation rows: only the day0 checkpoint exists, matching every real
    # run so far -- a day1 file is deliberately NOT written here, so a
    # regression back to the old day1 lookup would see no file and report
    # zero isolation flow again.
    freight_iso = pd.DataFrame({"od_id": [1, 2, 3], "Car21": [10.0, 25.0, 5.0]})
    freight_iso.to_csv(reroute_dir / f"trip_isolations_freight_s{SCENARIO_ID}_day0.csv", index=False)

    passenger_iso = pd.DataFrame({"od_id": [1], "Car21": [8.0]})
    passenger_iso.to_csv(reroute_dir / f"trip_isolations_passenger_s{SCENARIO_ID}_day0.csv", index=False)

    return reroute_dir


def test_isolation_metrics_reads_day0_not_day1(tmp_path) -> None:
    results_root = tmp_path / "results"
    reroute_dir = _write_reroute_fixtures(results_root)

    metrics = _isolation_metrics(reroute_dir, scenario_id=SCENARIO_ID)

    assert metrics["isolation_rows_freight"] == 3
    assert metrics["isolation_flow_freight"] == pytest.approx(40.0)
    assert metrics["isolation_rows_passenger"] == 1
    assert metrics["isolation_flow_passenger"] == pytest.approx(8.0)
    assert metrics["isolation_rows"] == 4
    assert metrics["isolation_flow"] == pytest.approx(48.0)


def test_isolation_metrics_ignores_day1_only_files(tmp_path) -> None:
    """A day1-only file (no day0) must NOT be picked up -- guards against
    reverting to the old (wrong) day1 lookup."""
    results_root = tmp_path / "results"
    reroute_dir = results_root / "rerouting_analysis" / VARIANT / str(DEPTH_KEY) / str(FLOOD_KEY)
    reroute_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"od_id": [1], "Car21": [999.0]}).to_csv(
        reroute_dir / f"trip_isolations_freight_s{SCENARIO_ID}_day1.csv", index=False
    )

    metrics = _isolation_metrics(reroute_dir, scenario_id=SCENARIO_ID)

    assert metrics["isolation_rows_freight"] == 0
    assert metrics["isolation_flow_freight"] == 0.0


def test_first_cost_row_keeps_isolation_cost(tmp_path) -> None:
    results_root = tmp_path / "results"
    reroute_dir = _write_reroute_fixtures(results_root)

    row = _first_cost_row(reroute_dir / "cost_matrix_by_scenario.csv")

    assert "isolation_cost" in row
    assert row["isolation_cost"] == pytest.approx(2_300.0)


def test_summarize_single_scenario_surfaces_nonzero_isolation_cost(tmp_path) -> None:
    results_root = tmp_path / "results"
    _write_reroute_fixtures(results_root)

    summary = summarize_single_scenario(
        results_root,
        variant=VARIANT,
        depth_key=DEPTH_KEY,
        flood_key=FLOOD_KEY,
        recovery_scenario=SCENARIO_ID,
    )

    assert summary["isolation_cost_freight_usd"] == pytest.approx(2_300.0)
    assert summary["isolation_cost_passenger_usd"] == pytest.approx(150.0)
    assert summary["isolation_cost_usd"] == pytest.approx(2_450.0)
    assert summary["isolation_rows"] == 4
    assert summary["isolation_flow"] == pytest.approx(48.0)
