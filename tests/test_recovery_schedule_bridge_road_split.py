"""Tests for the T26 bridge/road recovery-schedule split (Script 4).

docs/FLOOD_TABLE_REVIEW.md flagged that T26 had no bridge/road split, so
switching recovery.use_table_recovery_design on silently gave bridges the
road schedule. T26_recovery_schedule_US_candidate_bridges.csv (NCHRP WOD
390-anchored, genuinely longer than roads) closes that gap.
"""

from __future__ import annotations

from resiflow.tables import recovery_schedule_from_bridge_and_road_tables

BRIDGE_TABLE = "T26_recovery_schedule_US_candidate_bridges"
ROAD_TABLE = "T26_recovery_design_current"


def test_bridge_and_road_schedules_differ_for_average_scenario():
    bridge_dict, road_dict, days = recovery_schedule_from_bridge_and_road_tables(
        BRIDGE_TABLE, ROAD_TABLE, "average"
    )
    # Real re-anchored values: bridge extensive/average full recovery = 147d,
    # road extensive/average full recovery = 90d -- genuinely different.
    assert 147 in days
    assert 90 in days
    # day 110 is a real union checkpoint (road severe/average's own d100) --
    # at that point the road is long fully recovered, the bridge is not.
    bridge_rate_at_110 = bridge_dict["extensive"][days.index(110)]
    road_rate_at_110 = road_dict["extensive"][days.index(110)]
    assert bridge_rate_at_110 == 0.5  # still mid-recovery (98 <= 110 < 147)
    assert road_rate_at_110 == 1.0  # already fully recovered (110 >= 90)


def test_union_of_both_tables_checkpoints_present():
    _, _, days = recovery_schedule_from_bridge_and_road_tables(
        BRIDGE_TABLE, ROAD_TABLE, "average"
    )
    # Bridge average checkpoints: 0, 98, 147. Road average checkpoints: 0, 60, 90.
    for expected_day in (0, 60, 90, 98, 147):
        assert expected_day in days


def test_minor_moderate_no_capacity_loss_in_both():
    bridge_dict, road_dict, days = recovery_schedule_from_bridge_and_road_tables(
        BRIDGE_TABLE, ROAD_TABLE, "fast"
    )
    assert all(r == 1.0 for r in bridge_dict["minor"])
    assert all(r == 1.0 for r in road_dict["minor"])


def test_fast_scenario_bridge_matches_road_unchanged():
    bridge_dict, road_dict, days = recovery_schedule_from_bridge_and_road_tables(
        BRIDGE_TABLE, ROAD_TABLE, "fast"
    )
    # Bridge severe/fast: 50%@45d, 100%@60d. Road severe/fast: 50%@45d, 100%@60d
    # (identical here -- the fast scenario was explicitly left unchanged for
    # both re-anchorings, per T26_recovery_schedule_US_candidate_bridges.csv's
    # own "basis" column).
    idx = days.index(45)
    assert bridge_dict["severe"][idx] == 0.5
    assert road_dict["severe"][idx] == 0.5
