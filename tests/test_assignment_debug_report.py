"""Smoke test: the debug report writes every artifact and its OD table conserves demand."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "testbed" / "assignment_debug_report.py"


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    spec = importlib.util.spec_from_file_location("assignment_debug_report", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path_factory.mktemp("report")
    cap = mod.run_observed("anaheim", 20.0, out)  # 20x: multi-iteration with congestion isolation
    return mod, cap, out


def test_od_table_matches_audit(report):
    mod, cap, _ = report
    tab = mod.od_table(cap)
    last = cap["audits"].iloc[-1]
    assert tab["delivered"].sum() == pytest.approx(last["delivered_cum"], rel=1e-9)
    assert tab["demand"].sum() == pytest.approx(
        last["delivered_cum"] + last["isolated_structural_cum"] + last["isolated_congestion_cum"] + last["remain"], rel=1e-6
    )


def test_all_figures_written(report):
    mod, cap, out = report
    zones = mod.zone_set(cap["spec"])
    assert len(zones) == 38
    mod.plot_trajectory(cap["audits"], out / "trajectory.png")
    mod.plot_od_matrix(mod.od_table(cap), zones, out / "od_matrix.png")
    mod.plot_maps(cap, zones, out / "network_maps.png", out / "deletions_by_iter.png")
    for name in ("trajectory", "od_matrix", "network_maps", "deletions_by_iter"):
        assert (out / f"{name}.png").stat().st_size > 10_000
