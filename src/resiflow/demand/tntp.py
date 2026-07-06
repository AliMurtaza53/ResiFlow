"""TNTP trips demand adapter."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from resiflow.demand.base import DEFAULT_FLOW_COL, DemandLoadResult, DemandSpec
from resiflow.demand.combine import normalize_assignment_od
from resiflow.networks.tntp import read_tntp_trips


def load_tntp_trips(
    trips_path: str | Path,
    *,
    demand_scale: float = 1.0,
    node_id_formatter=None,
) -> pd.DataFrame:
    od = read_tntp_trips(trips_path, node_id_formatter=node_id_formatter)
    if demand_scale != 1.0:
        od = od.copy()
        od[DEFAULT_FLOW_COL] = od[DEFAULT_FLOW_COL] * float(demand_scale)
    return normalize_assignment_od(od, DEFAULT_FLOW_COL, source="tntp")


def split_freight_passenger(
    passenger_od: pd.DataFrame,
    *,
    freight_share: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    share = float(freight_share)
    freight = passenger_od.copy()
    freight[DEFAULT_FLOW_COL] = freight[DEFAULT_FLOW_COL] * share
    passenger = passenger_od.copy()
    passenger[DEFAULT_FLOW_COL] = passenger[DEFAULT_FLOW_COL] * (1.0 - share)
    return (
        normalize_assignment_od(freight, DEFAULT_FLOW_COL, source="freight"),
        normalize_assignment_od(passenger, DEFAULT_FLOW_COL, source="passenger"),
    )
