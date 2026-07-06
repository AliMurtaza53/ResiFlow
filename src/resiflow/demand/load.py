"""Load assignment demand for Scripts 1 and 4."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from resiflow.config import get_env
from resiflow.demand.base import DEFAULT_FLOW_COL, DemandLoadResult, DemandSpec
from resiflow.demand.combine import (
    load_combined_assignment_od,
    normalize_assignment_od,
    passenger_od_disabled,
    resolve_passenger_od_path,
)
from resiflow.demand.tntp import load_tntp_trips, split_freight_passenger


def first_existing(paths: list[Path | str]) -> Path | None:
    for path in paths:
        candidate = Path(path)
        if candidate.exists():
            return candidate
    return None


def resolve_freight_od_path(base_path: Path) -> Path:
    env_path = get_env("RESIFLOW_FAF5_OD_MATRIX_PATH", "NIRD_FAF5_OD_MATRIX_PATH")
    if env_path:
        path = Path(env_path)
        if path.exists():
            return path
    found = first_existing(
        [
            base_path / "census_datasets" / "faf5_od_matrix.pq",
            base_path / "inputs" / "census_datasets" / "faf5_od_matrix.pq",
            base_path / "inputs" / "test_17node" / "faf5_od_matrix_17x17_test.pq",
        ]
    )
    if found is None:
        raise FileNotFoundError("Could not find FAF5 OD matrix in standard or toy input paths")
    return found


def demand_spec_from_env(base_path: Path) -> DemandSpec:
    source = get_env("RESIFLOW_DEMAND_SOURCE", "NIRD_DEMAND_SOURCE", "faf5_parquet") or "faf5_parquet"
    passenger_path = None if passenger_od_disabled() else resolve_passenger_od_path(base_path)
    scale_raw = get_env("RESIFLOW_DEMAND_SCALE", "NIRD_DEMAND_SCALE", "1.0")
    return DemandSpec(
        source=source.strip().lower(),
        freight_path=resolve_freight_od_path(base_path),
        passenger_path=passenger_path,
        demand_scale=float(scale_raw or "1.0"),
    )


def load_assignment_demand(
    base_path: Path,
    spec: DemandSpec | None = None,
) -> DemandLoadResult:
    """Load freight/passenger/combined assignment OD for the transport model."""
    resolved = spec or demand_spec_from_env(base_path)

    if resolved.source == "tntp":
        trips_path = Path(resolved.extra["trips_path"])
        node_id_formatter = resolved.extra.get("node_id_formatter")
        passenger_od = load_tntp_trips(
            trips_path,
            demand_scale=resolved.demand_scale,
            node_id_formatter=node_id_formatter,
        )
        if resolved.freight_share is not None:
            freight_od, passenger_only = split_freight_passenger(
                passenger_od,
                freight_share=resolved.freight_share,
            )
            assignment, stats = load_combined_assignment_od(
                freight_od,
                passenger_path=None,
            )
            assignment = combine_scaled(freight_od, passenger_only)
            stats = demand_stats(freight_od, passenger_only, assignment)
            return DemandLoadResult(
                assignment_od=assignment,
                freight_od=freight_od,
                passenger_od=passenger_only,
                stats=stats,
            )
        stats = {
            "freight_flow": 0.0,
            "passenger_flow": float(passenger_od[DEFAULT_FLOW_COL].sum()),
            "combined_flow": float(passenger_od[DEFAULT_FLOW_COL].sum()),
        }
        return DemandLoadResult(
            assignment_od=passenger_od,
            passenger_od=passenger_od,
            stats=stats,
        )

    freight_path = resolved.freight_path or resolve_freight_od_path(base_path)
    freight_od = pd.read_parquet(freight_path)
    flow_col = resolved.flow_col
    if resolved.demand_scale != 1.0 and flow_col in freight_od.columns:
        freight_od = freight_od.copy()
        freight_od[flow_col] = pd.to_numeric(freight_od[flow_col], errors="coerce").fillna(0.0)
        freight_od[flow_col] *= resolved.demand_scale

    passenger_path = resolved.passenger_path
    if passenger_path is None and not passenger_od_disabled():
        passenger_path = resolve_passenger_od_path(base_path)

    assignment, stats = load_combined_assignment_od(
        freight_od,
        passenger_path=passenger_path,
        freight_flow_col=flow_col,
    )
    passenger_od = None
    if passenger_path is not None:
        passenger_od = normalize_assignment_od(
            pd.read_parquet(passenger_path), DEFAULT_FLOW_COL, source="passenger"
        )
    freight_only = normalize_assignment_od(freight_od, flow_col, source="freight").rename(
        columns={flow_col: DEFAULT_FLOW_COL}
    )
    return DemandLoadResult(
        assignment_od=assignment,
        freight_od=freight_only,
        passenger_od=passenger_od,
        stats=stats,
    )


def combine_scaled(freight_od: pd.DataFrame, passenger_od: pd.DataFrame) -> pd.DataFrame:
    from resiflow.demand.combine import combine_freight_passenger_od

    return combine_freight_passenger_od(freight_od, passenger_od)[
        ["origin_node", "destination_node", DEFAULT_FLOW_COL]
    ]


def demand_stats(
    freight_od: pd.DataFrame,
    passenger_od: pd.DataFrame,
    assignment_od: pd.DataFrame,
) -> dict[str, float]:
    return {
        "freight_flow": float(freight_od[DEFAULT_FLOW_COL].sum()),
        "passenger_flow": float(passenger_od[DEFAULT_FLOW_COL].sum()),
        "combined_flow": float(assignment_od[DEFAULT_FLOW_COL].sum()),
    }


def align_od_node_dtype(od: pd.DataFrame, road_links) -> pd.DataFrame:
    """Cast OD node IDs to match link endpoint dtype."""
    out = od.copy()
    node_dtype = road_links["from_id"].dtype
    if pd.api.types.is_integer_dtype(node_dtype):
        out["origin_node"] = pd.to_numeric(out["origin_node"], errors="raise").astype(node_dtype)
        out["destination_node"] = pd.to_numeric(out["destination_node"], errors="raise").astype(
            node_dtype
        )
    else:
        out["origin_node"] = out["origin_node"].astype(node_dtype)
        out["destination_node"] = out["destination_node"].astype(node_dtype)
    return out
