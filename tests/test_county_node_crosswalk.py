"""Tests for scripts/diagnostics/county_node_crosswalk.py (node -> county -> state rollup check)."""
import importlib.util
from pathlib import Path

import pandas as pd

_SPEC = importlib.util.spec_from_file_location(
    "county_node_crosswalk", Path(__file__).resolve().parents[1] / "scripts" / "diagnostics" / "county_node_crosswalk.py"
)
cnc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cnc)


def _write_crosswalk(tmp_path, rows):
    p = tmp_path / "cw.csv"
    pd.DataFrame(rows, columns=["county_fips", "state_fips", "node_id"]).to_csv(p, index=False)
    return p


def _write_od(tmp_path, origins, dests, dtype=None):
    p = tmp_path / "od.parquet"
    pd.DataFrame({"origin_node": origins, "destination_node": dests, "Car21": 1.0}).astype(
        {"origin_node": dtype or "int64", "destination_node": dtype or "int64"}
    ).to_parquet(p)
    return p


def test_norm_node_handles_int_float_and_string_forms():
    s = pd.Series([100169, 100169.0, "100169", "100169.0"], dtype=object)
    assert set(cnc.norm_node(s)) == {"100169"}


def test_check_passes_when_every_node_maps_to_one_state(tmp_path):
    cw = _write_crosswalk(tmp_path, [("01001", "01", "10"), ("01003", "01", "11"), ("02013", "02", "12")])
    od = _write_od(tmp_path, [10, 11], [12, 10])
    assert cnc.check(od, cw) == 0


def test_check_fails_on_unmatched_node(tmp_path):
    cw = _write_crosswalk(tmp_path, [("01001", "01", "10")])
    od = _write_od(tmp_path, [10, 99], [10, 10])
    assert cnc.check(od, cw) == 1


def test_float_typed_od_nodes_still_match(tmp_path):
    cw = _write_crosswalk(tmp_path, [("01001", "01", "10"), ("01003", "01", "11")])
    od = _write_od(tmp_path, [10.0, 11.0], [11.0, 10.0], dtype="float64")
    assert cnc.check(od, cw) == 0


def test_shared_node_in_one_state_passes_state_level_but_is_reported(tmp_path, capsys):
    # Connecticut planning regions 09120 and 09190 share a node today
    cw = _write_crosswalk(tmp_path, [("09120", "09", "5"), ("09190", "09", "5"), ("01001", "01", "6")])
    od = _write_od(tmp_path, [5, 6], [6, 5])
    assert cnc.check(od, cw) == 0
    out = capsys.readouterr().out
    assert "STATE-LEVEL ROLLUP: PASS" in out and "AMBIGUOUS for 1 node" in out


def test_node_spanning_two_states_fails(tmp_path):
    cw = _write_crosswalk(tmp_path, [("01001", "01", "7"), ("02013", "02", "7")])
    od = _write_od(tmp_path, [7], [7])
    assert cnc.check(od, cw) == 1
