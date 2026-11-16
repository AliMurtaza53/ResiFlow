"""Which vehicle class the assignment costs a run with (time value, fuel curve, occupancy).

Until 2026-11 every stage hard-coded vehicle_type="car", so freight trucks were costed as
passenger cars. Now:
  freight-only      -> "ogv"  (truck driver value of time, diesel heavy-truck fuel curve)
  passenger-only    -> "car"
  freight+passenger -> "car" on the combined PCE-weighted flow (trucks count ``truck_pce`` times);
                       a single-cost approximation, not a true multi-class assignment.
Override with RESIFLOW_VEHICLE_CLASS / NIRD_VEHICLE_CLASS (e.g. a passenger-only run that loads
its OD through the freight slot must set ``car``).
"""

from __future__ import annotations

import os

VALID_CLASSES = ("car", "ogv", "lgv", "psv", "rail")


def vehicle_class_override() -> str | None:
    for key in ("RESIFLOW_VEHICLE_CLASS", "NIRD_VEHICLE_CLASS"):
        raw = os.getenv(key, "").strip().lower()
        if raw:
            if raw not in VALID_CLASSES:
                raise ValueError(f"{key}={raw!r}; expected one of {VALID_CLASSES}")
            return raw
    return None


def vehicle_class_for_stats(stats: dict[str, float]) -> str:
    """Class for Script 1 from the loaded demand totals."""
    forced = vehicle_class_override()
    if forced:
        return forced
    freight = float(stats.get("freight_flow", 0.0))
    passenger = float(stats.get("passenger_flow", 0.0))
    if passenger <= 0 < freight:
        return "ogv"
    return "car"


def vehicle_class_for_mode(mode_name: str) -> str:
    """Class for Script 4 from its reroute mode ('freight', 'passenger' or 'combined')."""
    forced = vehicle_class_override()
    if forced:
        return forced
    return "ogv" if mode_name == "freight" else "car"


def truck_pce() -> float:
    """Passenger-car equivalents per truck when freight and passenger share one assignment."""
    from resiflow.parameters import get_parameter

    return float(get_parameter("assignment", "truck_pce", 2.0))
