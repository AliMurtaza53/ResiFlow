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

    flooded_freight = _flow_on_edge(freight_post, spec.flooded_edge_id)
    flooded_passenger = _flow_on_edge(passenger_post, spec.flooded_edge_id)
    assert flooded_freight == pytest.approx(-spec.expected_disrupted_flow_freight)
    assert flooded_passenger == pytest.approx(-spec.expected_disrupted_flow_passenger)


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
