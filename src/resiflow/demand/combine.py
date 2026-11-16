"""Freight + passenger OD merge helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from resiflow.demand.base import DEFAULT_FLOW_COL, REQUIRED_OD_COLUMNS


def passenger_od_disabled() -> bool:
    """Return True when pipeline scripts should skip passenger OD merge."""
    import os

    return os.getenv("NIRD_DISABLE_PASSENGER_OD", "").strip().lower() in {
        "1",
        "true",
        "yes",
    } or os.getenv("RESIFLOW_DISABLE_PASSENGER_OD", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def normalize_assignment_od(
    od: pd.DataFrame,
    flow_col: str = DEFAULT_FLOW_COL,
    *,
    source: str = "od",
) -> pd.DataFrame:
    missing = set(REQUIRED_OD_COLUMNS) - set(od.columns)
    if missing:
        raise ValueError(f"{source} OD missing columns: {sorted(missing)}")
    if flow_col not in od.columns:
        raise ValueError(f"{source} OD missing flow column '{flow_col}'")

    out = od.copy()
    out["origin_node"] = out["origin_node"].astype(str)
    out["destination_node"] = out["destination_node"].astype(str)
    out[flow_col] = pd.to_numeric(out[flow_col], errors="coerce").fillna(0.0)
    grouped = out.groupby(["origin_node", "destination_node"], as_index=False)[flow_col].sum()
    return grouped[grouped[flow_col] > 0].reset_index(drop=True)


def combine_freight_passenger_od(
    freight_od: pd.DataFrame,
    passenger_od: pd.DataFrame,
    *,
    freight_flow_col: str = DEFAULT_FLOW_COL,
    passenger_flow_col: str = DEFAULT_FLOW_COL,
    truck_pce: float = 1.0,
) -> pd.DataFrame:
    """Merge freight and passenger OD into one assignment matrix.

    Car21 is the capacity load in passenger-car equivalents: passenger + truck_pce * freight.
    ``freight_flow`` and ``passenger_flow`` stay in vehicles. truck_pce=1.0 (default here)
    reproduces the old plain sum; real combined runs pass the ``assignment.truck_pce`` parameter.
    """
    freight = normalize_assignment_od(freight_od, freight_flow_col, source="freight").rename(
        columns={freight_flow_col: "freight_flow"}
    )
    passenger = normalize_assignment_od(
        passenger_od, passenger_flow_col, source="passenger"
    ).rename(columns={passenger_flow_col: "passenger_flow"})

    combined = freight.merge(
        passenger,
        on=["origin_node", "destination_node"],
        how="outer",
    ).fillna({"freight_flow": 0.0, "passenger_flow": 0.0})
    combined[DEFAULT_FLOW_COL] = (
        float(truck_pce) * combined["freight_flow"] + combined["passenger_flow"]
    )
    combined = combined[combined[DEFAULT_FLOW_COL] > 0].reset_index(drop=True)
    return combined[
        ["origin_node", "destination_node", "freight_flow", "passenger_flow", DEFAULT_FLOW_COL]
    ]


def resolve_passenger_od_path(
    base_path: Path | None = None,
    *,
    year: int = 2022,
    job_type: str = "JT00",
) -> Path | None:
    """Locate passenger assignment OD from env or standard processed paths."""
    import os

    from resiflow.config import get_env

    if passenger_od_disabled():
        return None

    for key in ("RESIFLOW_PASSENGER_OD_PATH", "NIRD_PASSENGER_OD_PATH"):
        env_path = get_env(key, None)
        if env_path:
            path = Path(env_path)
            if path.exists():
                return path

    candidates: list[Path] = []
    if base_path is not None:
        candidates.append(
            base_path.parent
            / "lodes_data"
            / "processed"
            / f"lodes_passenger_assignment_od_{job_type.lower()}_{year}.parquet"
        )
    for path in candidates:
        if path.exists():
            return path
    return None


def load_combined_assignment_od(
    freight_od: pd.DataFrame,
    *,
    passenger_path: str | Path | None = None,
    freight_flow_col: str = DEFAULT_FLOW_COL,
    truck_pce: float | None = None,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Return assignment OD for Script 1; optionally merge passenger demand.

    When passenger demand is merged, trucks count ``truck_pce`` (default: the
    ``assignment.truck_pce`` parameter, 2.0) car equivalents toward the assignment load.
    """
    if passenger_path is None:
        assignment = normalize_assignment_od(freight_od, freight_flow_col, source="freight").rename(
            columns={freight_flow_col: DEFAULT_FLOW_COL}
        )
        stats = {
            "freight_flow": float(assignment[DEFAULT_FLOW_COL].sum()),
            "passenger_flow": 0.0,
            "combined_flow": float(assignment[DEFAULT_FLOW_COL].sum()),
        }
        return assignment[["origin_node", "destination_node", DEFAULT_FLOW_COL]], stats

    if truck_pce is None:
        from resiflow.demand.vehicle_class import truck_pce as _truck_pce

        truck_pce = _truck_pce()
    passenger_od = pd.read_parquet(passenger_path)
    combined = combine_freight_passenger_od(
        freight_od,
        passenger_od,
        freight_flow_col=freight_flow_col,
        truck_pce=truck_pce,
    )
    stats = {
        "freight_flow": float(combined["freight_flow"].sum()),
        "passenger_flow": float(combined["passenger_flow"].sum()),
        "combined_flow": float(combined[DEFAULT_FLOW_COL].sum()),
        "truck_pce": float(truck_pce),
    }
    return combined[["origin_node", "destination_node", DEFAULT_FLOW_COL]], stats
