"""Explicit demand cases: passenger-only runs end to end (Stages 1-4) and the loader switch."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from multihazard_sioux_falls_fixtures import (
    build_multihazard_dataset,
    multihazard_env,
    scenario_for,
)
from toy_pipeline_fixtures import reroute_dir, run_script

from resiflow.demand import demand_case


def test_demand_case_parsing(monkeypatch):
    monkeypatch.delenv("RESIFLOW_DEMAND_CASE", raising=False)
    monkeypatch.delenv("NIRD_DEMAND_CASE", raising=False)
    assert demand_case() is None
    for v in ("freight", "passenger", "combined"):
        monkeypatch.setenv("RESIFLOW_DEMAND_CASE", v.upper())
        assert demand_case() == v
    monkeypatch.setenv("RESIFLOW_DEMAND_CASE", "trucks")
    with pytest.raises(ValueError):
        demand_case()


@pytest.fixture(scope="module")
def passenger_only_run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pax_only")
    config_path, _ = build_multihazard_dataset(tmp)
    env = multihazard_env(tmp, config_path, hazard_type="flood", flood_subtype="flood_surface")
    env["RESIFLOW_DEMAND_CASE"] = "passenger"
    # Passenger-only means no freight OD may be needed: point the freight path at nothing.
    env["RESIFLOW_FAF5_OD_MATRIX_PATH"] = str(tmp / "does_not_exist.pq")
    env["NIRD_FAF5_OD_MATRIX_PATH"] = env["RESIFLOW_FAF5_OD_MATRIX_PATH"]
    run_script("1_network_flow_model_revision.py", ["1", "1"], env)
    scenario = scenario_for("flood", flood_subtype="flood_surface", event_id="1").scenario_param
    run_script("2_intersection_analysis.py", [str(scenario), "1"], env)
    run_script("3_damage_analysis.py", [], env)
    run_script("4_rerouting_and_recovery_scenario_loop.py", [str(scenario), "1", "1", "1"], env)
    return tmp, env, scenario


def test_passenger_only_stage4_outputs(passenger_only_run):
    tmp, env, scenario = passenger_only_run
    out = reroute_dir(tmp, env, depth_key=scenario, event_key=1)
    assert (out / "cost_matrix_passenger_by_scenario.csv").exists()
    assert (out / "cost_matrix_by_scenario.csv").exists()
    assert not (out / "cost_matrix_freight_by_scenario.csv").exists()
    cost = pd.read_csv(out / "cost_matrix_passenger_by_scenario.csv")
    assert len(cost) >= 1
    assert (cost["total_disrupted_flow"] >= 0).all()
    assert cost["total_disrupted_flow"].sum() > 0
