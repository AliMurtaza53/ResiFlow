"""Tests for T35-driven winter storm residual speed recovery (Script 4)."""

from __future__ import annotations

import pandas as pd
import pytest

from resiflow.hazards.winter_storm_clearance import (
    load_speed_recovery_table,
    residual_speed_factor_winter_storm,
)


def test_real_table_loads_with_5_rows():
    table = load_speed_recovery_table()
    assert set(table.keys()) == {0, 1, 2, 3, 4}
    assert table[0] == pytest.approx((0.7, 0.6))
    assert table[4] == pytest.approx((1.0, 1.0))


def test_not_yet_open_is_fully_closed():
    day_open = pd.Series([5.0])
    is_major = pd.Series([True])
    factor = residual_speed_factor_winter_storm(event_day=3, day_open=day_open, is_major=is_major)
    assert factor.iloc[0] == pytest.approx(0.0)


def test_day_of_opening_uses_day_zero_factor():
    day_open = pd.Series([5.0, 5.0])
    is_major = pd.Series([True, False])
    factor = residual_speed_factor_winter_storm(event_day=5, day_open=day_open, is_major=is_major)
    assert factor.iloc[0] == pytest.approx(0.7)  # major
    assert factor.iloc[1] == pytest.approx(0.6)  # minor


def test_two_days_after_opening():
    day_open = pd.Series([5.0, 5.0])
    is_major = pd.Series([True, False])
    factor = residual_speed_factor_winter_storm(event_day=7, day_open=day_open, is_major=is_major)
    assert factor.iloc[0] == pytest.approx(0.95)  # major
    assert factor.iloc[1] == pytest.approx(0.88)  # minor


def test_beyond_table_clamped_to_fully_recovered():
    day_open = pd.Series([5.0])
    is_major = pd.Series([False])
    factor = residual_speed_factor_winter_storm(event_day=30, day_open=day_open, is_major=is_major)
    assert factor.iloc[0] == pytest.approx(1.0)


def test_no_rank_is_unaffected_not_guessed():
    day_open = pd.Series([pd.NA], dtype="Int64")
    is_major = pd.Series([True])
    factor = residual_speed_factor_winter_storm(event_day=1, day_open=day_open, is_major=is_major)
    assert factor.iloc[0] == pytest.approx(1.0)


def test_day_open_zero_at_event_day_zero_is_pure_function_behavior():
    # day_open=0 is ALSO what T34 assigns to damage_level=="no" (never
    # closed at all) -- this function is agnostic to damage_level by
    # design (it only knows day_open/event_day), so it still returns
    # day-0's factor here rather than 1.0. The CALLER (Script 4, matching
    # the existing T37/T38 branch's own "skip if damage_level in (no,
    # none)" pattern) is responsible for never calling this at all for an
    # undamaged link -- see scripts/4_rerouting_and_recovery_scenario_loop.py.
    day_open = pd.Series([0.0])
    is_major = pd.Series([True])
    factor = residual_speed_factor_winter_storm(event_day=0, day_open=day_open, is_major=is_major)
    assert factor.iloc[0] == pytest.approx(0.7)
