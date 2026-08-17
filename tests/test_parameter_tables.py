"""Tests for the discretized parameter tables (parameters/tables) and their
opt-in wiring: loader header-skip + interpolation, status enforcement, and
flag-off runs staying on the historical code paths (bit-identical baseline)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import resiflow.tables as rt
from resiflow.parameters import clear_cache
from resiflow.tables import interpolate, load_table, recovery_schedule_from_table

REPO_ROOT = Path(__file__).resolve().parents[1]
_OVERRIDES_ENV = "RESIFLOW_PARAM_OVERRIDES"


@pytest.fixture(autouse=True)
def _clean_params_env(monkeypatch):
    monkeypatch.delenv(_OVERRIDES_ENV, raising=False)
    monkeypatch.delenv("RESIFLOW_PARAMETERS_ROOT", raising=False)
    monkeypatch.delenv("NIRD_PARAMETERS_ROOT", raising=False)
    clear_cache()
    yield
    clear_cache()


def _enable(monkeypatch, tmp_path, payload: dict) -> None:
    """Point RESIFLOW_PARAM_OVERRIDES at a payload enabling table flags."""
    ov_path = tmp_path / "overrides.json"
    ov_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv(_OVERRIDES_ENV, str(ov_path))
    clear_cache()


# ---------------------------------------------------------------------------
# loader: header skip, interpolation, status enforcement
# ---------------------------------------------------------------------------

def test_load_table_skips_provenance_headers():
    table = load_table("T04_fuel_consumption_speed_UK_TAG_current")
    assert list(table.columns)[:2] == ["speed_kmh", "speed_mph"]
    assert "fuel_l_per_km_car" in table.columns
    assert table["speed_kmh"].iloc[0] == 10
    # no header text leaked into data
    assert not table.iloc[:, 0].astype(str).str.startswith("#").any()


def test_interpolation_round_trip_and_midpoint():
    table = load_table("T04_fuel_consumption_speed_UK_TAG_current")
    # exact at grid points
    for _, row in table.iterrows():
        assert interpolate(table, row["speed_kmh"], "fuel_l_per_km_car") == pytest.approx(
            row["fuel_l_per_km_car"]
        )
    # linear between grid points
    assert interpolate(table, 15.0, "fuel_l_per_km_car") == pytest.approx(
        (0.1323 + 0.1005) / 2
    )
    # vector input, prefix column matching (US candidate ogv_truck), axis pinning
    us = load_table("T04_fuel_consumption_speed_US_candidate")
    vals = interpolate(us, np.array([8.0, 16.1]), "fuel_l_per_km_ogv", axis_column="speed_kmh")
    assert vals == pytest.approx([0.893, 0.682])


def test_t19_matches_closed_form_quadratic_at_grid_points():
    table = load_table("T19_speed_depth_curve_discretized")
    for xd in (15, 30, 60):
        col = f"v_ratio_xd{xd}"
        for _, row in table.iterrows():
            d = row["flood_depth_cm"]
            expected = (1.0 - d / xd) ** 2 if d <= xd else 0.0
            assert interpolate(table, d, col) == pytest.approx(expected, abs=1e-4)


def test_placeholder_rows_are_refused(caplog):
    with caplog.at_level(logging.WARNING, logger="resiflow.tables"):
        table = load_table("T20_damage_level_depth_thresholds")
    assert not (table["flood_type"] == "coastal").any()
    assert any("PLACEHOLDER_DO_NOT_USE" in r.message for r in caplog.records)


def test_approximate_and_template_files_warn(caplog):
    with caplog.at_level(logging.WARNING, logger="resiflow.tables"):
        load_table("T04_fuel_consumption_speed_US_candidate")
        load_table("T22_damage_ratio_curves_TEMPLATE")
    warned = [r.message for r in caplog.records if "not authoritative" in r.message]
    assert len(warned) == 2


def test_tables_root_follows_parameters_root_env(monkeypatch, tmp_path):
    monkeypatch.setenv("RESIFLOW_PARAMETERS_ROOT", str(tmp_path))
    assert rt.tables_root() == tmp_path / "tables"
    with pytest.raises(FileNotFoundError):
        load_table("T19_speed_depth_curve_discretized")


# ---------------------------------------------------------------------------
# no-flag baseline: consumers never touch the tables directory
# ---------------------------------------------------------------------------

def test_default_runs_never_load_tables(monkeypatch):
    def _boom(*args, **kwargs):  # pragma: no cover - failure path
        raise AssertionError("load_table called on a no-flag run")

    monkeypatch.setattr(rt, "load_table", _boom)

    from resiflow.fragility.flood_categorical import (
        compute_damage_levels_on_flooded_roads_vectorized,
    )
    from resiflow.fragility.flood_operational import apply_max_speed_to_links
    from resiflow.networks.profiles import load_assignment_profiles

    frame = pd.DataFrame(
        {"flood_depth_max": [0.1, 0.7], "free_flow_speeds": [60.0, 60.0]}
    )
    out = apply_max_speed_to_links(frame, depth_key=30)
    assert out["max_speed"].iloc[0] == pytest.approx(60.0 * (10 / 30 - 1) ** 2)
    assert out["max_speed"].iloc[1] == 0.0

    levels = compute_damage_levels_on_flooded_roads_vectorized(
        "river",
        pd.Series(["motorway", "tertiary"]),
        pd.Series(["", ""]),
        pd.Series(["road", "road"]),
        pd.Series([1.5, 0.3]),
    )
    assert levels.tolist() == ["moderate", "minor"]

    profiles = load_assignment_profiles(params_root=REPO_ROOT / "parameters")
    assert profiles["flow_cap_plph"]["freeway"] == 2400


# ---------------------------------------------------------------------------
# flag-on wiring (via RESIFLOW_PARAM_OVERRIDES, the SA injection seam)
# ---------------------------------------------------------------------------

def test_t08_table_profiles_match_assignment_profiles_json(monkeypatch, tmp_path):
    from resiflow.networks.profiles import load_assignment_profiles

    baseline = load_assignment_profiles(params_root=REPO_ROOT / "parameters")
    _enable(monkeypatch, tmp_path, {"assignment": {"use_table_tier_values": True}})
    from_table = load_assignment_profiles(params_root=REPO_ROOT / "parameters")
    # T08a is a verbatim discretization of assignment_profiles.json
    assert from_table == baseline


def test_t19_table_speed_depth_matches_formula_at_grid(monkeypatch, tmp_path):
    from resiflow.fragility.flood_operational import apply_max_speed_to_links

    depths_m = pd.Series([0.0, 0.05, 0.10, 0.15, 0.25, 0.45])
    frame = pd.DataFrame(
        {"flood_depth_max": depths_m, "free_flow_speeds": 60.0}
    )
    baseline = apply_max_speed_to_links(frame, depth_key=30)["max_speed"]

    _enable(monkeypatch, tmp_path, {"hazard_disruption": {"use_table_speed_depth": True}})
    tabled = apply_max_speed_to_links(frame, depth_key=30)["max_speed"]
    # table is the 4-dp discretization of the same quadratic
    assert np.allclose(tabled, baseline, atol=60.0 * 1e-4)


def test_t19_table_unknown_threshold_fails_loud(monkeypatch, tmp_path):
    from resiflow.fragility.flood_operational import (
        compute_maximum_speed_on_flooded_roads,
    )

    _enable(monkeypatch, tmp_path, {"hazard_disruption": {"use_table_speed_depth": True}})
    with pytest.raises(ValueError, match="no column"):
        compute_maximum_speed_on_flooded_roads(0.1, 60.0, threshold=45)


def test_t20_table_thresholds_match_code_thresholds(monkeypatch, tmp_path):
    from resiflow.fragility import flood_categorical as fc

    road_classes = pd.Series(["motorway", "motorway", "tertiary", "primary", "tertiary"])
    blank = pd.Series([""] * 5)
    depths = pd.Series([0.6, 2.5, 0.3, 7.0, 0.05])  # m

    for fld in ("river", "surface"):
        baseline = fc.compute_damage_levels_on_flooded_roads_vectorized(
            fld, road_classes, blank, blank, depths
        )
        _enable(
            monkeypatch, tmp_path, {"vulnerability": {"use_table_damage_thresholds": True}}
        )
        tabled = fc.compute_damage_levels_on_flooded_roads_vectorized(
            fld, road_classes, blank, blank, depths
        )
        assert tabled.tolist() == baseline.tolist()
        monkeypatch.delenv(_OVERRIDES_ENV)
        clear_cache()


def test_t20_table_mode_refuses_coastal(monkeypatch, tmp_path):
    from resiflow.fragility import flood_categorical as fc

    _enable(
        monkeypatch, tmp_path, {"vulnerability": {"use_table_damage_thresholds": True}}
    )
    with pytest.raises(ValueError, match="coastal"):
        fc.compute_damage_level_on_flooded_roads("coastal", "motorway", "", "road", 1.0)


def test_t04_t05_table_costs_match_formula_at_grid_speed(monkeypatch, tmp_path):
    from resiflow.road_revised import compute_costs_for_links

    # one link traversed at exactly 50 km/h (a T04/T05 grid speed)
    frame = pd.DataFrame({"time_hr": [1.0], "length_mile": [50.0 / 1.60934]})
    baseline = compute_costs_for_links(frame.copy(), "ogv", inplace=False)

    _enable(
        monkeypatch,
        tmp_path,
        {
            "cost_operating": {
                "use_table_fuel_curve": True,
                "use_table_nonfuel_curve": True,
            }
        },
    )
    tabled = compute_costs_for_links(frame.copy(), "ogv", inplace=False)
    # tables are 2-4 dp discretizations of the same curves
    assert tabled["operating_cost"].iloc[0] == pytest.approx(
        baseline["operating_cost"].iloc[0], abs=0.05
    )
    assert tabled["time_cost"].iloc[0] == baseline["time_cost"].iloc[0]


# ---------------------------------------------------------------------------
# T26 recovery schedule derivation
# ---------------------------------------------------------------------------

def test_recovery_schedule_fast_scenario_steps():
    recovery, days = recovery_schedule_from_table(scenario="fast")
    assert days == [0, 30, 45, 60]
    assert recovery["minor"] == [1.0, 1.0, 1.0, 1.0]  # no capacity loss
    assert recovery["moderate"] == [1.0, 1.0, 1.0, 1.0]
    assert recovery["extensive"] == [0.0, 0.5, 1.0, 1.0]
    assert recovery["severe"] == [0.0, 0.0, 0.5, 1.0]


def test_recovery_schedule_average_scenario_steps():
    recovery, days = recovery_schedule_from_table(scenario="average")
    assert days == [0, 60, 90, 110]
    assert recovery["extensive"] == [0.0, 0.5, 1.0, 1.0]
    assert recovery["severe"] == [0.0, 0.0, 0.5, 1.0]


def test_recovery_schedule_unknown_scenario_fails_loud():
    with pytest.raises(ValueError, match="known"):
        recovery_schedule_from_table(scenario="heroic")
