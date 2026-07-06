"""Canonical link disruption record and legacy flood column mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

DAMAGE_LEVELS = ("no", "minor", "moderate", "extensive", "severe")


@dataclass
class LinkDisruptionRecord:
    """Hazard-agnostic per-link disruption state."""

    e_id: str
    hazard_type: str = "flood"
    event_id: str | int = 1
    scenario_param: int = 30
    intensity_primary: float = 0.0
    intensity_unit: str = "m_depth"
    max_speed: float | None = None
    damage_level_max: str = "no"
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_flood_row(cls, row: pd.Series, *, event_id: str | int, depth_key: int) -> "LinkDisruptionRecord":
        return cls(
            e_id=str(row["e_id"]),
            hazard_type="flood",
            event_id=event_id,
            scenario_param=depth_key,
            intensity_primary=float(row.get("flood_depth_max", 0.0) or 0.0),
            intensity_unit="m_depth",
            max_speed=float(row["max_speed"]) if pd.notna(row.get("max_speed")) else None,
            damage_level_max=str(row.get("damage_level_max", "no") or "no"),
        )


def apply_legacy_flood_columns(df: pd.DataFrame, *, depth_key: int, event_id: str | int) -> pd.DataFrame:
    """Attach canonical hazard metadata while preserving Script 3/4 flood column names."""
    out = df.copy()
    out["hazard_type"] = "flood"
    out["event_id"] = str(event_id)
    out["scenario_param"] = int(depth_key)
    out["intensity_primary"] = pd.to_numeric(out.get("flood_depth_max", 0.0), errors="coerce").fillna(0.0)
    out["intensity_unit"] = "m_depth"
    if "damage_level_max" in out.columns:
        out["damage_level_max"] = out["damage_level_max"].fillna("no")
    return out


def records_to_dataframe(records: list[LinkDisruptionRecord]) -> pd.DataFrame:
    rows = []
    for rec in records:
        rows.append(
            {
                "e_id": rec.e_id,
                "hazard_type": rec.hazard_type,
                "event_id": str(rec.event_id),
                "scenario_param": rec.scenario_param,
                "intensity_primary": rec.intensity_primary,
                "intensity_unit": rec.intensity_unit,
                "max_speed": rec.max_speed,
                "damage_level_max": rec.damage_level_max,
                **rec.extra,
            }
        )
    return pd.DataFrame(rows)
