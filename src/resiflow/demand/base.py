"""Demand adapter types and assignment OD contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

REQUIRED_OD_COLUMNS = ("origin_node", "destination_node")
DEFAULT_FLOW_COL = "Car21"


@dataclass(frozen=True)
class DemandSpec:
    """Resolved demand configuration for Script 1 / 4."""

    source: str
    freight_path: Path | None = None
    passenger_path: Path | None = None
    demand_scale: float = 1.0
    freight_share: float | None = None
    flow_col: str = DEFAULT_FLOW_COL
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DemandLoadResult:
    """Assignment-ready OD plus optional mode splits."""

    assignment_od: pd.DataFrame
    freight_od: pd.DataFrame | None = None
    passenger_od: pd.DataFrame | None = None
    stats: dict[str, float] = field(default_factory=dict)


class DemandSource(Protocol):
    """Build or load assignment OD from a particular demand source."""

    source_name: str

    def load(self, spec: DemandSpec) -> DemandLoadResult: ...
