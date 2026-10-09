"""Gated winter classification, faf5_class join, T33 ranks (topology), T34 day_open, peak flag."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from resiflow.fragility.winter_storm_categorical import (
    compute_damage_levels_vectorized as classify,
    t_factor_from_air_temp_f,
)
from resiflow.fragility.winter_storm_speed import apply_max_speed_to_links, speed_ratio
from resiflow.hazards.winter_storm_clearance import (
    add_clearance_columns,
    assign_clearance_rank,
    day_open_for,
    load_class_rank_map,
    peak_closure_flag,
)
from resiflow.preprocess.faf5_network import attach_faf5_class

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_NETWORK = Path("C:/Users/akothaw/Desktop/data/soge_clusters/networks/faf5/faf5_road_links.gpq")
_ORDER = {"no": 0, "minor": 1, "moderate": 2, "extensive": 3, "severe": 4}


def _levels(depth, duration=None, temp=None):
    depth = pd.Series(depth, dtype=float)
    rc = pd.Series(["primary"] * len(depth))
    return list(
        classify(
            rc,
            depth,
            None,
            duration_hours=pd.Series(duration, dtype=float) if duration is not None else None,
            air_temp_f=pd.Series(temp, dtype=float) if temp is not None else None,
        )
    )


# --------------------------------------------------------------------- classification
def test_depth_ladder_boundaries() -> None:
    assert _levels([0, 0.5, 101.9, 102, 304.9, 305, 456.9, 457, 2000]) == [
        "no", "minor", "minor", "moderate", "moderate", "extensive", "extensive", "severe", "severe",
    ]


def test_a_no_link_below_102mm_ever_ends_above_minor() -> None:
    """(a) The gate: whatever duration/temperature say, sub-102 mm depth stays minor."""
    depths = np.concatenate([np.linspace(0.01, 101.99, 200), [101.999999]])
    for duration in (0.0, 24.0, 48.0, 720.0, np.nan):
        for temp in (-40.0, 0.0, 10.0, 25.0, 60.0, np.nan):
            levels = _levels(depths, [duration] * len(depths), [temp] * len(depths))
            assert set(levels) == {"minor"}, (duration, temp, set(levels))


def test_escalators_apply_above_gate_independent_stacking_capped() -> None:
    cold, warm = 5.0, 40.0
    # moderate base: each escalator +1, both +2, capped at severe
    assert _levels([150, 150], [0, 24], [warm, warm]) == ["moderate", "extensive"]
    assert _levels([150, 150], [0, 0], [warm, cold]) == ["moderate", "extensive"]
    assert _levels([150], [24], [cold]) == ["severe"]
    # extensive base + both escalators is capped, never past severe
    assert _levels([400], [48], [cold]) == ["severe"]
    assert _levels([600], [48], [cold]) == ["severe"]


def test_escalation_thresholds_inclusive_at_24h_and_t_factor_1p5() -> None:
    # T_factor = 1 + 0.025 * (30 - T): exactly 1.5 at 10 F, just under at 10.5 F
    assert _levels([150], [23.99], [40.0]) == ["moderate"]
    assert _levels([150], [24.0], [40.0]) == ["extensive"]
    assert _levels([150], [0.0], [10.0]) == ["extensive"]
    assert _levels([150], [0.0], [10.5]) == ["moderate"]


def test_missing_duration_or_temperature_never_escalates() -> None:
    assert _levels([150], [np.nan], [np.nan]) == ["moderate"]
    assert _levels([150]) == ["moderate"]
    assert _levels([150], [np.nan], [5.0]) == ["extensive"]  # only the present input counts


def test_t_factor_matches_t32_cost_function() -> None:
    """The escalator's T_factor is the one T32's cost formula uses (cost fn is untouched)."""
    from resiflow.hazards.winter_storm_cost import _load_t32_coefficients, winter_storm_direct_cost_usd_per_lane_mile

    c = _load_t32_coefficients()
    for temp in (-20.0, 5.0, 10.0, 20.0, 30.0, 45.0):
        cost = winter_storm_direct_cost_usd_per_lane_mile(
            snow_depth_mm=150.0, duration_hours=None, air_temp_F=temp, road_classification="tertiary"
        )
        passes = 150.0 / c["d_plow_mm"]
        implied = cost / 0.85 / (c["kappa"] + c["c_pass"] * passes)  # minor-class multiplier 0.85
        assert implied == pytest.approx(float(t_factor_from_air_temp_f(pd.Series([temp]))[0]))


# ------------------------------------------------------------------------- speed curve
def test_speed_curve_from_t19_winter_table() -> None:
    assert speed_ratio([0.0])[0] == pytest.approx(1.0)
    assert speed_ratio([102.0])[0] == pytest.approx(0.65)  # table row
    assert speed_ratio([19.0])[0] == pytest.approx(0.885)  # midpoint of 13 mm (0.90) and 25 mm (0.87)
    assert speed_ratio([254.0])[0] == 0.0
    assert speed_ratio([5000.0])[0] == 0.0
    frame = apply_max_speed_to_links(
        pd.DataFrame({"d": [0.0, 300.0], "free_flow_speeds": [60.0, 60.0]}), depth_col="d"
    )
    assert list(frame["max_speed"]) == [60.0, 0.0]


# ------------------------------------------------------------------- faf5_class join
def test_b_attach_faf5_class_populates_all_but_null_class_and_keeps_road_classification() -> None:
    links = pd.DataFrame({"e_id": ["1", "2", "3", "4"], "road_classification": ["primary", "service", "service", "primary"]})
    raw = pd.DataFrame({"ID": [1, 2, 3, 4], "Class": [14.0, 16.0, np.nan, 23.0]})
    out = attach_faf5_class(links, raw)
    assert list(out["road_classification"]) == list(links["road_classification"])
    assert str(out["faf5_class"].dtype) == "Int64"
    assert out["faf5_class"].isna().sum() == 1
    assert out.loc[out["e_id"] == "4", "faf5_class"].iloc[0] == 23  # 23 stays distinguishable from 14


def test_attach_faf5_class_rejects_duplicate_raw_ids() -> None:
    with pytest.raises(ValueError):
        attach_faf5_class(pd.DataFrame({"e_id": ["1"]}), pd.DataFrame({"ID": [1, 1], "Class": [11, 12]}))


@pytest.mark.skipif(not REAL_NETWORK.exists(), reason="real FAF5 network parquet not available")
def test_b_real_network_faf5_class_populated_except_four_null_class_links() -> None:
    links = pd.read_parquet(REAL_NETWORK, columns=["e_id", "road_classification", "faf5_class"])
    assert "road_classification" in links.columns  # coexists, not replaced
    assert int(links["faf5_class"].isna().sum()) == 4
    assert int(links["faf5_class"].notna().sum()) == len(links) - 4


# --------------------------------------------------------------------- T33 rank / T34
def _net(rows):
    return pd.DataFrame(rows, columns=["faf5_class", "from_id", "to_id"])


def test_t33_class_rank_map_reads_first_block_only() -> None:
    m = load_class_rank_map()
    assert m[11] == 1 and m[12] == 1 and m[16] == 1 and m[14] == 2 and m[15] == 5
    assert m[22] == "TOPOLOGY" and m[23] == "TOPOLOGY"
    assert m[41] == "EXCLUDE" and m[50] == "EXCLUDE"
    assert max(k for k in m) == 50  # rank-table rows (1..5) were not misread as classes


def test_topology_inheritance_undirected_multihop_and_isolated_default() -> None:
    links = _net(
        [
            (11, 1, 2),   # 0 interstate                    rank 1
            (22, 2, 3),   # 1 ramp off the interstate       -> 1
            (22, 4, 3),   # 2 ramp chained via node 3 (reversed orientation) -> 1 (2 hops)
            (14, 5, 6),   # 3 arterial                       rank 2
            (22, 6, 7),   # 4 ramp off arterial only         -> 2
            (22, 2, 5),   # 5 ramp touching interstate (node 2) AND arterial (node 5) -> best = 1
            (22, 90, 91),  # 6 isolated ramp pair
            (22, 91, 92),  # 7
            (15, 8, 9),   # 8 local                          rank 5
            (17, 9, 10),  # 9 traffic circle off local only  -> 5
            (np.nan, 20, 21),  # 10 null Class               unclassified
        ]
    )
    r = assign_clearance_rank(links)
    assert list(r["clearance_rank"].astype("float")[:10]) == [1, 1, 1, 2, 2, 1, 2, 2, 5, 5]
    assert list(r["clearance_rank_source"][[6, 7]]) == ["isolated_default"] * 2
    assert r["clearance_rank_source"].iloc[1] == "topology" and r["clearance_rank_source"].iloc[0] == "direct"
    assert pd.isna(r["clearance_rank"].iloc[10]) and r["clearance_rank_source"].iloc[10] == "unclassified"


def test_c_excluded_classes_never_receive_rank_damage_level_or_day_open() -> None:
    """(c) class 41 (ferry) and 50 (centroid connector), even under deep, long, cold snow."""
    from resiflow.disruption.winter_storm import classify_merged_intersections

    road_links = pd.DataFrame(
        {"e_id": ["a", "b", "c"], "faf5_class": [11, 41, 50], "from_id": [1, 2, 3], "to_id": [2, 3, 4]}
    )
    inter = pd.DataFrame(
        {
            "e_id": ["a", "b", "c"],
            "road_classification": ["motorway", "service", "centroid_connector"],
            "winter_storm_mm": [600.0, 600.0, 600.0],
            "duration_hours": [48.0, 48.0, 48.0],
            "air_temp_F": [-20.0, -20.0, -20.0],
        }
    )
    seg = classify_merged_intersections(inter, road_links)
    assert list(seg["damage_level_winter_storm"]) == ["severe", "no", "no"]
    assert list(seg["damage_level_surface"]) == ["severe", "no", "no"]

    links = road_links.assign(damage_level_max=["severe", "severe", "severe"], winter_storm_max_mm=600.0)
    out = add_clearance_columns(links)
    for e_id in ("b", "c"):
        row = out.loc[out["e_id"] == e_id].iloc[0]
        assert pd.isna(row["clearance_rank"]) and row["clearance_rank_source"] == "excluded"
        assert row["damage_level_max"] == "no"
        assert pd.isna(row["day_open"]) and not row["winter_peak_closure_flag"]
    assert out.loc[out["e_id"] == "a", "clearance_rank"].iloc[0] == 1


@pytest.mark.skipif(not REAL_NETWORK.exists(), reason="real FAF5 network parquet not available")
def test_real_network_ranks_ferries_excluded_and_isolated_default() -> None:
    links = pd.read_parquet(REAL_NETWORK, columns=["e_id", "from_id", "to_id", "faf5_class"])
    r = assign_clearance_rank(links)
    src = r["clearance_rank_source"]
    assert int((src == "excluded").sum()) == int((links["faf5_class"] == 41).sum()) == 191
    assert r.loc[src == "excluded", "clearance_rank"].isna().all()
    assert int((src == "unclassified").sum()) == 4  # the null-Class links
    assert int((src == "isolated_default").sum()) == 169
    assert set(r["clearance_rank"].dropna().astype(int)) == {1, 2, 5}  # ranks 3/4 have no member classes


def test_t34_day_open_lookup() -> None:
    lvl = pd.Series(["no", "minor", "extensive", "severe", "moderate", "severe"])
    rank = pd.array([1, 2, 1, 5, pd.NA, 5], dtype="Int64")
    out = day_open_for(lvl, pd.Series(rank))
    assert out.iloc[0] == 0 and out.iloc[1] == 1 and out.iloc[2] == 2 and out.iloc[3] == 11
    assert pd.isna(out.iloc[4])  # damaged but unranked
    assert day_open_for(pd.Series(["severe"]), pd.Series([5]), region="low_capability").iloc[0] == 18


def test_peak_closure_flag_is_a_peak_flag_on_rank5_links_only() -> None:
    rank = pd.Series(pd.array([5, 5, 2, pd.NA], dtype="Int64"))
    depth = pd.Series([200.0, 199.9, 900.0, 900.0])
    assert list(peak_closure_flag(rank, depth)) == [True, False, False, False]


def test_link_builder_end_to_end_synthetic() -> None:
    from resiflow.disruption.build import build_winter_storm_link_disruption
    from resiflow.disruption.winter_storm import classify_merged_intersections

    road_links = pd.DataFrame(
        {
            "e_id": ["L1", "L2", "L3", "L4", "L5"],
            "faf5_class": [11, 22, 15, 41, 14],
            "from_id": [1, 2, 8, 30, 40],
            "to_id": [2, 3, 9, 31, 41],
            "road_classification": ["motorway", "motorway_link", "tertiary", "service", "primary"],
            "free_flow_speeds": [60.0] * 5,
        }
    )
    depth = [500.0, 150.0, 250.0, 300.0, 50.0]
    inter = pd.DataFrame(
        {
            "e_id": road_links["e_id"],
            "length": 1.0,
            "index_i": 0,
            "index_j": 0,
            "road_classification": road_links["road_classification"],
            "winter_storm_mm": depth,
            "duration_hours": [24.0, 24.0, 0.0, 48.0, 48.0],
            "air_temp_F": [5.0, 5.0, 40.0, -10.0, -10.0],
        }
    )
    inter = classify_merged_intersections(inter, road_links)
    out = build_winter_storm_link_disruption(
        road_links,
        inter,
        # assignment state (free_flow_speeds, ...) comes from the base scenario, as in the real pipeline
        pd.DataFrame({"e_id": road_links["e_id"], "free_flow_speeds": [60.0] * 5}),
        hazard_event=SimpleNamespace(event_id="1"),
        scenario_param=601,
    ).set_index("e_id")

    assert list(out["damage_level_max"]) == ["severe", "severe", "moderate", "no", "minor"]  # L5 gated: 50 mm
    assert out.loc["L1", "max_speed"] == 0.0  # 500 mm: past the T19-winter zero
    assert out.loc["L4", "max_speed"] == 60.0  # excluded ferry: unrestricted
    assert list(out["clearance_rank"].astype("float")[["L1", "L2", "L3", "L5"]]) == [1, 1, 5, 2]
    assert list(out["day_open"].astype("float")[["L1", "L2", "L3", "L5"]]) == [3, 3, 4, 1]
    assert pd.isna(out.loc["L4", "day_open"])
    assert list(out["winter_peak_closure_flag"]) == [False, False, True, False, False]


# ---------------------------------------------------------- (d) old quadratic is gone
def test_d_old_k100_k150_quadratic_is_no_longer_called_anywhere() -> None:
    for module in ("resiflow.fragility.snow_operational", "resiflow.fragility.winter_storm_operational"):
        assert importlib.util.find_spec(module) is None, f"{module} should have been removed"

    quadratic = re.compile(r"-\s*1\)\s*\*\*\s*2")
    offenders = []
    for path in (REPO_ROOT / "src" / "resiflow").rglob("*.py"):
        if path.name == "flood_operational.py":
            continue  # flood's Pregnolato quadratic is a different, kept mechanism
        text = path.read_text(encoding="utf-8")
        if quadratic.search(text) or "apply_snow_max_speed" in text or "apply_ws_max_speed" in text:
            offenders.append(path.name)
    assert not offenders, offenders
