"""End-to-end pipeline smoke tests on toy routing networks."""

from __future__ import annotations

import subprocess

import pandas as pd
import pytest

from toy_pipeline_fixtures import (
    base_scenario_dir,
    build_toy_dataset,
    damage_dir,
    disruption_dir,
    pipeline_env,
    reroute_dir,
    run_pipeline_scripts,
)


def _edge_flows(edge_flows_path) -> pd.DataFrame:
    flows = pd.read_parquet(edge_flows_path)
    assert not flows.empty, "edge flows output is empty"
    assert "e_id" in flows.columns, "edge flows missing e_id"
    flow_col = "acc_flow" if "acc_flow" in flows.columns else "flow"
    flows = flows.copy()
    flows["e_id"] = flows["e_id"].astype(str)
    flows[flow_col] = pd.to_numeric(flows[flow_col], errors="coerce").fillna(0.0)
    return flows[["e_id", flow_col]].rename(columns={flow_col: "flow"})


def _flow_on_edge(flows: pd.DataFrame, edge_id: str) -> float:
    row = flows.loc[flows["e_id"] == edge_id, "flow"]
    assert not row.empty, f"edge {edge_id} missing from flows={flows.to_dict('records')}"
    return float(row.iloc[0])


def _assert_pipeline_outputs(tmp_path, env, spec) -> None:
    base_dir = base_scenario_dir(tmp_path, env)
    disrupt_dir = disruption_dir(tmp_path, env)
    dmg_dir = damage_dir(tmp_path, env)
    reroute_out = reroute_dir(tmp_path, env)

    odpfc_path = base_dir / "odpfc.pq"
    edge_flows_path = base_dir / "edge_flows.gpq"
    road_links_path = disrupt_dir / "links" / "road_links_1.gpq"
    intersections_path = disrupt_dir / "intersections" / "intersections_1.pq"
    damage_csv = dmg_dir / "intersections_1_with_damage_values.csv"
    cost_matrix = reroute_out / "cost_matrix_by_scenario.csv"
    passenger_cost_matrix = reroute_out / "cost_matrix_passenger_by_scenario.csv"

    assert odpfc_path.exists() or (base_dir / "odpfc_parts").is_dir(), (
        f"missing baseline odpfc output under {base_dir}"
    )
    assert edge_flows_path.exists(), f"missing baseline edge flows: {edge_flows_path}"
    assert road_links_path.exists(), f"missing disrupted road links: {road_links_path}"
    assert intersections_path.exists(), f"missing intersections: {intersections_path}"
    assert damage_csv.exists(), f"missing damage csv: {damage_csv}"
    assert cost_matrix.exists(), f"missing freight cost matrix: {cost_matrix}"
    assert passenger_cost_matrix.exists(), (
        f"missing passenger cost matrix: {passenger_cost_matrix}"
    )

    baseline_edges = _edge_flows(edge_flows_path)
    for edge_id, expected_flow in spec.baseline_edge_flows.items():
        actual = _flow_on_edge(baseline_edges, edge_id)
        assert actual == pytest.approx(expected_flow), (
            f"baseline flow on {edge_id}: expected {expected_flow}, got {actual}; "
            f"flows={baseline_edges.to_dict('records')}"
        )
    for edge_id in spec.baseline_path_edges:
        assert _flow_on_edge(baseline_edges, edge_id) > 0.0, (
            f"baseline path edge {edge_id} has no flow"
        )

    road_links = pd.read_parquet(road_links_path)
    flooded = road_links.loc[road_links["e_id"] == spec.flooded_edge_id]
    assert not flooded.empty, f"flooded edge {spec.flooded_edge_id} missing from road links"
    assert float(flooded["flood_depth_max"].fillna(0).max()) > 0.0

    max_speed = float(flooded["max_speed"].fillna(999).min())
    assert max_speed == 0.0, f"expected flooded edge closed, max_speed={max_speed}"

    non_flooded = road_links.loc[road_links["e_id"] != spec.flooded_edge_id]
    assert float(non_flooded["flood_depth_max"].fillna(0).max()) == 0.0, (
        "only the designated edge should be flooded; "
        f"links={road_links[['e_id', 'flood_depth_max', 'max_speed']].to_dict('records')}"
    )

    costs = pd.read_csv(cost_matrix)
    assert len(costs) == 1
    freight_row = costs.iloc[0]
    assert float(freight_row["total_disrupted_flow"]) == pytest.approx(
        spec.expected_disrupted_flow_freight
    )
    assert float(freight_row["rerouting_cost"]) == pytest.approx(
        spec.expected_rerouting_cost_freight
    )

    passenger_costs = pd.read_csv(passenger_cost_matrix)
    assert len(passenger_costs) == 1
    passenger_row = passenger_costs.iloc[0]
    assert float(passenger_row["total_disrupted_flow"]) == pytest.approx(
        spec.expected_disrupted_flow_passenger
    )
    assert float(passenger_row["rerouting_cost"]) == pytest.approx(
        spec.expected_rerouting_cost_passenger
    )

    freight_post = _edge_flows(reroute_out / "edge_flows_freight_s1_day1.gpq")
    passenger_post = _edge_flows(reroute_out / "edge_flows_passenger_s1_day1.gpq")

    assert _flow_on_edge(freight_post, spec.reroute_gain_edge) == pytest.approx(
        spec.expected_reroute_flow_freight
    ), (
        f"freight should reroute onto {spec.reroute_gain_edge}; "
        f"flows={freight_post.to_dict('records')}"
    )
    assert _flow_on_edge(passenger_post, spec.reroute_gain_edge) == pytest.approx(
        spec.expected_reroute_flow_passenger
    ), (
        f"passenger should reroute onto {spec.reroute_gain_edge}; "
        f"flows={passenger_post.to_dict('records')}"
    )

    # acc_flow fix (2026-08-29): a fully-closed edge carries zero physical
    # flow, not a negative number representing "flow removed." Before the
    # fix, road_links["acc_flow"] was seeded as current_flow - disrupted_flow
    # and never revisited for edges excluded from the disrupted-network solve
    # (closed edges have acc_capacity=0, so they're filtered out of
    # valid_road_links entirely) -- leaving the flooded edge stuck at
    # -disrupted_flow in the written output. See the acc_flow seeding
    # comment in scripts/4_rerouting_and_recovery_scenario_loop.py.
    flooded_freight = _flow_on_edge(freight_post, spec.flooded_edge_id)
    flooded_passenger = _flow_on_edge(passenger_post, spec.flooded_edge_id)
    assert flooded_freight == pytest.approx(0.0)
    assert flooded_passenger == pytest.approx(0.0)

    if spec.shared_reroute_edge is not None:
        # A shared downstream segment (on both the old and new route) is the
        # case that most needed this fix: before it, the erroneous negative
        # seed exactly cancelled the solver's real assigned flow, silently
        # reporting 0.0 flow on this edge instead of its true rerouted total.
        shared_freight = _flow_on_edge(freight_post, spec.shared_reroute_edge)
        shared_passenger = _flow_on_edge(passenger_post, spec.shared_reroute_edge)
        assert shared_freight == pytest.approx(spec.expected_reroute_flow_freight), (
            f"shared edge {spec.shared_reroute_edge} should carry the same rerouted "
            f"flow as {spec.reroute_gain_edge}; flows={freight_post.to_dict('records')}"
        )
        assert shared_passenger == pytest.approx(spec.expected_reroute_flow_passenger), (
            f"shared edge {spec.shared_reroute_edge} should carry the same rerouted "
            f"flow as {spec.reroute_gain_edge}; flows={passenger_post.to_dict('records')}"
        )

    # Shared-capacity invariant (2026-08-29 fix): freight and passenger now
    # compete for one physical capacity pool per edge, so their post-reroute
    # flows on the detour edge must sum to no more than that edge's actual
    # capacity -- never each independently maxing it out (the bug this test
    # would have caught: previously freight alone AND passenger alone could
    # each reach the edge's full capacity, silently double-booking it).
    detour_capacity = pd.read_parquet(
        reroute_out / "edge_flows_freight_s1_day1.gpq"
    ).set_index("e_id").loc[spec.reroute_gain_edge, "acc_capacity"]
    combined_detour_flow = _flow_on_edge(
        freight_post, spec.reroute_gain_edge
    ) + _flow_on_edge(passenger_post, spec.reroute_gain_edge)
    assert combined_detour_flow <= float(detour_capacity) + 1e-6, (
        f"freight+passenger combined flow on {spec.reroute_gain_edge} "
        f"({combined_detour_flow}) exceeds its real capacity ({detour_capacity}) "
        "-- shared capacity is being double-counted again"
    )

    # Demand-conservation invariant: the freight/passenger split of
    # total_disrupted_flow must add back up to each mode's own known input
    # demand -- the split is by exact per-OD composition, not an estimate.
    freight_costs = pd.read_csv(cost_matrix)
    passenger_costs = pd.read_csv(passenger_cost_matrix)
    assert float(freight_costs["total_disrupted_flow"].iloc[0]) + float(
        passenger_costs["total_disrupted_flow"].iloc[0]
    ) == pytest.approx(spec.freight_flow + spec.passenger_flow)


@pytest.mark.parametrize("network_name", ["three_parallel", "braess"])
def test_pipeline_scripts_reroute_toy_network(tmp_path, network_name):
    config_path, spec, _road_links = build_toy_dataset(tmp_path, network_name)
    env = pipeline_env(tmp_path, config_path, network_name=network_name)

    try:
        run_pipeline_scripts(env)
    except subprocess.CalledProcessError as exc:
        raise AssertionError(
            f"pipeline failed for {network_name}\n"
            f"stdout:\n{exc.stdout}\n"
            f"stderr:\n{exc.stderr}"
        ) from exc

    _assert_pipeline_outputs(tmp_path, env, spec)
