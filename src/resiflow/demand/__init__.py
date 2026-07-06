"""Assignment demand adapters (TNTP, FAF5 parquet, ...)."""

from resiflow.demand.base import (
    DEFAULT_FLOW_COL,
    REQUIRED_OD_COLUMNS,
    DemandLoadResult,
    DemandSpec,
)
from resiflow.demand.combine import (
    combine_freight_passenger_od,
    load_combined_assignment_od,
    normalize_assignment_od,
    passenger_od_disabled,
    resolve_passenger_od_path,
)
from resiflow.demand.load import (
    align_od_node_dtype,
    demand_spec_from_env,
    load_assignment_demand,
    resolve_freight_od_path,
)
from resiflow.demand.tntp import load_tntp_trips, split_freight_passenger

__all__ = [
    "DEFAULT_FLOW_COL",
    "REQUIRED_OD_COLUMNS",
    "DemandLoadResult",
    "DemandSpec",
    "align_od_node_dtype",
    "combine_freight_passenger_od",
    "demand_spec_from_env",
    "load_assignment_demand",
    "load_combined_assignment_od",
    "load_tntp_trips",
    "normalize_assignment_od",
    "passenger_od_disabled",
    "resolve_freight_od_path",
    "resolve_passenger_od_path",
    "split_freight_passenger",
]
