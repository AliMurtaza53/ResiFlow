"""Baseline (pre-event) demand for the rerouting cost: the flow the damaged network actually serves.

Rerouting cost is post minus pre over the same routed flow. Isolation is priced separately, so flow isolated on the damaged
network must be removed from the baseline demand. An OD pair can be PARTIALLY isolated (part of its flow routes, part does
not). Dropping the whole pair removes its routed flow from the baseline too, so that flow had a post cost and no pre cost and
the rerouting cost was overstated. Found 2026-11-13 in the Harvey runs: on day 7, 55,530 partially isolated OD pairs carrying
24,000 routed trips had no baseline path (the same 24,000 in both the Harvey-15 and the full-CONUS run).
"""

from __future__ import annotations

import pandas as pd

KEYS = ["origin_node", "destination_node"]


def baseline_demand_excluding_isolated_flow(
    disrupted_od: pd.DataFrame, isolation_od: pd.DataFrame, flow_col: str = "Car21", iso_flow_col: str = "flow"
) -> pd.DataFrame:
    """Disrupted demand minus the flow isolated per OD pair; pairs left with no flow are dropped."""
    if isolation_od is None or isolation_od.empty:
        return disrupted_od
    demand = disrupted_od.copy()
    demand[KEYS] = demand[KEYS].astype(str)
    iso = isolation_od[KEYS + [iso_flow_col]].copy()
    iso[KEYS] = iso[KEYS].astype(str)
    iso = iso.groupby(KEYS, as_index=False)[iso_flow_col].sum().rename(columns={iso_flow_col: "_isolated_flow"})
    out = demand.merge(iso, how="left", on=KEYS)
    out["_isolated_flow"] = out["_isolated_flow"].fillna(0.0)
    out[flow_col] = (out[flow_col] - out["_isolated_flow"]).clip(lower=0.0)
    out = out[out[flow_col] > 1e-9].drop(columns="_isolated_flow")
    return out.reset_index(drop=True)
