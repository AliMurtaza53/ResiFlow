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
    scenario_for,
)
from toy_pipeline_fixtures import disruption_dir, reroute_dir, run_script


@pytest.fixture(scope="module")
def multihazard_baseline(tmp_path_factory) -> tuple[Path, dict[str, str]]:
    tmp = tmp_path_factory.mktemp("multihazard_base")
    config_path, _ = build_multihazard_dataset(tmp)
    env = multihazard_env(tmp, config_path, hazard_type="flood", flood_subtype="flood_surface")
    run_script("1_network_flow_model_revision.py", ["1", "1"], env)
    return tmp, env


def _run_hazard(tmp: Path, base_env: dict[str, str], hazard_type: str, *, flood_subtype: str | None = None, event: str = "1") -> int:
    env = multihazard_env(
        tmp,
        Path(base_env["NIRD_CONFIG_PATH"]),
        hazard_type=hazard_type,
        flood_subtype=flood_subtype,
    )
    scenario = scenario_for(
        hazard_type if hazard_type != "flood" else "flood",
        flood_subtype=flood_subtype,
        event_id=event,
    )
    scenario_param = scenario.scenario_param
    run_script("2_intersection_analysis.py", [str(scenario_param), event], env)
    run_script("3_damage_analysis.py", [], env)
    run_script(
        "4_rerouting_and_recovery_scenario_loop.py",
        [str(scenario_param), event, "1", "1"],
        env,
    )
    return scenario_param


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
    scenario_param = _run_hazard(tmp, base_env, hazard_type, flood_subtype=flood_subtype, event="1")
    links_path = (
        disruption_dir(tmp, base_env, depth_key=scenario_param)
        / "links"
        / "road_links_1.gpq"
    )
    assert links_path.exists(), links_path
    links = pd.read_parquet(links_path)
    assert "hazard_type" in links.columns or "max_speed" in links.columns
    reroute = reroute_dir(tmp, base_env, depth_key=scenario_param, event_key=1) / "cost_matrix_by_scenario.csv"
    has_categorical_damage = (
        "damage_level_max" in links.columns
        and links["damage_level_max"].astype(str).str.lower().ne("no").any()
    )
    if has_categorical_damage:
        assert reroute.exists(), reroute


def test_multihazard_unique_scenario_keys() -> None:
    """All multihazard registry keys must be unique for side-by-side comparison."""
    keys = [
        SCENARIO_KEYS["flood_surface"],
        SCENARIO_KEYS["flood_river"],
        SCENARIO_KEYS["flood_coastal"],
        SCENARIO_KEYS["earthquake"],
        SCENARIO_KEYS["landslide"],
        SCENARIO_KEYS["winter_storm"],
    ]
    assert len(keys) == len(set(keys))


def test_multihazard_miss_event_produces_no_disruption(multihazard_baseline) -> None:
    tmp, base_env = multihazard_baseline
    scenario_param = SCENARIO_KEYS["earthquake"]
    env = multihazard_env(tmp, Path(base_env["NIRD_CONFIG_PATH"]), hazard_type="earthquake")
    run_script("2_intersection_analysis.py", [str(scenario_param), "0"], env)
    links_path = disruption_dir(tmp, base_env, depth_key=scenario_param) / "links" / "road_links_0.gpq"
    if links_path.exists():
        links = pd.read_parquet(links_path)
        if "pga_max_g" in links.columns:
            assert float(links["pga_max_g"].max()) == 0.0
