"""Tests for NHCCI-based dollar-year harmonization."""

from __future__ import annotations

import pytest

from resiflow.nhcci import escalation_factor, latest_quarter, nhcci_index


def test_known_index_values_seasonally_adjusted():
    # Real values read directly from parameters/tables/NHCCI_20260922.csv.
    assert nhcci_index(2008, 4) == pytest.approx(1.652130652)
    assert nhcci_index(2018, 4) == pytest.approx(1.870604335)
    assert nhcci_index(2024, 4) == pytest.approx(3.238746815)
    assert nhcci_index(2026, 1) == pytest.approx(3.165451056)


def test_latest_quarter_is_2026_q1():
    assert latest_quarter() == (2026, 1)


def test_unknown_quarter_raises():
    with pytest.raises(ValueError):
        nhcci_index(1999, 1)


def test_escalation_factor_defaults_to_latest_quarter():
    factor = escalation_factor(2018, 4)
    expected = 3.165451056 / 1.870604335
    assert factor == pytest.approx(expected)


def test_escalation_factor_explicit_target():
    factor = escalation_factor(2008, 4, 2018, 4)
    expected = 1.870604335 / 1.652130652
    assert factor == pytest.approx(expected)


def test_escalation_factor_round_trip_is_identity():
    forward = escalation_factor(2018, 4, 2024, 4)
    backward = escalation_factor(2024, 4, 2018, 4)
    assert forward * backward == pytest.approx(1.0)
