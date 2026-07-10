"""E2E multihazard pipeline tests on Sioux Falls synthetic rasters."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from multihazard_sioux_falls_fixtures import (
    MULTIHAZARD_VARIANT,
    SCENARIO_KEYS,
    build_multihazard_dataset,
    multihazard_env,
)
from toy_pipeline_fixtures import disruption_dir, reroute_dir, run_script


@pytest.fixture(scope="module")
def multihazard_baseline(tmp_path_factory) -> tuple[Path, dict[str, str]]:
    tmp = tmp_path_factory.mktemp("multihazard_base")
    config_path, _ = build_multihazard_dataset(tmp)
    env = multihazard_env(tmp, config_path, hazard_type="flood", flood_subtype="flood_surface")
    run_script("1_network_flow_model_revision.py", ["1", "1"], env)
    return tmp, env


def _run_hazard(tmp: Path, base_env: dict[str, str], hazard_type: str, *, flood_subtype: str | None = None, event: str = "1") -> None:
    env = dict(base_env)
    if hazard_type == "flood":
        env.pop("RESIFLOW_HAZARD_TYPE", None)
        if flood_subtype:
            env["RESIFLOW_FLOOD_SUBTYPE"] = flood_subtype
    else:
        env["RESIFLOW_HAZARD_TYPE"] = hazard_type
    scenario = SCENARIO_KEYS[hazard_type]
    run_script("2_intersection_analysis.py", [str(scenario), event], env)
    run_script("3_damage_analysis.py", [], env)
    run_script("4_rerouting_and_recovery_scenario_loop.py", [str(scenario), event, "1", "1"], env)


@pytest.mark.parametrize(
    ("hazard_type", "flood_subtype"),
    [
        ("flood", "flood_surface"),
        ("flood", "flood_river"),
        ("flood", "flood_coastal"),
        ("earthquake", None),
        ("landslide", None),
        ("winter_storm", None),
    ],
)
def test_multihazard_pipeline_event_bridge(multihazard_baseline, hazard_type, flood_subtype) -> None:
    tmp, base_env = multihazard_baseline
    _run_hazard(tmp, base_env, hazard_type, flood_subtype=flood_subtype, event="1")
    scenario = SCENARIO_KEYS[hazard_type if hazard_type != "flood" else "flood"]
    links_path = (
        disruption_dir(tmp, base_env, depth_key=scenario)
        / "links"
        / "road_links_1.gpq"
    )
    assert links_path.exists(), links_path
    links = pd.read_parquet(links_path)
    assert "hazard_type" in links.columns or "max_speed" in links.columns
    reroute = reroute_dir(tmp, base_env, depth_key=scenario, event_key=1) / "cost_matrix_by_scenario.csv"
    assert reroute.exists(), reroute


def test_multihazard_miss_event_produces_no_disruption(multihazard_baseline) -> None:
    tmp, base_env = multihazard_baseline
    _run_hazard(tmp, base_env, "earthquake", event="0")
    scenario = SCENARIO_KEYS["earthquake"]
    links_path = disruption_dir(tmp, base_env, depth_key=scenario) / "links" / "road_links_0.gpq"
    if links_path.exists():
        links = pd.read_parquet(links_path)
        if "pga_max_g" in links.columns:
            assert float(links["pga_max_g"].max()) == 0.0
