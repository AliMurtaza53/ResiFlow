"""Load editable network mapping and assignment profile parameters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from resiflow.config import get_env
from resiflow.networks.base import (
    LEGACY_COMBINED_TO_TIER,
    LEGACY_PROFILE_FILE_ALIASES,
    TIER_TO_LEGACY_COMBINED,
)

_REPO_PARAMETERS = Path(__file__).resolve().parents[3] / "parameters"


def coerce_profile_dict(raw: dict[str, Any]) -> dict[str, float]:
    """Normalize profile dict keys to canonical assignment_tier names."""
    out: dict[str, float] = {}
    for key, value in raw.items():
        if key in LEGACY_COMBINED_TO_TIER:
            out[LEGACY_COMBINED_TO_TIER[key]] = float(value)
        elif key in TIER_TO_LEGACY_COMBINED:
            out[key] = float(value)
        else:
            out[str(key)] = float(value)
    return out


def resolve_params_root(params_root: Path | str | None = None) -> Path:
    """Resolve parameters directory (explicit path, env, or repo defaults)."""
    if params_root is not None:
        return Path(params_root)
    env_path = get_env("RESIFLOW_PARAMETERS_ROOT", "NIRD_PARAMETERS_ROOT")
    if env_path:
        return Path(env_path)
    return _REPO_PARAMETERS


def _read_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_network_mapping(
    source: str,
    *,
    params_root: Path | str | None = None,
) -> dict[str, Any]:
    """Load heuristic class→tier mapping for a network source."""
    root = resolve_params_root(params_root)
    path = root / f"network_mapping.{source}.json"
    if not path.exists():
        raise FileNotFoundError(f"Network mapping not found for source={source!r}: {path}")
    mapping = _read_json(path)
    mapping.setdefault("network_source", source)
    return mapping


def _load_legacy_profile_file(root: Path, profile_name: str) -> dict[str, float]:
    filename = LEGACY_PROFILE_FILE_ALIASES[profile_name]
    path = root / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing legacy profile file: {path}")
    return coerce_profile_dict(_read_json(path))


# T08 discretized-table columns -> assignment_profiles.json profile names.
# flow_breakpoint_pc_per_lane_hr/congestion_factor_mph_per_pcu are handled
# separately below: T08_assignment_tiers_UK_current.csv gives literal
# numbers for both (kept for backward compatibility), but
# T08_assignment_tiers_US_candidate.csv -- the real table this project
# actually points at as of 2026-10-08, see docs/FLOOD_TABLE_REVIEW.md --
# assumes a classic BPR a/b power-law congestion curve instead (its own
# flow_breakpoint column reads "n/a (use BPR)" for 3 of 4 tiers, and a
# range for the 4th) and has no congestion_factor column at all. This
# codebase's actual edge-speed model is piecewise-linear
# (breakpoint+slope), not BPR, so both are DERIVED from the table's real
# capacity/free-flow-speed via that model's own documented linearization
# (NCHRP 825 Exhibit 128: Q_bp = 0.85 x capacity; slope = free_flow_speed /
# (1.15 x capacity) -- already used identically in
# resiflow.networks.t08b_profile) whenever the literal columns aren't
# present or aren't clean numbers.
_TIER_TABLE_COLUMN_TO_PROFILE = {
    "flow_cap_pc_per_lane_hr": "flow_cap_plph",
    "free_flow_speed_mph": "free_flow_speed",
    "urban_speed_cap_mph": "urban_speed_cap",
    "min_speed_mph": "min_speed_cap",
}
_NCHRP825_BREAKPOINT_FRACTION = 0.85
_NCHRP825_SLOPE_DENOMINATOR_FACTOR = 1.15


def _load_profiles_from_table(
    table_name: str,
    params_root: Path | str | None,
) -> dict[str, dict[str, float]]:
    """Assignment profiles from a Txx tier table (assignment.use_table_tier_values)."""
    from resiflow.tables import load_table  # deferred: parameters<->profiles cycle

    table = load_table(table_name, params_root=params_root)
    profiles: dict[str, dict[str, float]] = {}
    for column, profile_name in _TIER_TABLE_COLUMN_TO_PROFILE.items():
        if column not in table.columns:
            raise ValueError(
                f"Tier table {table_name!r} is missing column {column!r} "
                f"(needed for profile {profile_name!r})."
            )
        values: dict[str, float] = {}
        for _, row in table.iterrows():
            try:
                values[str(row["tier"])] = float(row[column])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Tier table {table_name!r} column {column!r} has a "
                    f"non-numeric value {row[column]!r} for tier "
                    f"{row['tier']!r} — pull exact values before adoption "
                    "(see the table's provenance header)."
                ) from exc
        profiles[profile_name] = coerce_profile_dict(values)

    def _literal_column(column: str) -> dict[str, float] | None:
        if column not in table.columns:
            return None
        values: dict[str, float] = {}
        for _, row in table.iterrows():
            try:
                values[str(row["tier"])] = float(row[column])
            except (TypeError, ValueError):
                return None  # not clean numbers (e.g. "n/a (use BPR)") -- derive instead
        return values

    breakpoint_values = _literal_column("flow_breakpoint_pc_per_lane_hr")
    congestion_values = _literal_column("congestion_factor_mph_per_pcu")
    if breakpoint_values is None or congestion_values is None:
        capacity = profiles["flow_cap_plph"]
        free_flow = profiles["free_flow_speed"]
        breakpoint_values = {
            tier: _NCHRP825_BREAKPOINT_FRACTION * cap for tier, cap in capacity.items()
        }
        congestion_values = {
            tier: free_flow[tier] / (_NCHRP825_SLOPE_DENOMINATOR_FACTOR * cap)
            for tier, cap in capacity.items()
        }
    profiles["flow_breakpoint"] = coerce_profile_dict(breakpoint_values)
    profiles["congestion_factor"] = coerce_profile_dict(congestion_values)
    return profiles


def load_assignment_profiles(
    params_root: Path | str | None = None,
) -> dict[str, dict[str, float]]:
    """Load assignment profile dicts keyed by profile name (tier-keyed values).

    Prefers ``assignment_profiles.json`` when present; otherwise reads legacy
    per-profile JSON files (M/A_dual/... keys are coerced to assignment tiers).
    With ``assignment.use_table_tier_values`` enabled, the dicts come from the
    discretized tier table (``assignment.tier_table``, default
    ``T08_assignment_tiers_US_candidate`` as of 2026-10-08 -- its real US
    values now match ``assignment_profiles.json``'s own default values; see
    docs/FLOOD_TABLE_REVIEW.md. The old UK-current T08 file is archived.)
    """
    from resiflow.parameters import get_parameter  # deferred: import cycle

    if get_parameter("assignment", "use_table_tier_values", False):
        table_name = get_parameter(
            "assignment", "tier_table", "T08_assignment_tiers_US_candidate"
        )
        return _load_profiles_from_table(table_name, params_root)

    root = resolve_params_root(params_root)
    bundled = root / "assignment_profiles.json"
    if bundled.exists():
        raw = _read_json(bundled)
        # "_"-prefixed keys are documentation metadata (same convention as
        # unified_parameters.json's "_comment*" keys), not profile dicts.
        return {
            name: coerce_profile_dict(values)
            for name, values in raw.items()
            if not name.startswith("_")
        }

    profiles: dict[str, dict[str, float]] = {}
    for profile_name in LEGACY_PROFILE_FILE_ALIASES:
        profiles[profile_name] = _load_legacy_profile_file(root, profile_name)
    profiles["congestion_factor"] = {
        "freeway": 0.033,
        "arterial": 0.033,
        "collector": 0.05,
        "local_access": 0.05,
    }
    return profiles


def legacy_profile_dict(
    profiles: dict[str, dict[str, float]],
    profile_name: str,
) -> dict[str, float]:
    """Convert a tier-keyed profile dict to legacy combined_label keys."""
    tiered = profiles[profile_name]
    return {
        TIER_TO_LEGACY_COMBINED[tier]: value
        for tier, value in tiered.items()
        if tier in TIER_TO_LEGACY_COMBINED
    }
