"""Backward-compatible re-exports; prefer :mod:`resiflow.demand`."""

from resiflow.demand.combine import (
    combine_freight_passenger_od,
    load_combined_assignment_od,
    passenger_od_disabled,
    resolve_passenger_od_path,
)

__all__ = [
    "combine_freight_passenger_od",
    "load_combined_assignment_od",
    "passenger_od_disabled",
    "resolve_passenger_od_path",
]
