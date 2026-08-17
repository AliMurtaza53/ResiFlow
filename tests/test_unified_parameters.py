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
from resiflow.parameters import (
    active_overrides_path,
    clear_cache,
    get_parameter,
    load_unified_parameters,
)
from resiflow.preprocess import faf5_network

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_PARAMETERS = REPO_ROOT / "parameters"

_OVERRIDES_ENV = "RESIFLOW_PARAM_OVERRIDES"


@pytest.fixture(autouse=True)
def _clear_parameter_cache(monkeypatch):
    monkeypatch.delenv(_OVERRIDES_ENV, raising=False)
    clear_cache()
    yield
    clear_cache()


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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


def test_active_overrides_path_reflects_env(monkeypatch, tmp_path):
    assert active_overrides_path() is None
    ov = tmp_path / "overrides.json"
    monkeypatch.setenv(_OVERRIDES_ENV, str(ov))
    assert active_overrides_path() == ov


def test_overrides_deep_merge_patches_without_clobbering_siblings(monkeypatch, tmp_path):
    _write_json(
        tmp_path / "unified_parameters.json",
        {
            "cost_time": {
                "avg_vehicle_occupancy_car": 1.67,
                "vot_usd_per_hour": {"car": 21.80, "ogv": 37.20},
            },
            "conversions": {"mile_to_km": 1.60934},
        },
    )
    ov = _write_json(
        tmp_path / "ov.json",
        {"cost_time": {"vot_usd_per_hour": {"car": 30.0}}},
    )
    monkeypatch.setenv(_OVERRIDES_ENV, str(ov))
    data = load_unified_parameters(params_root=tmp_path)
    # patched leaf wins ...
    assert data["cost_time"]["vot_usd_per_hour"]["car"] == 30.0
    # ... sibling leaves and sibling sections survive the merge
    assert data["cost_time"]["vot_usd_per_hour"]["ogv"] == 37.20
    assert data["cost_time"]["avg_vehicle_occupancy_car"] == 1.67
    assert data["conversions"]["mile_to_km"] == 1.60934


def test_overrides_scale_multiplies_scalar(monkeypatch, tmp_path):
    _write_json(
        tmp_path / "unified_parameters.json",
        {"hazard_disruption": {"flood_closure_threshold_cm": 30}},
    )
    ov = _write_json(
        tmp_path / "ov.json",
        {"_scales": {"hazard_disruption.flood_closure_threshold_cm": 0.5}},
    )
    monkeypatch.setenv(_OVERRIDES_ENV, str(ov))
    assert get_parameter(
        "hazard_disruption", "flood_closure_threshold_cm", 30, params_root=tmp_path
    ) == pytest.approx(15.0)


def test_overrides_scale_multiplies_every_numeric_leaf_of_dict(monkeypatch, tmp_path):
    _write_json(
        tmp_path / "unified_parameters.json",
        {
            "cost_time": {
                "vot_usd_per_hour": {"car": 20.0, "ogv": 40.0, "label": "usd"},
            }
        },
    )
    ov = _write_json(tmp_path / "ov.json", {"_scales": {"cost_time.vot_usd_per_hour": 1.1}})
    monkeypatch.setenv(_OVERRIDES_ENV, str(ov))
    vot = get_parameter("cost_time", "vot_usd_per_hour", {}, params_root=tmp_path)
    assert vot["car"] == pytest.approx(22.0)
    assert vot["ogv"] == pytest.approx(44.0)
    assert vot["label"] == "usd"  # non-numeric leaves untouched


def test_overrides_scale_never_scales_bools(monkeypatch, tmp_path):
    _write_json(
        tmp_path / "unified_parameters.json",
        {"flags": {"opts": {"enabled": True, "weight": 2.0}}},
    )
    ov = _write_json(tmp_path / "ov.json", {"_scales": {"flags.opts": 3.0}})
    monkeypatch.setenv(_OVERRIDES_ENV, str(ov))
    opts = get_parameter("flags", "opts", {}, params_root=tmp_path)
    assert opts["enabled"] is True
    assert opts["weight"] == pytest.approx(6.0)


def test_overrides_scale_unknown_path_raises_keyerror(monkeypatch, tmp_path):
    _write_json(tmp_path / "unified_parameters.json", {"conversions": {"mile_to_km": 1.6}})
    ov = _write_json(tmp_path / "ov.json", {"_scales": {"conversions.no_such_key": 2.0}})
    monkeypatch.setenv(_OVERRIDES_ENV, str(ov))
    with pytest.raises(KeyError):
        load_unified_parameters(params_root=tmp_path)


def test_overrides_scale_applies_to_merged_values(monkeypatch, tmp_path):
    """A _scales path may target a key introduced by the same overrides file."""
    _write_json(tmp_path / "unified_parameters.json", {"conversions": {"mile_to_km": 1.6}})
    ov = _write_json(
        tmp_path / "ov.json",
        {"assignment": {"capacity_scale": 0.8}, "_scales": {"assignment.capacity_scale": 2.0}},
    )
    monkeypatch.setenv(_OVERRIDES_ENV, str(ov))
    assert get_parameter(
        "assignment", "capacity_scale", 1.0, params_root=tmp_path
    ) == pytest.approx(1.6)


def test_cache_is_keyed_by_overrides_path(monkeypatch, tmp_path):
    _write_json(tmp_path / "unified_parameters.json", {"conversions": {"mile_to_km": 1.6}})
    # populate cache with no overrides in force
    assert get_parameter("conversions", "mile_to_km", 0.0, params_root=tmp_path) == 1.6
    ov = _write_json(tmp_path / "ov.json", {"conversions": {"mile_to_km": 9.9}})
    monkeypatch.setenv(_OVERRIDES_ENV, str(ov))
    # no clear_cache(): the overrides path is part of the cache key
    assert get_parameter("conversions", "mile_to_km", 0.0, params_root=tmp_path) == 9.9
    monkeypatch.delenv(_OVERRIDES_ENV)
    assert get_parameter("conversions", "mile_to_km", 0.0, params_root=tmp_path) == 1.6


def test_missing_overrides_file_raises(monkeypatch, tmp_path):
    _write_json(tmp_path / "unified_parameters.json", {"conversions": {"mile_to_km": 1.6}})
    monkeypatch.setenv(_OVERRIDES_ENV, str(tmp_path / "does_not_exist.json"))
    with pytest.raises(FileNotFoundError):
        load_unified_parameters(params_root=tmp_path)


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
