import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "analyze_assignment_diagnostics",
    Path(__file__).resolve().parents[1] / "scripts" / "analyze_assignment_diagnostics.py",
)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

parse_timing_checkpoints = _MODULE.parse_timing_checkpoints
parse_capacity_blocked_edges = _MODULE.parse_capacity_blocked_edges
classify_run_stop_reason = _MODULE.classify_run_stop_reason
classify_unassigned_demand = _MODULE.classify_unassigned_demand
allocation_ratio_distribution = _MODULE.allocation_ratio_distribution


def test_parse_timing_checkpoints_computes_elapsed_between_consecutive_labels():
    log = (
        "2026-10-23 14:17:17,132 123 script.py RSS checkpoint [iter1_start]: 10.00 GB\n"
        "2026-10-23 14:17:20,132 123 script.py RSS checkpoint [iter1_args_built]: 10.50 GB\n"
        "2026-10-23 14:17:25,132 123 script.py RSS checkpoint [iter1_end]: 11.00 GB\n"
    )
    df = parse_timing_checkpoints(log)
    assert list(df["label"]) == ["iter1_start", "iter1_args_built", "iter1_end"]
    assert df["elapsed_since_prev_s"].iloc[1] == pytest.approx(3.0)
    assert df["elapsed_since_prev_s"].iloc[2] == pytest.approx(5.0)


def test_parse_timing_checkpoints_empty_when_no_checkpoints_present():
    df = parse_timing_checkpoints("no checkpoints in this log at all\n")
    assert df.empty


def test_parse_capacity_blocked_edges_aggregates_across_iterations():
    log = (
        "Capacity-blocked edge [iter 1]: e_id=e1 road=MAIN ST tier=arterial lanes=2 "
        "acc_capacity=50.00 current_capacity=1000.00\n"
        "Capacity-blocked edge [iter 2]: e_id=e1 road=MAIN ST tier=arterial lanes=2 "
        "acc_capacity=30.00 current_capacity=1000.00\n"
        "Capacity-blocked edge [iter 2]: e_id=e2 road=ELM ST tier=local_access lanes=1 "
        "acc_capacity=5.00 current_capacity=200.00\n"
    )
    df = parse_capacity_blocked_edges(log)
    e1 = df[df["e_id"] == "e1"].iloc[0]
    assert e1["times_blocked"] == 2
    assert e1["total_acc_capacity"] == pytest.approx(80.0)
    # sorted descending by total_acc_capacity -- e1 (80) ranks above e2 (5)
    assert df.iloc[0]["e_id"] == "e1"


def test_classify_run_stop_reason_detects_stagnation():
    log = "2026-10-23 ... Stop: Insufficient progress for 3 consecutive iterations ...\n"
    assert classify_run_stop_reason(log) == "stagnated"


def test_classify_run_stop_reason_unknown_when_no_marker_found():
    assert classify_run_stop_reason("nothing relevant here\n") == "unknown"


def test_classify_unassigned_demand_splits_reachable_from_unreachable():
    # network: 1-2-3 connected; 4-5 a separate disconnected component
    road_links = pd.DataFrame({"from_id": [1, 2, 4], "to_id": [2, 3, 5]})
    isolated_od = pd.DataFrame({
        "origin_node": [1, 4],
        "destination_node": [3, 1],  # 1->3 reachable (same component); 4->1 NOT (different components)
        "flow": [10.0, 5.0],
    })
    result = classify_unassigned_demand(isolated_od, road_links)
    mapping = dict(zip(zip(result["origin_node"], result["destination_node"]), result["classification"]))
    assert mapping[(1, 3)] == "reachable_but_unassigned"
    assert mapping[(4, 1)] == "structurally_unreachable"


def test_allocation_ratio_distribution_computes_full_percentiles_not_just_mean():
    original_od = pd.DataFrame({
        "origin_node": ["a", "b", "c"],
        "destination_node": ["x", "y", "z"],
        "Car21": [100.0, 100.0, 100.0],
    })
    isolated_od = pd.DataFrame({
        "origin_node": ["a", "b"],
        "destination_node": ["x", "y"],
        "flow": [100.0, 0.0],  # a->x: fully unassigned (ratio 0); b->y: fully assigned (ratio 1); c->z: no isolated row (ratio 1)
    })
    result = allocation_ratio_distribution(original_od, isolated_od)
    assert result["n_pairs"] == 3
    assert result["percentiles"]["p0"] == pytest.approx(0.0)
    assert result["percentiles"]["p100"] == pytest.approx(1.0)
    assert result["n_pairs_below_0.5_allocation"] == 1
