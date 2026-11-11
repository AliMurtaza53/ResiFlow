"""Opt-in per-iteration audit dump (docs/ASSIGNMENT_DUMP_SPEC.md, phase 1: summary and binding)."""

from __future__ import annotations

import dataclasses
import json
import logging

import numpy as np
import pandas as pd
import pytest

from resiflow import audit_dump as ad
from resiflow.assignment import compare
from resiflow.testbeds import load_testbed

STRATEGIES = ["legacy_compact_sql", "duckdb_chunked_compact", "streaming_arrays"]
_VOLATILE = {"iter_wall_s"}


def _run(monkeypatch, caplog, testbed, scale, strategy, dump_dir=None, level=None, **env):
    for k in ("RESIFLOW_AUDIT_DUMP_DIR", "RESIFLOW_AUDIT_DUMP_LEVEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NIRD_PATH_REALIZATION_STRATEGY", strategy)
    if dump_dir is not None:
        monkeypatch.setenv("RESIFLOW_AUDIT_DUMP_DIR", str(dump_dir))
    if level:
        monkeypatch.setenv("RESIFLOW_AUDIT_DUMP_LEVEL", level)
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    spec = dataclasses.replace(load_testbed(testbed), demand_scale=scale)
    monkeypatch.setattr(compare, "load_testbed", lambda *_a, **_k: spec)
    caplog.clear()
    caplog.set_level(logging.INFO)
    links, _flows, meta = compare.run_resiflow_capconstrained_from_testbed(testbed)
    audits = [
        dict(tok.split("=") for tok in r.getMessage().split()[1:])
        for r in caplog.records
        if r.getMessage().startswith("ITER_AUDIT")
    ]
    return links, audits, meta


def _stable(audits):
    return [{k: v for k, v in a.items() if k not in _VOLATILE} for a in audits]


# --- off by default, levels, manifest ----------------------------------------------------------


def test_off_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("RESIFLOW_AUDIT_DUMP_DIR", raising=False)
    assert ad.AuditDump.from_env() is None


def test_summary_level_writes_only_summary_and_manifest(monkeypatch, caplog, tmp_path):
    _run(monkeypatch, caplog, "anaheim", 6.0, "streaming_arrays", tmp_path, "summary")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["iteration_summary.parquet", "manifest.json"]


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_binding_level_files_and_schemas(monkeypatch, caplog, tmp_path, strategy):
    _, audits, _ = _run(monkeypatch, caplog, "anaheim", 20.0, strategy, tmp_path)  # default level
    names = {p.name for p in tmp_path.iterdir()}
    expected = {"manifest.json", "iteration_summary.parquet", "edge_iter", "ratio_iter"}
    if strategy == "streaming_arrays":
        expected.add("binding_od_iter")
    assert names == expected
    n_iter = len(audits)
    for sub in expected - {"manifest.json", "iteration_summary.parquet"}:
        assert len(list((tmp_path / sub).glob("iter=*.parquet"))) == n_iter
    edge = pd.read_parquet(tmp_path / "edge_iter" / "iter=0001.parquet")
    assert list(edge.columns) == [
        "iteration", "e_id", "flow", "total_candidate_flow", "edge_ratio", "acc_capacity_before",
        "acc_capacity_after", "current_capacity", "remaining_ratio", "is_binding", "is_deleted",
        "road_name", "state", "county", "tier", "lanes", "road_class", "is_connector",
    ]
    assert (edge["is_binding"] | edge["is_deleted"]).all()
    ratio = pd.read_parquet(tmp_path / "ratio_iter" / "iter=0001.parquet")
    assert list(ratio.columns) == ["iteration", "metric", "value", "resolution", "source"]
    summary = pd.read_parquet(tmp_path / "iteration_summary.parquet")
    assert len(summary) == n_iter
    for col in ("delivered", "remain", "edges_deleted", "prune_applied", "requested_flow", "dump_wall_s",
                "edges_loaded", "edges_binding", "edges_meeting_prune_rule", "legacy_assigned_fraction"):
        assert col in summary.columns
    if strategy == "streaming_arrays":
        bod = pd.read_parquet(tmp_path / "binding_od_iter" / "iter=0001.parquet")
        assert list(bod.columns) == ["iteration", "e_id", "n_od_bound", "flow_candidate", "flow_adjusted", "flow_lost"]


def test_unimplemented_level_falls_back_to_binding(monkeypatch, caplog, tmp_path):
    _run(monkeypatch, caplog, "anaheim", 6.0, "streaming_arrays", tmp_path, "zonepair")
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["level"] == "binding" and m["level_requested"] == "zonepair"
    assert "not implemented yet" in caplog.text


def test_invalid_level_disables_dump_and_run_still_completes(monkeypatch, caplog, tmp_path):
    _, audits, _ = _run(monkeypatch, caplog, "anaheim", 6.0, "streaming_arrays", tmp_path, "bogus")
    assert audits and not any(tmp_path.iterdir())
    assert caplog.text.count("AUDIT_DUMP warning") == 1


def test_manifest_contents(monkeypatch, caplog, tmp_path):
    _, audits, meta = _run(
        monkeypatch, caplog, "anaheim", 6.0, "duckdb_chunked_compact", tmp_path,
        RESIFLOW_EDGE_PRUNE_RATIO="0.02", RESIFLOW_GIT_COMMIT="abc1234",
    )
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["schema_version"] == ad.SCHEMA_VERSION and m["git_commit"] == "abc1234"
    assert m["strategy"] == "duckdb_chunked_compact" and m["level"] == "binding"
    assert m["initial_demand"] == pytest.approx(meta["total_demand"])
    assert m["env"]["RESIFLOW_EDGE_PRUNE_RATIO"] == "0.02"
    assert m["env"]["NIRD_PATH_REALIZATION_STRATEGY"] == "duckdb_chunked_compact"
    assert "unavailable" in m["strategy_capabilities"]["binding_od_iter"]  # stated, not faked
    assert m["finished"] is True and m["iterations_completed"] == len(audits)
    assert m["iterations_written"] == len(audits) and m["stop_reason"]
    assert m["edge_attribute_source_columns"]["tier"] == "assignment_tier"
    assert m["files"]["edge_iter"]["files"] == len(audits)


def test_repeat_use_of_one_dir_goes_to_call_subdir(monkeypatch, caplog, tmp_path):
    _run(monkeypatch, caplog, "anaheim", 6.0, "streaming_arrays", tmp_path)
    _run(monkeypatch, caplog, "anaheim", 6.0, "streaming_arrays", tmp_path)
    assert (tmp_path / "manifest.json").exists() and (tmp_path / "call_02" / "manifest.json").exists()


# --- dump on versus off: identical numerical results (Lessons 1 and 2) --------------------------


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("testbed, scale", [
    ("sioux_falls", 1.0), ("sioux_falls", 20.0), ("anaheim", 1.0), ("anaheim", 6.0),
    ("anaheim", 20.0), ("anaheim", 40.0),
])
def test_dump_on_equals_off(monkeypatch, caplog, tmp_path, testbed, scale, strategy):
    links_off, audits_off, _ = _run(monkeypatch, caplog, testbed, scale, strategy)
    links_on, audits_on, _ = _run(monkeypatch, caplog, testbed, scale, strategy, tmp_path)
    assert _stable(audits_on) == _stable(audits_off)  # delivered, isolated, remain, edges_deleted per iteration
    pd.testing.assert_frame_equal(
        pd.DataFrame(links_on).reset_index(drop=True), pd.DataFrame(links_off).reset_index(drop=True)
    )  # total edge flow (acc_flow) and every other column
    assert (tmp_path / "manifest.json").exists()


# --- the dump is internally consistent and agrees with the log and across strategies ----------


def _load(dump_dir):
    summary = pd.read_parquet(dump_dir / "iteration_summary.parquet")
    edges = {i: pd.read_parquet(dump_dir / "edge_iter" / f"iter={i:04d}.parquet") for i in summary["iteration"]}
    ratios = {i: pd.read_parquet(dump_dir / "ratio_iter" / f"iter={i:04d}.parquet").set_index("metric")["value"]
              for i in summary["iteration"]}
    return summary, edges, ratios


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_dump_is_consistent_with_log_and_conservation(monkeypatch, caplog, tmp_path, strategy):
    _, audits, meta = _run(monkeypatch, caplog, "anaheim", 40.0, strategy, tmp_path)
    summary, edges, ratios = _load(tmp_path)
    assert len(audits) == len(summary) > 5  # capacity binds over several iterations
    for a, (_, s) in zip(audits, summary.iterrows()):
        k = int(a["iteration"])
        assert s["delivered"] == pytest.approx(float(a["delivered"]), rel=1e-9, abs=1e-6)
        # edges_deleted in the log equals the edges flagged is_deleted in the dump
        assert int(edges[k]["is_deleted"].sum()) == int(s["edges_meeting_prune_rule"]) == int(a["edges_deleted"])
        # candidate flow >= adjusted flow; adjusted flow never exceeds the residual capacity before
        e = edges[k]
        assert (e["total_candidate_flow"] + 1e-6 >= e["flow"]).all()
        assert (e["flow"] <= e["acc_capacity_before"] * (1 + 1e-9) + 1e-6).all()
        assert ((e["edge_ratio"] >= 0) & (e["edge_ratio"] <= 1)).all()
        # ratio distribution: adjusted flow equals the iteration's delivered flow (OD-side cross-check)
        r = ratios[k]
        assert r["flow_adjusted"] == pytest.approx(s["delivered"], rel=1e-9, abs=1e-6)
        assert r["n_od"] > 0 and r["q0"] <= r["q0.5"] <= r["q1"] <= 1.0
    # per-iteration conservation reconstructed from the dump alone
    first = summary.iloc[0]
    total = first["delivered_cum"] + first["isolated_structural_cum"] + first["isolated_congestion_cum"] + first["remain"]
    assert total == pytest.approx(meta["total_demand"], rel=1e-9)


def test_binding_od_flow_lost_matches_ratio_distribution(monkeypatch, caplog, tmp_path):
    _run(monkeypatch, caplog, "anaheim", 40.0, "streaming_arrays", tmp_path)
    summary, _, ratios = _load(tmp_path)
    for k in summary["iteration"]:
        bod = pd.read_parquet(tmp_path / "binding_od_iter" / f"iter={k:04d}.parquet")
        r = ratios[k]
        assert bod["flow_lost"].sum() == pytest.approx(r["flow_candidate"] - r["flow_adjusted"], rel=1e-9, abs=1e-6)
        assert bod["n_od_bound"].sum() <= r["n_od"]


def test_strategies_agree_on_edge_and_ratio_files(monkeypatch, caplog, tmp_path):
    loaded = {}
    for st in STRATEGIES:
        d = tmp_path / st
        _run(monkeypatch, caplog, "anaheim", 20.0, st, d)
        loaded[st] = _load(d)
    base_summary, base_edges, base_ratios = loaded["streaming_arrays"]
    for st in STRATEGIES[:2]:
        summary, edges, ratios = loaded[st]
        assert len(summary) == len(base_summary)
        for k in base_edges:
            cols = ["e_id", "flow", "total_candidate_flow", "edge_ratio", "acc_capacity_before", "is_deleted"]
            a = base_edges[k].sort_values("e_id")[cols].reset_index(drop=True)
            b = edges[k].sort_values("e_id")[cols].reset_index(drop=True)
            pd.testing.assert_frame_equal(a, b, rtol=1e-9, atol=1e-6)
            # the SQL ratio histogram and the inline streaming one agree
            pd.testing.assert_series_equal(base_ratios[k], ratios[k], rtol=1e-9, atol=1e-9)


# --- failure policy, knobs that must keep working ----------------------------------------------


def test_failure_in_dump_warns_once_and_never_changes_the_run(monkeypatch, caplog, tmp_path):
    links_off, audits_off, _ = _run(monkeypatch, caplog, "anaheim", 20.0, "streaming_arrays")

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(ad, "_write_parquet", boom)
    links_on, audits_on, _ = _run(monkeypatch, caplog, "anaheim", 20.0, "streaming_arrays", tmp_path)
    assert caplog.text.count("AUDIT_DUMP warning") == 1  # warn once, then disabled
    assert _stable(audits_on) == _stable(audits_off)
    pd.testing.assert_frame_equal(pd.DataFrame(links_on).reset_index(drop=True), pd.DataFrame(links_off).reset_index(drop=True))
    assert ad.get_sink() is None  # no stale sink left behind


def test_unwritable_dump_dir_does_not_stop_the_run(monkeypatch, caplog, tmp_path):
    blocker = tmp_path / "file_not_dir"
    blocker.write_text("x")
    _, audits, _ = _run(monkeypatch, caplog, "anaheim", 6.0, "streaming_arrays", blocker / "sub")
    assert audits and "AUDIT_DUMP warning" in caplog.text


def test_capacity_blocked_edges_log_still_works_with_dump_on(monkeypatch, caplog, tmp_path):
    _run(monkeypatch, caplog, "anaheim", 20.0, "streaming_arrays", tmp_path, RESIFLOW_LOG_CAPACITY_BLOCKED_EDGES="1")
    assert "Capacity-blocked edge [iter 1]" in caplog.text and "Capacity-blocked edges [iter 1]" in caplog.text


# --- stop iteration prints a number, not NA (quirk fix) ------------------------------------


def test_stop_iteration_counts_prune_rule_edges_without_applying_them(monkeypatch, caplog, tmp_path):
    _, audits, _ = _run(monkeypatch, caplog, "anaheim", 40.0, "streaming_arrays", tmp_path, RESIFLOW_MAX_FLOW_ITERATIONS="3")
    assert len(audits) == 3
    last = audits[-1]
    assert last["prune_applied"] == "0" and last["edges_deleted"].isdigit()
    assert all(a["prune_applied"] == "1" for a in audits[:-1])
    summary, edges, _ = _load(tmp_path)
    assert int(edges[3]["is_deleted"].sum()) == int(last["edges_deleted"]) > 0
    assert json.loads((tmp_path / "manifest.json").read_text())["stop_reason"] == "max_iterations"


# --- ratio sink unit test ------------------------------------------------------------------------


def test_ratio_sink_quantiles_and_binding_attribution():
    sink = ad.RatioSink()
    sink.add(1.0, 100.0)            # unconstrained
    sink.add(0.5, 100.0, "eA")      # throttled by eA
    sink.add(0.25, 200.0, "eA")
    sink.add(0.05, 100.0, "eB")
    df = sink.ratio_records(1).set_index("metric")["value"]
    assert df["n_od"] == 4 and df["flow_candidate"] == 500 and df["flow_adjusted"] == pytest.approx(100 + 50 + 50 + 5)
    assert df["q0"] == 0.05 and df["q1"] == 1.0
    assert df["share_flow_r_lt_0.1"] == pytest.approx(100 / 500) and df["share_flow_r_lt_1"] == pytest.approx(400 / 500)
    assert 0.25 <= df["q0.5"] <= 0.26  # flow-weighted median lies in the 0.25 bin
    bod = sink.binding_od(1).set_index("e_id")
    assert bod.loc["eA", "n_od_bound"] == 2 and bod.loc["eA", "flow_lost"] == pytest.approx(300 - 100)
    assert bod.loc["eB", "flow_lost"] == pytest.approx(95)
