"""Scenario registry unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from resiflow.hazards.base import parse_hazard_config
from resiflow.hazards.scenario_registry import (
    HazardScenario,
    load_hazard_manifest,
    lookup_scenario_by_env,
    resolve_active_scenario,
    scenario_param_from_path,
)


def test_parse_hazard_config_separates_closure_threshold() -> None:
    cfg = parse_hazard_config(
        {
            "hazard_type": "flood",
            "hazard_subtype": "flood_river",
            "event_id": "1",
            "scenario_param": 302,
            "closure_threshold": 30,
        }
    )
    assert cfg["scenario_param"] == 302
    assert cfg["closure_threshold"] == 30
    assert cfg["hazard_subtype"] == "flood_river"


def test_builtin_multihazard_keys_are_unique() -> None:
    import os

    cases = [
        ("flood", "flood_surface"),
        ("flood", "flood_river"),
        ("flood", "flood_coastal"),
        ("earthquake", None),
        ("landslide", None),
        ("winter_storm", None),
    ]
    keys: list[int] = []
    for hazard_type, flood_subtype in cases:
        if hazard_type == "flood":
            os.environ.pop("RESIFLOW_HAZARD_TYPE", None)
            if flood_subtype:
                os.environ["RESIFLOW_FLOOD_SUBTYPE"] = flood_subtype
        else:
            os.environ["RESIFLOW_HAZARD_TYPE"] = hazard_type
            os.environ.pop("RESIFLOW_FLOOD_SUBTYPE", None)
        found = lookup_scenario_by_env()
        assert found is not None
        keys.append(found.scenario_param)
    assert len(keys) == len(set(keys))


def test_resolve_active_scenario_legacy_fallback() -> None:
  scenario = resolve_active_scenario(scenario_param=30, event_id="1")
  assert scenario.scenario_param == 30
  assert scenario.closure_threshold == 30
  assert scenario.hazard_type == "flood"


def test_load_hazard_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "hazards.json"
    manifest.write_text(
        """
        {
          "events": [
            {
              "hazard_type": "earthquake",
              "event_id": "1",
              "scenario_param": 9001,
              "closure_threshold": 25
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    scenarios = load_hazard_manifest(manifest)
    assert len(scenarios) == 1
    assert scenarios[0].scenario_param == 9001
    assert scenarios[0].closure_threshold == 25


def test_scenario_param_from_path() -> None:
    path = Path("results/disruption_analysis/variant/302/intersections/intersections_1.pq")
    assert scenario_param_from_path(path) == "302"


def test_hazard_scenario_operational_threshold() -> None:
    scenario = HazardScenario(302, "flood", closure_threshold=30)
    assert scenario.operational_threshold == 30
    assert scenario.scenario_key == "302"
