"""Tests for the unified scalar-parameter loader (resiflow.parameters)."""

from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path

import pytest

from resiflow import constants, damage_aggregation
from resiflow.assignment.ue_bpr import (
    UELink,
    solve_tntp_user_equilibrium,
    solve_user_equilibrium,
)
from resiflow.disruption import earthquake, landslide, winter_storm
from resiflow.fragility.flood_operational import compute_maximum_speed_on_flooded_roads
from resiflow.parameters import clear_cache, get_parameter, load_unified_parameters
from resiflow.preprocess import faf5_network

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_PARAMETERS = REPO_ROOT / "parameters"


@pytest.fixture(autouse=True)
def _clear_parameter_cache():
    clear_cache()
    yield
    clear_cache()


def test_load_unified_parameters_returns_empty_dict_when_file_absent(tmp_path):
    assert load_unified_parameters(params_root=tmp_path) == {}


def test_get_parameter_falls_back_to_default_when_file_absent(tmp_path):
    value = get_parameter("conversions", "mile_to_km", 999.0, params_root=tmp_path)
    assert value == 999.0


def test_get_parameter_falls_back_to_default_when_section_or_key_missing(tmp_path):
    (tmp_path / "unified_parameters.json").write_text(
        json.dumps({"conversions": {}}), encoding="utf-8"
    )
    assert get_parameter("conversions", "mile_to_km", 999.0, params_root=tmp_path) == 999.0
    assert get_parameter("nonexistent_section", "x", 42, params_root=tmp_path) == 42


def test_get_parameter_applies_override_when_present(tmp_path):
    (tmp_path / "unified_parameters.json").write_text(
        json.dumps({"conversions": {"mile_to_km": 2.0}}), encoding="utf-8"
    )
    value = get_parameter("conversions", "mile_to_km", 1.60934, params_root=tmp_path)
    assert value == 2.0


def test_get_parameter_applies_dict_valued_override(tmp_path):
    (tmp_path / "unified_parameters.json").write_text(
        json.dumps(
            {
                "cost_time": {
                    "avg_vehicle_occupancy_car": 1.4,
                    "vot_usd_per_hour": {"car": 99.0},
                }
            }
        ),
        encoding="utf-8",
    )
    assert (
        get_parameter("cost_time", "avg_vehicle_occupancy_car", 1.1, params_root=tmp_path)
        == 1.4
    )
    assert get_parameter(
        "cost_time", "vot_usd_per_hour", {"car": 18.5}, params_root=tmp_path
    ) == {"car": 99.0}


def test_bundled_reference_file_matches_live_runtime_constants():
    """Guard against the repo's unified_parameters.json drifting from the
    hardcoded defaults it's meant to back."""
    data = load_unified_parameters(params_root=REPO_PARAMETERS)

    conversions = data["conversions"]
    assert conversions["meter_to_mile"] == pytest.approx(constants.CONV_METER_TO_MILE)
    assert conversions["mile_to_km"] == pytest.approx(constants.CONV_MILE_TO_KM)
    assert conversions["km_to_mile"] == pytest.approx(constants.CONV_KM_TO_MILE)
    assert conversions["pence_to_pound"] == pytest.approx(constants.PENCE_TO_POUND)
    assert conversions["gbp_to_usd"] == pytest.approx(constants.GBP_TO_USD)
    assert conversions["default_fuel_usd_per_litre"] == pytest.approx(
        constants.DEFAULT_FUEL_USD_PER_LITRE
    )

    ue_link_fields = {f.name: f.default for f in dataclasses.fields(UELink)}
    ue_bpr = data["assignment_ue_bpr"]
    assert ue_bpr["bpr_alpha"] == pytest.approx(ue_link_fields["alpha"])
    assert ue_bpr["bpr_beta"] == pytest.approx(ue_link_fields["beta"])
    assert ue_bpr["max_iterations"] == inspect.signature(
        solve_user_equilibrium
    ).parameters["max_iterations"].default
    assert ue_bpr["target_gap"] == pytest.approx(
        inspect.signature(solve_user_equilibrium).parameters["target_gap"].default
    )
    assert ue_bpr["demand_scale"] == pytest.approx(
        inspect.signature(solve_tntp_user_equilibrium).parameters["demand_scale"].default
    )

    assert data["damage_aggregation"]["musd_to_usd"] == pytest.approx(
        damage_aggregation.MUSD_TO_USD
    )

    # Script 4 cost-engine economics (constants.py <-> reference file).
    cost_time = data["cost_time"]
    assert cost_time["avg_vehicle_occupancy_car"] == pytest.approx(
        constants.AVG_VEHICLE_OCCUPANCY_CAR
    )
    assert cost_time["vot_usd_per_hour"] == constants.VOT_USD_PER_HOUR

    cost_operating = data["cost_operating"]
    assert cost_operating["fuel_usd_per_litre"] == constants.FUEL_USD_PER_LITRE
    assert cost_operating["fuel_litre_per_km"] == constants.FUEL_LITRE_PER_KM
    assert cost_operating["non_fuel_cost_coeffs"] == constants.NON_FUEL_PENCE_PER_KM

    preprocess = data["preprocess"]
    assert preprocess["faf5_default_lanes"] == faf5_network.DEFAULTS["lanes"]
    assert preprocess["faf5_default_avg_toll_cost"] == pytest.approx(
        faf5_network.DEFAULTS["average_toll_cost"]
    )
    assert preprocess["faf5_default_meters_per_lane"] == pytest.approx(
        faf5_network.DEFAULTS["meters_per_lane"]
    )
    # earth_radius_miles is owned by the top-level `preprocess` package
    # (src/preprocess/map_bts_od_to_network_centroids.py), a sibling of
    # `resiflow`, not the `resiflow.preprocess` sub-package checked above.
    # Unlike `resiflow` (which has a repo-root compatibility shim,
    # resiflow/__init__.py, extending its __path__ to src/resiflow), the
    # `preprocess` package has no such shim and isn't importable without
    # manual sys.path setup (as scripts/testbed/generate_synthetic_hazards.py
    # does for itself) -- fixing that is a packaging concern outside this
    # migration's scope, so this one key is checked structurally instead.
    assert "earth_radius_miles" in preprocess

    hazard = data["hazard_disruption"]
    flood_threshold_default = inspect.signature(
        compute_maximum_speed_on_flooded_roads
    ).parameters["threshold"].default
    assert hazard["flood_closure_threshold_cm"] == pytest.approx(flood_threshold_default)
    assert hazard["earthquake_script3_depth_scale"] == pytest.approx(
        earthquake.SCRIPT3_DEPTH_SCALE
    )
    assert hazard["landslide_script3_depth_scale"] == pytest.approx(
        landslide.SCRIPT3_DEPTH_SCALE
    )
    assert hazard["winter_storm_script3_depth_scale"] == pytest.approx(
        winter_storm.SCRIPT3_DEPTH_SCALE
    )

    # testbed_synthetic_hazards is intentionally not checked here:
    # scripts/testbed/generate_synthetic_hazards.py is not part of the
    # installed package (scripts/ is outside [tool.setuptools.packages.find]),
    # does its own sys.path manipulation, and has module-import-time side
    # effects (loads a testbed config via load_testbed()) that make direct
    # import from a unit test heavier and riskier than the check is worth.
    assert set(data["testbed_synthetic_hazards"]) == {
        "flood_peak_m",
        "coastal_peak_m",
        "river_peak_m",
        "pga_peak_g",
        "landslide_peak_mm",
        "winter_storm_peak_mm",
        "winter_storm_moderate_mm",
    }
