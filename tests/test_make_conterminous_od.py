"""Tests for scripts/make_conterminous_od.py (OD node re-snap to the current network, AK/HI drop)."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "make_conterminous_od", Path(__file__).resolve().parents[1] / "scripts" / "make_conterminous_od.py"
)
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)


def _links(rows):
    return pd.DataFrame(rows, columns=["from_id", "to_id", "STATE", "assignment_tier", "faf5_class"])


def test_components_main_and_fragment():
    links = _links([(1, 2, "TX", "arterial", 1), (2, 3, "TX", "arterial", 1), (10, 11, "NV", "arterial", 1)])
    comp, main = mod.components(links)
    assert comp[1] == comp[2] == comp[3] == main
    assert comp[10] == comp[11] != main


def test_eligible_nodes_excludes_fragment_freeway_and_ramp_nodes():
    links = _links([
        (1, 2, "TX", "arterial", 1),
        (2, 3, "TX", "freeway", 1),     # freeway tier -> nodes 2 and 3 not eligible
        (3, 4, "TX", "arterial", 22),   # ramp class -> node 4 not eligible
        (4, 5, "TX", "collector", 1),
        (20, 21, "NV", "arterial", 1),  # separate fragment
    ])
    comp, main = mod.components(links)
    el = set(mod.eligible_nodes(links, comp, main))
    assert el == {1, 5}


def test_snap_nodes_nearest_and_unique():
    cand = pd.DataFrame({"x": [0.0, 10.0, 1000.0], "y": [0.0, 0.0, 0.0]}, index=pd.Index([100, 101, 102], name="node_id"))
    src = pd.DataFrame({"x": [1.0, 2.0], "y": [0.0, 0.0]}, index=pd.Index([7, 8], name="old"))
    s = mod.snap_nodes(src, cand).set_index("old_node")
    assert s.loc[7, "new_node"] == 100            # nearest
    assert s.loc[8, "new_node"] == 101            # 100 already used -> next nearest, never reused
    assert s.new_node.is_unique


def test_transform_od_drops_remaps_conserves_and_keeps_dtype():
    df = pd.DataFrame({"origin_node": np.array([1, 2, 3, 9], dtype="int64"),
                       "destination_node": np.array([2, 3, 3, 1], dtype="int64"),
                       "Car21": [10.0, 20.0, 5.0, 7.0]})
    out, st = mod.transform_od(df, remap={1: 100, 2: 200}, drop_nodes={9})
    assert out.origin_node.dtype == df.origin_node.dtype
    assert out.origin_node.tolist() == [100, 200, 3] and out.destination_node.tolist() == [200, 3, 3]
    assert st["flow_dropped"] == pytest.approx(7.0)
    assert st["flow_in"] == pytest.approx(st["flow_out"] + st["flow_dropped"])
    assert st["intrazonal_rows_in"] == 1 and st["intrazonal_rows_out"] == 1


def test_transform_od_handles_string_node_columns():
    df = pd.DataFrame({"origin_node": ["1", "2"], "destination_node": ["2", "1"], "Car21": [1.0, 2.0]})
    out, _ = mod.transform_od(df, remap={1: 100}, drop_nodes=set())
    assert out.origin_node.tolist() == ["100", "2"] and out.destination_node.tolist() == ["2", "100"]


def test_flow_between_components_counts_only_cross_component_non_intrazonal():
    comp = pd.Series({1: 0, 2: 0, 10: 1})
    df = pd.DataFrame({"origin_node": [1, 1, 10, 10], "destination_node": [2, 10, 10, 1], "Car21": [3.0, 4.0, 100.0, 5.0]})
    assert mod.flow_between_components(df, comp) == pytest.approx(9.0)


def test_state_match_share_detects_scrambled_nodes():
    links = _links([(1, 2, "TX", "arterial", 1), (3, 4, "OR", "arterial", 1)])
    good = pd.DataFrame({"state_fips": ["48", "41"], "node_id": ["1", "3"]})     # TX -> node 1 (TX), OR -> node 3 (OR)
    scrambled = pd.DataFrame({"state_fips": ["48", "41"], "node_id": ["3", "1"]})
    assert mod.state_match_share(good, links) == 1.0
    assert mod.state_match_share(scrambled, links) == 0.0
