"""Compare BPR user equilibrium vs ResiFlow cap-constrained assignment on Sioux Falls."""

from __future__ import annotations

import pytest

from resiflow.assignment.compare import compare_ue_vs_resiflow
from resiflow.assignment.ue_bpr import solve_tntp_user_equilibrium
from resiflow.testbeds import load_testbed


@pytest.fixture
def sioux_spec():
    return load_testbed("sioux_falls")


def test_ue_converges_on_sioux_falls(sioux_spec):
    result = solve_tntp_user_equilibrium(
        sioux_spec.net_path(),
        sioux_spec.trips_path(),
        demand_scale=sioux_spec.demand_scale,
        target_gap=1e-3,
        max_iterations=1000,
    )
    assert result.converged
    assert result.iterations > 0
    assert result.link_flows["ue_flow"].sum() > 0


@pytest.mark.slow
def test_ue_vs_resiflow_flow_correlation(sioux_spec):
    """Cap-constrained piecewise speeds vs BPR UE on Sioux Falls."""
    report = compare_ue_vs_resiflow("sioux_falls", target_gap=1e-3)
    assert report["ue_converged"]
    assert report["paired_links"] > 50
    # Same total volume; routing patterns differ (BPR per-link vs tier piecewise, undirected graph).
    assert 0.95 <= report["total_flow_ratio"] <= 1.05
    assert report["flow_correlation_undirected"] > 0.2
    assert report["resiflow_total_flow"] > 0
