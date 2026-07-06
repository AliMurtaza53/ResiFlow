"""Compare BPR user equilibrium vs ResiFlow capacity-constrained assignment."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

import resiflow.road_revised as road_funcs
from resiflow.assignment.ue_bpr import links_from_tntp, solve_user_equilibrium
from resiflow.demand.load import align_od_node_dtype
from resiflow.demand.tntp import load_tntp_trips
from resiflow.networks import load_assignment_profiles, normalize_network_links
from resiflow.networks.tntp import links_to_geodataframe, read_tntp_links, read_tntp_nodes
from resiflow.testbeds import load_testbed

_REPO_PARAMETERS = Path(__file__).resolve().parents[3] / "parameters"


def _undirected_pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((str(a), str(b))))


def _aggregate_undirected_flows(
    flows: pd.DataFrame,
    *,
    from_col: str = "from_id",
    to_col: str = "to_id",
    flow_col: str,
) -> pd.Series:
    grouped = flows.groupby(
        flows.apply(lambda r: _undirected_pair(r[from_col], r[to_col]), axis=1)
    )[flow_col].sum()
    grouped.index = pd.MultiIndex.from_tuples(grouped.index, names=["node_a", "node_b"])
    return grouped


def run_resiflow_capconstrained_from_testbed(
    testbed_id: str = "sioux_falls",
    *,
    use_testbed_prefix: bool = False,
    params_root: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    spec = load_testbed(testbed_id)
    node_fmt = spec.node_id_formatter() if use_testbed_prefix else (lambda raw: str(raw))
    resolved_params = params_root or _REPO_PARAMETERS

    nodes = read_tntp_nodes(spec.node_path())
    links_df = read_tntp_links(spec.net_path())
    od = load_tntp_trips(
        spec.trips_path(),
        demand_scale=spec.demand_scale,
        node_id_formatter=node_fmt,
    )

    road_links = links_to_geodataframe(
        nodes,
        links_df,
        node_id_formatter=node_fmt,
        source_crs=spec.source_crs,
        output_crs=spec.output_crs,
    )
    profiles = load_assignment_profiles(resolved_params)
    road_links = normalize_network_links(
        road_links, source="tntp", params_root=str(resolved_params)
    )
    od = align_od_node_dtype(od, road_links)

    road_links = road_funcs.edge_init(
        road_links,
        profiles["flow_breakpoint"],
        profiles["flow_cap_plph"],
        profiles["free_flow_speed"],
        profiles["urban_speed_cap"],
        profiles["min_speed_cap"],
        max_flow_speed_dict=None,
    )
    network, road_links = road_funcs.create_igraph_network(road_links, vehicle_type="car")

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "baseline.duckdb")
        road_links, _ = road_funcs.network_flow_model(
            road_links,
            network,
            od,
            profiles["flow_breakpoint"],
            num_of_chunk=1,
            num_of_cpu=1,
            db_path=db_path,
            iso_out_path=None,
            odpfc_out_path=None,
        )

    flows = road_links[["e_id", "from_id", "to_id", "acc_flow", "acc_speed"]].copy()
    flows = flows.rename(columns={"acc_flow": "resiflow_flow", "acc_speed": "resiflow_speed"})
    return links_df, flows, {"total_demand": float(od["Car21"].sum())}


def compare_ue_vs_resiflow(
    testbed_id: str = "sioux_falls",
    *,
    use_testbed_prefix: bool = False,
    target_gap: float = 1e-3,
) -> dict[str, object]:
    """Run UE and ResiFlow cap-constrained assignment on the same TNTP testbed."""
    spec = load_testbed(testbed_id)
    node_fmt = spec.node_id_formatter() if use_testbed_prefix else (lambda raw: str(raw))

    links_df = read_tntp_links(spec.net_path())
    od = load_tntp_trips(
        spec.trips_path(),
        demand_scale=spec.demand_scale,
        node_id_formatter=node_fmt,
    )

    ue_links = links_from_tntp(links_df)
    ue_result = solve_user_equilibrium(
        ue_links,
        od,
        target_gap=target_gap,
        max_iterations=1000,
    )

    _, resiflow_flows, meta = run_resiflow_capconstrained_from_testbed(
        testbed_id,
        use_testbed_prefix=use_testbed_prefix,
    )

    # Map UE flows onto ResiFlow links by (from_id, to_id).
    ue_map = {
        (str(row.init_node), str(row.term_node)): float(row.ue_flow)
        for row in ue_result.link_flows.itertuples(index=False)
    }
    resiflow_flows["ue_flow"] = resiflow_flows.apply(
        lambda r: ue_map.get((str(r.from_id), str(r.to_id)), np.nan),
        axis=1,
    )
    paired = resiflow_flows.dropna(subset=["ue_flow"]).copy()
    paired_active = paired[(paired["ue_flow"] > 0.01) | (paired["resiflow_flow"] > 0.01)].copy()

    def _corr(frame: pd.DataFrame, x: str, y: str) -> float:
        if len(frame) < 2:
            return float("nan")
        return float(np.corrcoef(frame[x], frame[y])[0, 1])

    corr_directed = _corr(paired_active, "resiflow_flow", "ue_flow")
    ue_undirected = _aggregate_undirected_flows(
        ue_result.link_flows.rename(columns={"init_node": "from_id", "term_node": "to_id"}),
        flow_col="ue_flow",
    )
    rf_undirected = _aggregate_undirected_flows(paired, flow_col="resiflow_flow")
    undirected = pd.DataFrame({"ue_flow": ue_undirected, "resiflow_flow": rf_undirected}).fillna(0.0)
    undirected = undirected[(undirected["ue_flow"] > 0.01) | (undirected["resiflow_flow"] > 0.01)]
    corr_undirected = _corr(undirected.reset_index(drop=True), "resiflow_flow", "ue_flow")

    mae = (
        float(np.mean(np.abs(paired_active["resiflow_flow"] - paired_active["ue_flow"])))
        if len(paired_active)
        else float("nan")
    )
    mape = (
        float(
            np.mean(
                np.abs(paired_active["resiflow_flow"] - paired_active["ue_flow"])
                / paired_active["ue_flow"].clip(lower=1.0)
            )
        )
        if len(paired_active)
        else float("nan")
    )
    ue_total = float(ue_result.link_flows["ue_flow"].sum())
    rf_total = float(resiflow_flows["resiflow_flow"].sum())
    total_flow_ratio = rf_total / ue_total if ue_total > 0 else float("nan")

    return {
        "testbed_id": testbed_id,
        "demand_scale": spec.demand_scale,
        "total_demand": meta["total_demand"],
        "ue_iterations": ue_result.iterations,
        "ue_relative_gap": ue_result.relative_gap,
        "ue_converged": ue_result.converged,
        "link_count": len(resiflow_flows),
        "paired_links": len(paired_active),
        "flow_correlation": corr_directed,
        "flow_correlation_undirected": corr_undirected,
        "ue_total_flow": ue_total,
        "resiflow_total_flow": rf_total,
        "total_flow_ratio": total_flow_ratio,
        "flow_mae": mae,
        "flow_mape": mape,
        "paired_flows": paired_active[["from_id", "to_id", "resiflow_flow", "ue_flow"]],
        "undirected_flows": undirected.reset_index(),
        "ue_link_flows": ue_result.link_flows,
    }
