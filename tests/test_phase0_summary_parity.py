"""Phase 0 Sioux Falls summary parity vs pinned baseline CSV."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VIZ_DIR = REPO_ROOT / "scripts" / "visualizations"
if str(VIZ_DIR) not in sys.path:
    sys.path.insert(0, str(VIZ_DIR))

from viz_data_loaders import summarize_single_scenario  # noqa: E402

from sioux_falls_fixtures import build_sioux_falls_dataset, sioux_falls_env
from toy_pipeline_fixtures import run_pipeline_scripts

BASELINE_CSV = REPO_ROOT / "docs" / "reference" / "phase0_flood_summary.csv"

PARITY_INT_COLUMNS = (
    "link_count",
    "flooded_links",
    "closed_links",
    "damaged_links",
    "depth_key",
    "flood_key",
)

PARITY_FLOAT_COLUMNS = (
    "max_flood_depth_m",
    "freight_disrupted_flow",
    "passenger_disrupted_flow",
    "rerouting_cost_freight_usd",
    "rerouting_cost_passenger_usd",
    "direct_damage_usd",
    "combined_total_usd",
    "passenger_flooded_edge_flow",
)


@pytest.fixture(scope="module")
def phase0_baseline_row():
    import pandas as pd

    if not BASELINE_CSV.exists():
        pytest.skip(f"baseline CSV missing: {BASELINE_CSV}")
    table = pd.read_csv(BASELINE_CSV)
    sioux = table.loc[table["variant"] == "toy_sioux_falls"]
    if sioux.empty:
        pytest.skip("no toy_sioux_falls row in baseline CSV")
    return sioux.iloc[0].to_dict()


def test_sioux_falls_summary_matches_phase0_baseline(tmp_path, phase0_baseline_row) -> None:
    config_path, _spec, _links = build_sioux_falls_dataset(tmp_path)
    env = sioux_falls_env(tmp_path, config_path)
    run_pipeline_scripts(env)

    results_root = tmp_path / "results"
    summary = summarize_single_scenario(
        results_root,
        variant=env["NIRD_RESULTS_VARIANT"],
        depth_key=30,
        flood_key=1,
    )

    for col in PARITY_INT_COLUMNS:
        assert int(summary[col]) == int(phase0_baseline_row[col]), col

    for col in PARITY_FLOAT_COLUMNS:
        assert float(summary[col]) == pytest.approx(float(phase0_baseline_row[col]), rel=1e-4), col
