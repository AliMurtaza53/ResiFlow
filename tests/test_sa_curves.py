"""Tests for resiflow.sa.curves and the vulnerability-parameter wiring."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from resiflow.parameters import clear_cache
from resiflow.sa.curves import mix_damage_curves, scale_depth_axis, speed_depth

_OVERRIDES_ENV = "RESIFLOW_PARAM_OVERRIDES"


@pytest.fixture(autouse=True)
def _clean_parameter_state(monkeypatch):
    monkeypatch.delenv(_OVERRIDES_ENV, raising=False)
    clear_cache()
    yield
    clear_cache()


def _ratio_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "intensity": [0.0, 0.5, 1.0, 2.0],
            "C1": [0.0, 0.1, 0.2, 0.4],
            "C2": [0.0, 0.3, 0.6, 0.8],
            "C3": [0.0, 0.05, 0.1, 0.2],
            "C4": [0.0, 0.15, 0.3, 0.5],
            "C5": [0.0, 0.2, 0.4, 0.6],
            "C6": [0.0, 0.4, 0.7, 1.0],
        }
    )


# ---------------------------------------------------------------------------
# mix_damage_curves
# ---------------------------------------------------------------------------

def test_mix_theta_zero_keeps_low_flow_curve():
    df = _ratio_frame()
    out = mix_damage_curves(df, 0.0)
    for low, high in (("C1", "C2"), ("C3", "C4"), ("C5", "C6")):
        np.testing.assert_allclose(out[low], df[low])
        np.testing.assert_allclose(out[high], df[low])


def test_mix_theta_one_keeps_high_flow_curve():
    df = _ratio_frame()
    out = mix_damage_curves(df, 1.0)
    np.testing.assert_allclose(out["C1"], df["C2"])
    np.testing.assert_allclose(out["C2"], df["C2"])


def test_mix_theta_half_is_midpoint_and_pairs_agree():
    df = _ratio_frame()
    out = mix_damage_curves(df, 0.5)
    np.testing.assert_allclose(out["C5"], (df["C5"] + df["C6"]) / 2.0)
    np.testing.assert_allclose(out["C5"], out["C6"])


def test_mix_preserves_monotonicity_and_bounds():
    out = mix_damage_curves(_ratio_frame(), 0.37)
    for col in ("C1", "C3", "C5"):
        vals = out[col].to_numpy()
        assert np.all(np.diff(vals) >= 0)
        assert vals.min() >= 0.0 and vals.max() <= 1.0


def test_mix_keeps_column_layout_for_create_damage_curves():
    df = _ratio_frame()
    out = mix_damage_curves(df, 0.5)
    assert list(out.columns) == list(df.columns)


def test_mix_unmatched_pairs_raise():
    df = pd.DataFrame({"intensity": [0, 1], "Interstate": [0.0, 0.5]})
    with pytest.raises(KeyError):
        mix_damage_curves(df, 0.5)


def test_mix_rejects_theta_out_of_range():
    with pytest.raises(ValueError):
        mix_damage_curves(_ratio_frame(), 1.5)


def test_mix_requires_intensity_column():
    with pytest.raises(KeyError):
        mix_damage_curves(pd.DataFrame({"C1": [0.1], "C2": [0.2]}), 0.5)


# ---------------------------------------------------------------------------
# scale_depth_axis
# ---------------------------------------------------------------------------

def test_scale_depth_axis_identity_at_lambda_one():
    df = _ratio_frame()
    out = scale_depth_axis(df, 1.0)
    for col in df.columns:
        np.testing.assert_allclose(out[col], df[col])


def test_scale_depth_axis_shifts_damage_onset():
    df = _ratio_frame()
    out = scale_depth_axis(df, 2.0)
    # At recorded depth 1.0 the curve now returns the original value at 0.5.
    row = out.loc[df["intensity"] == 1.0].iloc[0]
    assert row["C1"] == pytest.approx(0.1)
    # lambda > 1 => damage starts deeper => damage at a given depth decreases
    assert (out["C1"] <= df["C1"] + 1e-12).all()


def test_scale_depth_axis_clamps_beyond_grid():
    df = _ratio_frame()
    out = scale_depth_axis(df, 0.5)
    # depth 2.0 evaluates at 4.0, beyond the grid -> clamped to end value
    row = out.loc[df["intensity"] == 2.0].iloc[0]
    assert row["C1"] == pytest.approx(0.4)


def test_scale_depth_axis_rejects_nonpositive_lambda():
    with pytest.raises(ValueError):
        scale_depth_axis(_ratio_frame(), 0.0)


# ---------------------------------------------------------------------------
# speed_depth
# ---------------------------------------------------------------------------

def test_speed_depth_p2_reproduces_pregnolato_quadratic():
    from resiflow.fragility.flood_operational import (
        compute_maximum_speed_on_flooded_roads,
    )

    for depth_m in (0.0, 0.05, 0.15, 0.29, 0.30, 0.5):
        expected = compute_maximum_speed_on_flooded_roads(depth_m, 60.0, threshold=30)
        got = speed_depth(60.0, depth_m * 100.0, 30.0, p=2.0)
        assert got == pytest.approx(expected)


def test_speed_depth_closes_at_threshold():
    assert speed_depth(60.0, 30.0, 30.0, p=1.5) == 0.0
    assert speed_depth(60.0, 45.0, 30.0, p=1.5) == 0.0


def test_speed_depth_linear_alternate():
    assert speed_depth(60.0, 15.0, 30.0, p=1.0) == pytest.approx(30.0)


def test_speed_depth_accepts_arrays():
    v = speed_depth(60.0, np.array([0.0, 15.0, 30.0]), 30.0, p=2.0)
    np.testing.assert_allclose(v, [60.0, 15.0, 0.0])


def test_speed_depth_validates_inputs():
    with pytest.raises(ValueError):
        speed_depth(60.0, 10.0, 0.0)
    with pytest.raises(ValueError):
        speed_depth(60.0, 10.0, 30.0, p=0.0)


# ---------------------------------------------------------------------------
# wiring: damage_threshold_scale (flood_categorical)
# ---------------------------------------------------------------------------

def test_damage_threshold_scale_shifts_categorical_levels(monkeypatch, tmp_path):
    from resiflow.fragility.flood_categorical import (
        compute_damage_level_on_flooded_roads,
        compute_damage_levels_on_flooded_roads_vectorized,
    )

    # Baseline: river / minor road, 60 cm >= 50 -> "moderate"
    assert (
        compute_damage_level_on_flooded_roads("river", "tertiary", "no", "road", 0.6)
        == "moderate"
    )

    ov = tmp_path / "ov.json"
    ov.write_text(
        json.dumps({"vulnerability": {"damage_threshold_scale": 2.0}}),
        encoding="utf-8",
    )
    monkeypatch.setenv(_OVERRIDES_ENV, str(ov))
    clear_cache()

    # Scaled: threshold 50 -> 100 cm, so 60 cm is now only "minor"
    assert (
        compute_damage_level_on_flooded_roads("river", "tertiary", "no", "road", 0.6)
        == "minor"
    )
    vec = compute_damage_levels_on_flooded_roads_vectorized(
        "river",
        pd.Series(["tertiary"]),
        pd.Series(["no"]),
        pd.Series(["road"]),
        pd.Series([0.6]),
    )
    assert vec.iloc[0] == "minor"


# ---------------------------------------------------------------------------
# wiring: speed_depth_exponent (flood_operational, import-time default)
# ---------------------------------------------------------------------------

def test_speed_depth_exponent_override_takes_effect_on_import(monkeypatch, tmp_path):
    import resiflow.fragility.flood_operational as fo

    ov = tmp_path / "ov.json"
    ov.write_text(
        json.dumps({"hazard_disruption": {"speed_depth_exponent": 1.0}}),
        encoding="utf-8",
    )
    monkeypatch.setenv(_OVERRIDES_ENV, str(ov))
    clear_cache()
    try:
        fo = importlib.reload(fo)
        # linear rule: half the threshold depth -> half the free-flow speed
        assert fo.compute_maximum_speed_on_flooded_roads(
            0.15, 60.0, threshold=30
        ) == pytest.approx(30.0)
    finally:
        monkeypatch.delenv(_OVERRIDES_ENV)
        clear_cache()
        fo = importlib.reload(fo)
    # restored default is quadratic again
    assert fo.compute_maximum_speed_on_flooded_roads(
        0.15, 60.0, threshold=30
    ) == pytest.approx(15.0)
