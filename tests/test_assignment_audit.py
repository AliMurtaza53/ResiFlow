"""Iteration audit logging, invariants, and the edge-prune knob in network_flow_model."""

from __future__ import annotations

import dataclasses
import logging
import re

import duckdb
import igraph
import pandas as pd
import pytest

from resiflow import road_revised as rr
from resiflow.assignment import compare
from resiflow.testbeds import load_testbed


def _kv(line: str) -> dict[str, str]:
    return dict(tok.split("=") for tok in line.split()[1:])


# --- RESIFLOW_EDGE_PRUNE_RATIO --------------------------------------------------


def test_prune_ratio_default_and_override(monkeypatch):
    monkeypatch.delenv("RESIFLOW_EDGE_PRUNE_RATIO", raising=False)
    assert rr._edge_prune_ratio() == 0.01
    monkeypatch.setenv("RESIFLOW_EDGE_PRUNE_RATIO", "0.1")
    assert rr._edge_prune_ratio() == 0.1


@pytest.mark.parametrize("bad", ["-0.1", "1.5"])
def test_prune_ratio_rejects_out_of_range(monkeypatch, bad):
    monkeypatch.setenv("RESIFLOW_EDGE_PRUNE_RATIO", bad)
    with pytest.raises(ValueError):
        rr._edge_prune_ratio()


def _prune_fixture():
    g = igraph.Graph(n=4, edges=[(0, 1), (1, 2), (2, 3)], directed=False)
    g.vs["name"] = ["a", "b", "c", "d"]
    g.es["e_id"] = ["e0", "e1", "e2"]
    links = pd.DataFrame(
        {
            "e_id": ["e0", "e1", "e2"],
            "e_idx": [0, 1, 2],
            "current_capacity": [1000.0, 1000.0, 1000.0],
            "acc_capacity": [5.0, 30.0, 500.0],  # residual ratios 0.005, 0.03, 0.5
        }
    )
    flow = pd.DataFrame({"e_id": ["e0", "e1", "e2"], "flow": [1.0, 1.0, 1.0]})
    return g, flow, links


@pytest.mark.parametrize(
    "env, surviving",
    [(None, 2), ("0.05", 1)],  # default prunes only the 0.005 edge; 0.05 also prunes 0.03
)
def test_update_network_structure_uses_prune_ratio(monkeypatch, env, surviving):
    if env is None:
        monkeypatch.delenv("RESIFLOW_EDGE_PRUNE_RATIO", raising=False)
    else:
        monkeypatch.setenv("RESIFLOW_EDGE_PRUNE_RATIO", env)
    g, flow, links = _prune_fixture()
    g, _ = rr.update_network_structure(3, g, flow, links)
    assert g.ecount() == surviving


# --- ITER_AUDIT + conservation invariant ----------------------------------------


def _audit_inputs():
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE remain_od (origin_node VARCHAR, destination_node VARCHAR, Car21 DOUBLE)")
    conn.execute("INSERT INTO remain_od VALUES ('a','b',20.0), ('z','b',10.0)")
    g = igraph.Graph(n=3, edges=[(0, 1)], directed=False)
    g.vs["name"] = ["a", "b", "z"]  # z has no edges
    return conn, g


def _audit(conn, g, **over):
    kw = dict(
        iteration=2, initial=100.0, delivered=15.0, delivered_cum=60.0,
        iso_struct=0.0, iso_cong=5.0, iso_struct_cum=0.0, iso_cong_cum=10.0,
        wall_s=1.5, edges_deleted=3,
    )
    kw.update(over)
    return rr._emit_iteration_audit(conn, g, **kw)


def test_iteration_audit_line_and_conservation_ok(caplog):
    conn, g = _audit_inputs()
    caplog.set_level(logging.INFO)
    out = _audit(conn, g)
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("ITER_AUDIT"))
    kv = _kv(line)
    assert list(kv) == [
        "iteration", "delivered", "delivered_cum", "delivered_frac_cum",
        "isolated_structural", "isolated_congestion",
        "isolated_structural_cum", "isolated_congestion_cum",
        "remain", "remain_frac", "edges_deleted", "origins_no_out_edges", "iter_wall_s",
    ]
    assert float(kv["remain"]) == 30.0 and kv["edges_deleted"] == "3"
    assert kv["origins_no_out_edges"] == "1"  # origin z has no outgoing edge
    assert out["ok"] and "INVARIANT conservation ok=True" in caplog.text


def test_audit_edges_deleted_na_on_stop_iteration(caplog):
    conn, g = _audit_inputs()
    caplog.set_level(logging.INFO)
    _audit(conn, g, edges_deleted=None)
    assert "edges_deleted=NA" in caplog.text


def test_conservation_violation_warns_then_raises(monkeypatch, caplog):
    conn, g = _audit_inputs()
    caplog.set_level(logging.INFO)
    out = _audit(conn, g, delivered_cum=50.0)  # 10 units unaccounted for
    assert not out["ok"]
    assert any(r.levelno == logging.WARNING and "conservation ok=False" in r.getMessage() for r in caplog.records)
    monkeypatch.setenv("RESIFLOW_INVARIANT_RAISE", "1")
    with pytest.raises(AssertionError):
        _audit(conn, g, delivered_cum=50.0)


def test_capacity_invariant(monkeypatch):
    ok = pd.DataFrame({"acc_capacity": [10.0, 0.0, -1e-9], "current_capacity": [100.0] * 3})
    assert rr._check_capacity_invariant(ok, 1)["ok"]
    bad = pd.DataFrame({"acc_capacity": [10.0, -5.0], "current_capacity": [100.0, 100.0]})
    res = rr._check_capacity_invariant(bad, 1)
    assert res["violating_edges"] == 1 and res["max_overshoot"] == 5.0
    monkeypatch.setenv("RESIFLOW_INVARIANT_RAISE", "1")
    with pytest.raises(AssertionError):
        rr._check_capacity_invariant(bad, 1)


# --- end to end on Anaheim ------------------------------------------------------


def _run_anaheim(monkeypatch, caplog, scale: float) -> tuple[list[dict[str, str]], float]:
    spec = dataclasses.replace(load_testbed("anaheim"), demand_scale=scale)
    monkeypatch.setattr(compare, "load_testbed", lambda *_a, **_k: spec)
    caplog.set_level(logging.INFO)
    _, _, meta = compare.run_resiflow_capconstrained_from_testbed("anaheim")
    audits = [_kv(r.getMessage()) for r in caplog.records if r.getMessage().startswith("ITER_AUDIT")]
    assert "conservation ok=False" not in caplog.text and "capacity ok=False" not in caplog.text
    return audits, meta["total_demand"]


def test_anaheim_multi_iteration_audit_conserves_demand(monkeypatch, caplog):
    audits, total = _run_anaheim(monkeypatch, caplog, 6.0)  # binds capacity: 3 iterations
    assert [a["iteration"] for a in audits] == ["1", "2", "3"]
    assert sum(float(a["delivered"]) for a in audits) == pytest.approx(total, rel=1e-9)
    assert audits[-1]["edges_deleted"] == "NA" and float(audits[-1]["remain"]) == 0.0


def test_anaheim_congestion_isolation_is_not_counted_as_delivered(monkeypatch, caplog):
    audits, total = _run_anaheim(monkeypatch, caplog, 40.0)
    last = audits[-1]
    delivered = float(last["delivered_cum"])
    iso = float(last["isolated_structural_cum"]) + float(last["isolated_congestion_cum"])
    assert delivered + iso == pytest.approx(total, rel=1e-9)
    assert float(last["isolated_congestion_cum"]) > 0 and delivered < total
    assert re.fullmatch(r"\d+", audits[0]["edges_deleted"])
