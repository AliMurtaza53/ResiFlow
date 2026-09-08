"""Shared hazard-scenario selection for the finale figures/maps.

Which scenario_params go into this comparison batch, and what to call them
-- NOT dollar data (build_finale_figures.py reads that from disk) or
geometry (build_finale_damage_maps.py reads that from disk). hazard_type/
hazard_subtype are looked up once here from the code-owned registry
(resiflow.hazards.scenario_registry._BUILTIN_SCENARIOS) instead of being
hand-duplicated in both scripts, so they can't drift out of sync with each
other or with the registry itself.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from resiflow.hazards.scenario_registry import lookup_scenario_by_param

VARIANT = "conus_nandu_v1"
EVENT_KEY = 1

# (scenario_param, display label). Extend as more hazards finish a complete
# pipeline run for this variant -- cross-check with
# viz_data_loaders.list_available_scenario_params(results_root, VARIANT) to
# see what's actually on disk before adding one here. 602/603/604 (winter
# storm Uri/Elliott/Snowmageddon) intentionally excluded as of 2026-09: not
# yet a completed scenario for this variant (see docs/PROJECT_LOG.md).
_SCENARIO_LABELS: list[tuple[int, str]] = [
    (301, "Flood"),
    (304, "Harvey"),
    (401, "Earthquake (Mineral)"),
    (403, "Earthquake (New Madrid)"),
    (501, "Landslide"),
    (601, "Winter storm (Jonas)"),
]


@dataclass(frozen=True)
class FinaleHazard:
    scenario_param: int
    event_key: int
    hazard_label: str
    hazard_type: str
    hazard_subtype: str


def finale_hazards() -> list[FinaleHazard]:
    hazards = []
    for scenario_param, hazard_label in _SCENARIO_LABELS:
        scenario = lookup_scenario_by_param(scenario_param)
        if scenario is None:
            raise ValueError(
                f"scenario_param={scenario_param} ({hazard_label}) is not in "
                "resiflow.hazards.scenario_registry -- register it there first."
            )
        hazards.append(
            FinaleHazard(
                scenario_param=scenario_param,
                event_key=EVENT_KEY,
                hazard_label=hazard_label,
                hazard_type=scenario.hazard_type,
                hazard_subtype=scenario.hazard_subtype or "",
            )
        )
    return hazards
