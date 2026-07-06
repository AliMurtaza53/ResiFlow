"""Combine freight and passenger assignment OD matrices for network flow models."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = ("origin_node", "destination_node")


def passenger_od_disabled() -> bool:
    """Return True when pipeline scripts should skip passenger OD merge."""
    import os

    return os.getenv("NIRD_DISABLE_PASSENGER_OD", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _normalize_assignment_od(od: pd.DataFrame, flow_col: str, source: str) -> pd.DataFrame:
    missing = set(REQUIRED_COLUMNS) - set(od.columns)
    if missing:
        raise ValueError(f"{source} OD missing columns: {sorted(missing)}")
    if flow_col not in od.columns:
        raise ValueError(f"{source} OD missing flow column '{flow_col}'")

    out = od.copy()
    out["origin_node"] = out["origin_node"].astype(str)
    out["destination_node"] = out["destination_node"].astype(str)
    out[flow_col] = pd.to_numeric(out[flow_col], errors="coerce").fillna(0.0)
    return out.groupby(["origin_node", "destination_node"], as_index=False)[flow_col].sum()


def combine_freight_passenger_od(
    freight_od: pd.DataFrame,
    passenger_od: pd.DataFrame,
    *,
    freight_flow_col: str = "Car21",
    passenger_flow_col: str = "Car21",
) -> pd.DataFrame:
    """Merge freight and passenger OD into one assignment matrix (summed Car21)."""
    freight = _normalize_assignment_od(freight_od, freight_flow_col, "freight").rename(
        columns={freight_flow_col: "freight_flow"}
    )
    passenger = _normalize_assignment_od(passenger_od, passenger_flow_col, "passenger").rename(
        columns={passenger_flow_col: "passenger_flow"}
    )

    combined = freight.merge(
        passenger,
        on=["origin_node", "destination_node"],
        how="outer",
    ).fillna({"freight_flow": 0.0, "passenger_flow": 0.0})
    combined["Car21"] = combined["freight_flow"] + combined["passenger_flow"]
    combined = combined[combined["Car21"] > 0].reset_index(drop=True)
    return combined[
        ["origin_node", "destination_node", "freight_flow", "passenger_flow", "Car21"]
    ]


def resolve_passenger_od_path(
    base_path: Path | None = None,
    *,
    year: int = 2022,
    job_type: str = "JT00",
) -> Path | None:
    """Locate passenger assignment OD from env or standard processed paths."""
    import os

    if passenger_od_disabled():
        return None

    env_path = os.getenv("NIRD_PASSENGER_OD_PATH")
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
    candidates.append(
        Path.home() / "Desktop" / "data" / "lodes_data" / "processed" / f"lodes_passenger_assignment_od_{job_type.lower()}_{year}.parquet"
    )
    for path in candidates:
        if path.exists():
            return path
    return None


def load_combined_assignment_od(
    freight_od: pd.DataFrame,
    *,
    passenger_path: str | Path | None = None,
    freight_flow_col: str = "Car21",
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Return assignment OD for Script 1; optionally merge passenger demand."""
    if passenger_path is None:
        assignment = _normalize_assignment_od(freight_od, freight_flow_col, "freight").rename(
            columns={freight_flow_col: "Car21"}
        )
        stats = {
            "freight_flow": float(assignment["Car21"].sum()),
            "passenger_flow": 0.0,
            "combined_flow": float(assignment["Car21"].sum()),
        }
        return assignment[["origin_node", "destination_node", "Car21"]], stats

    passenger_od = pd.read_parquet(passenger_path)
    combined = combine_freight_passenger_od(
        freight_od,
        passenger_od,
        freight_flow_col=freight_flow_col,
    )
    stats = {
        "freight_flow": float(combined["freight_flow"].sum()),
        "passenger_flow": float(combined["passenger_flow"].sum()),
        "combined_flow": float(combined["Car21"].sum()),
    }
    return combined[["origin_node", "destination_node", "Car21"]], stats
