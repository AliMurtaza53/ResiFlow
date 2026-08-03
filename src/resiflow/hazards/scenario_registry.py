"""Unique scenario keys for multihazard comparison (testbed and CONUS).

``scenario_param`` is the stable output-path key used under
``disruption_analysis/<variant>/<scenario_param>/`` and
``rerouting_analysis/<variant>/<scenario_param>/<event>/``.

``closure_threshold`` is the hazard-specific operational fragility parameter
(flood depth cm, snow mm, ice mm, etc.) and may differ from ``scenario_param``.

Legacy single-hazard runs keep backward compatibility: when no manifest or env
lookup matches, ``scenario_param`` and ``closure_threshold`` default to the Script 2
CLI argument.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from resiflow.hazards.base import parse_hazard_config, resolve_hazard_source_path
from resiflow.utils import load_config


@dataclass(frozen=True)
class HazardScenario:
    """Resolved hazard scenario for Script 2–4 path layout and fragility."""

    scenario_param: int
    hazard_type: str
    event_id: str = "1"
    closure_threshold: int | None = None
    hazard_subtype: str | None = None
    label: str | None = None

    def __post_init__(self) -> None:
        if self.closure_threshold is None:
            object.__setattr__(self, "closure_threshold", self.scenario_param)

    @property
    def operational_threshold(self) -> int:
        """Threshold passed to operational fragility curves."""
        return int(self.closure_threshold if self.closure_threshold is not None else self.scenario_param)

    @property
    def scenario_key(self) -> str:
        """Directory name for disruption/rerouting outputs."""
        return str(self.scenario_param)

    def matches_env(self, *, hazard_type: str, flood_subtype: str | None = None) -> bool:
        if self.hazard_type != hazard_type:
            return False
        if hazard_type == "flood" and flood_subtype and self.hazard_subtype:
            return self.hazard_subtype == flood_subtype
        if flood_subtype and self.hazard_subtype:
            return self.hazard_subtype == flood_subtype
        return True


# Built-in registry: unique scenario_param per hazard (network-scale agnostic).
# CONUS production should prefer ``hazards.json`` with the same fields.
_BUILTIN_SCENARIOS: tuple[HazardScenario, ...] = (
    HazardScenario(301, "flood", hazard_subtype="flood_surface", closure_threshold=30, label="flood_surface"),
    HazardScenario(302, "flood", hazard_subtype="flood_river", closure_threshold=30, label="flood_river"),
    HazardScenario(303, "flood", hazard_subtype="flood_coastal", closure_threshold=30, label="flood_coastal"),
    HazardScenario(401, "earthquake", closure_threshold=25, label="earthquake"),
    # Real NSHM 2023 (probabilistic, 475yr RP) contour-rasterized PGA, the
    # earthquake default before 2026-08-03. Kept reachable under its own
    # scenario_param now that 401's default resolves to the real 2011
    # Mineral, VA ShakeMap PGA instead (see hazards/real_va.py,
    # RealEarthquakeShakeMapSource, and docs/VA_MULTIHAZARD_COMPARISON.md).
    HazardScenario(
        402, "earthquake", hazard_subtype="earthquake_nshm", closure_threshold=25, label="earthquake_nshm"
    ),
    HazardScenario(501, "landslide", closure_threshold=100, label="landslide"),
    HazardScenario(601, "winter_storm", closure_threshold=100, label="winter_storm"),
    HazardScenario(701, "snow", closure_threshold=150, label="snow"),
    # Legacy single-hazard keys (scenario_param == closure_threshold).
    HazardScenario(30, "flood", closure_threshold=30, label="flood_legacy"),
    HazardScenario(150, "snow", closure_threshold=150, label="snow_legacy"),
)


def _entry_to_scenario(entry: dict[str, Any]) -> HazardScenario:
    cfg = parse_hazard_config(entry)
    closure = entry.get("closure_threshold")
    if closure is None:
        closure = entry.get("depth_key") or entry.get("snow_key_mm") or entry.get("ice_key_mm")
    return HazardScenario(
        scenario_param=int(cfg["scenario_param"]),
        hazard_type=str(cfg["hazard_type"]),
        event_id=str(cfg["event_id"]),
        closure_threshold=int(closure) if closure is not None else None,
        hazard_subtype=entry.get("hazard_subtype") or entry.get("flood_subtype"),
        label=entry.get("label"),
    )


def load_hazard_manifest(path: Path | str) -> list[HazardScenario]:
    """Load scenarios from a hazards.json manifest."""
    manifest_path = Path(path)
    if not manifest_path.exists():
        return []
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    events = data.get("events", data if isinstance(data, list) else [])
    return [_entry_to_scenario(entry) for entry in events]


def iter_registered_scenarios(
    *,
    manifest_path: Path | str | None = None,
    base_path: Path | None = None,
) -> Iterator[HazardScenario]:
    """Yield manifest scenarios first, then built-in defaults (deduped by scenario_param)."""
    seen: set[int] = set()
    if manifest_path is not None:
        for scenario in load_hazard_manifest(manifest_path):
            if scenario.scenario_param not in seen:
                seen.add(scenario.scenario_param)
                yield scenario
        return

    if base_path is not None:
        for candidate in (
            resolve_hazard_source_path({}, base_path),
            base_path / "hazards.json",
            base_path / "inputs" / "hazards.json",
        ):
            if candidate.exists():
                for scenario in load_hazard_manifest(candidate):
                    if scenario.scenario_param not in seen:
                        seen.add(scenario.scenario_param)
                        yield scenario

    for scenario in _BUILTIN_SCENARIOS:
        if scenario.scenario_param not in seen:
            seen.add(scenario.scenario_param)
            yield scenario


def _env_hazard_type() -> str:
    return os.environ.get("RESIFLOW_HAZARD_TYPE", "flood").strip().lower()


def _env_flood_subtype() -> str | None:
    raw = os.environ.get("RESIFLOW_FLOOD_SUBTYPE", "").strip()
    return raw or None


def lookup_scenario_by_param(
    scenario_param: int,
    *,
    manifest_path: Path | str | None = None,
    base_path: Path | None = None,
) -> HazardScenario | None:
    for scenario in iter_registered_scenarios(manifest_path=manifest_path, base_path=base_path):
        if scenario.scenario_param == int(scenario_param):
            return scenario
    return None


def lookup_scenario_by_env(
    *,
    manifest_path: Path | str | None = None,
    base_path: Path | None = None,
    event_id: str | None = None,
) -> HazardScenario | None:
    hazard_type = _env_hazard_type()
    flood_subtype = _env_flood_subtype() if hazard_type == "flood" else None

    for scenario in iter_registered_scenarios(manifest_path=manifest_path, base_path=base_path):
        if event_id is not None and scenario.event_id != str(event_id):
            continue
        if scenario.matches_env(hazard_type=hazard_type, flood_subtype=flood_subtype):
            return scenario
    return None


def resolve_active_scenario(
    *,
    scenario_param: int | None = None,
    event_id: str = "1",
    closure_threshold: int | None = None,
    manifest_path: Path | str | None = None,
    base_path: Path | None = None,
) -> HazardScenario:
    """Resolve the active scenario for Script 2–4.

    Resolution order:
    1. Explicit ``RESIFLOW_SCENARIO_PARAM`` env (if set) + manifest/builtin lookup
    2. ``scenario_param`` CLI argument + manifest/builtin lookup
    3. ``RESIFLOW_HAZARD_TYPE`` / ``RESIFLOW_FLOOD_SUBTYPE`` env lookup
    4. Legacy fallback: ``scenario_param`` doubles as ``closure_threshold``
    """
    if base_path is None:
        try:
            base_path = Path(load_config()["paths"]["soge_clusters"])
        except Exception:
            base_path = None

    explicit_manifest = manifest_path or os.environ.get("RESIFLOW_HAZARDS_MANIFEST", "").strip() or None

    env_param = os.environ.get("RESIFLOW_SCENARIO_PARAM", "").strip()
    if env_param:
        scenario_param = int(env_param)

    if scenario_param is not None:
        found = lookup_scenario_by_param(
            int(scenario_param),
            manifest_path=explicit_manifest,
            base_path=base_path,
        )
        if found is not None:
            if closure_threshold is not None:
                return HazardScenario(
                    scenario_param=found.scenario_param,
                    hazard_type=found.hazard_type,
                    event_id=str(event_id),
                    closure_threshold=int(closure_threshold),
                    hazard_subtype=found.hazard_subtype,
                    label=found.label,
                )
            return HazardScenario(
                scenario_param=found.scenario_param,
                hazard_type=found.hazard_type,
                event_id=str(event_id),
                closure_threshold=found.closure_threshold,
                hazard_subtype=found.hazard_subtype,
                label=found.label,
            )

    by_env = lookup_scenario_by_env(
        manifest_path=explicit_manifest,
        base_path=base_path,
        event_id=str(event_id),
    )
    if by_env is not None:
        if scenario_param is not None and by_env.scenario_param != int(scenario_param):
            # Env-selected hazard with explicit CLI scenario_param: trust CLI for path key.
            return HazardScenario(
                scenario_param=int(scenario_param),
                hazard_type=by_env.hazard_type,
                event_id=str(event_id),
                closure_threshold=int(closure_threshold) if closure_threshold is not None else by_env.closure_threshold,
                hazard_subtype=by_env.hazard_subtype,
                label=by_env.label,
            )
        return HazardScenario(
            scenario_param=by_env.scenario_param,
            hazard_type=by_env.hazard_type,
            event_id=str(event_id),
            closure_threshold=int(closure_threshold) if closure_threshold is not None else by_env.closure_threshold,
            hazard_subtype=by_env.hazard_subtype,
            label=by_env.label,
        )

    if scenario_param is None:
        raise ValueError(
            "Could not resolve hazard scenario: provide Script 2 scenario_param or set "
            "RESIFLOW_SCENARIO_PARAM / RESIFLOW_HAZARD_TYPE with a registered hazard."
        )

    threshold = int(closure_threshold) if closure_threshold is not None else int(scenario_param)
    return HazardScenario(
        scenario_param=int(scenario_param),
        hazard_type=_env_hazard_type(),
        event_id=str(event_id),
        closure_threshold=threshold,
        hazard_subtype=_env_flood_subtype(),
    )


def scenario_param_from_path(intersections_path: Path) -> str:
    """Extract scenario_param from ``.../<scenario_param>/intersections/...``."""
    # parent = intersections/, grandparent = scenario_param
    return intersections_path.parent.parent.name


def damage_output_path(
    results_root: Path,
    variant: str,
    scenario_param: int | str,
    event_stem: str,
) -> Path:
    """Path for Script 3 damage CSV (unique per scenario + event)."""
    return (
        results_root
        / "damage_analysis"
        / variant
        / str(scenario_param)
        / f"{event_stem}_with_damage_values.csv"
    )
