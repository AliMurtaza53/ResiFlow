"""Loader for the discretized parameter tables in ``parameters/tables/``.

The CSVs (audit-matrix ``Txx`` prefixes, see ``parameters/tables/manifest.csv``)
carry ``#`` provenance header lines followed by labeled-axis columns with units
embedded in the column names. This module is the single entry point for
consuming them:

* :func:`load_table` — read a table by name, skipping ``#`` lines, enforcing
  the status vocabulary (refuses ``PLACEHOLDER_DO_NOT_USE`` rows, warns on
  ``APPROXIMATE_VERIFY`` / ``TEMPLATE_REPLACE_VALUES`` files).
* :func:`interpolate` — linear interpolation of a value column against the
  table's axis column (the first column by default).
* :func:`recovery_schedule_from_table` — derive Script 4's day-by-day
  recovery-rate dicts from the step-wise T26 schedule.
* :func:`recovery_schedule_from_bridge_and_road_tables` — the same, with
  separate bridge/road T26 tables evaluated at their shared day union.
* :func:`residual_speed_factor` — T37/T38 damage×day residual speed for
  earthquake/landslide (Script 4 non-flood branch).
* :func:`flood_residual_speed_gate` — T27 day-range -> depth-gate tier for
  flood's residual-speed restriction (Script 4 flood branch).

Paths route through ``resolve_params_root`` so ``RESIFLOW_PARAMETERS_ROOT``
(and explicit ``params_root=``) relocate the tables together with every other
parameter file.

Consumers stay behind ``get_parameter`` flags that default to the current
behavior — nothing in the model reads these tables unless a
``use_table_*`` flag is switched on (see ``parameters/README.md``).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from resiflow.parameters import resolve_params_root

logger = logging.getLogger(__name__)

_MANIFEST_NAME = "manifest.csv"
_STATUS_REFUSE = "PLACEHOLDER_DO_NOT_USE"
# File-level statuses (manifest.csv) that are usable but not authoritative yet.
_STATUS_WARN = ("APPROXIMATE_VERIFY", "TEMPLATE_REPLACE_VALUES")


def tables_root(params_root: Path | str | None = None) -> Path:
    """Directory holding the discretized parameter tables."""
    return Path(resolve_params_root(params_root)) / "tables"


def _normalize_name(name: str) -> str:
    return name if name.endswith(".csv") else f"{name}.csv"


def _manifest_status(root: Path, filename: str) -> str:
    """File-level status from manifest.csv ('' if no manifest / not listed)."""
    manifest_path = root / _MANIFEST_NAME
    if not manifest_path.exists():
        return ""
    manifest = pd.read_csv(manifest_path, comment="#")
    row = manifest.loc[manifest["file"] == filename]
    if row.empty:
        return ""
    return str(row.iloc[0]["status"])


def load_table(
    name: str,
    *,
    params_root: Path | str | None = None,
) -> pd.DataFrame:
    """Load a parameter table by name (``.csv`` optional), skipping ``#`` lines.

    Status enforcement (manifest vocabulary):

    * A file whose manifest status is ``PLACEHOLDER_DO_NOT_USE`` refuses to
      load (``ValueError``).
    * Rows whose own ``status`` column contains ``PLACEHOLDER_DO_NOT_USE``
      (e.g. T20's coastal thresholds) are dropped with a warning — they are
      never served to a consumer.
    * ``APPROXIMATE_VERIFY`` / ``TEMPLATE_REPLACE_VALUES`` files load with a
      warning: values are anchored or illustrative, not authoritative.
    """
    filename = _normalize_name(name)
    root = tables_root(params_root)
    path = root / filename
    if not path.exists():
        raise FileNotFoundError(f"Parameter table not found: {path}")

    file_status = _manifest_status(root, filename)
    if _STATUS_REFUSE in file_status:
        raise ValueError(
            f"Refusing to load {filename}: manifest status {file_status!r}."
        )
    if any(token in file_status for token in _STATUS_WARN):
        logger.warning(
            "Parameter table %s has status %s: values are not authoritative "
            "yet (see its provenance header for the extraction source).",
            filename,
            file_status,
        )

    table = pd.read_csv(path, comment="#", skip_blank_lines=True)

    if "status" in table.columns:
        placeholder = table["status"].astype(str).str.contains(
            _STATUS_REFUSE, regex=False
        )
        if placeholder.any():
            logger.warning(
                "Dropping %d %s row(s) from %s: %s",
                int(placeholder.sum()),
                _STATUS_REFUSE,
                filename,
                ", ".join(map(str, table.loc[placeholder].iloc[:, 0].tolist())),
            )
            table = table.loc[~placeholder].reset_index(drop=True)

    return table


def resolve_column(table: pd.DataFrame, column: str) -> str:
    """Exact column name, or the unique column starting with ``column``.

    Prefix matching keeps consumers stable across candidate files that append
    clarifiers to a class label (e.g. ``fuel_l_per_km_ogv`` matching
    ``fuel_l_per_km_ogv_truck`` in the US candidate table).
    """
    if column in table.columns:
        return column
    matches = [c for c in table.columns if c.startswith(column)]
    if len(matches) == 1:
        return matches[0]
    raise KeyError(
        f"Column {column!r} not found (or ambiguous: {matches}) in table "
        f"columns {list(table.columns)}"
    )


def interpolate(
    table: pd.DataFrame,
    x,
    column: str,
    *,
    axis_column: str | None = None,
):
    """Linearly interpolate ``column`` at ``x`` along the table's axis column.

    ``axis_column`` defaults to the table's first column. Outside the axis
    range the end values are held (``np.interp`` semantics). Returns a float
    for scalar ``x``, else an ndarray of the same shape.
    """
    axis = axis_column if axis_column is not None else table.columns[0]
    if axis not in table.columns:
        raise KeyError(f"Axis column {axis!r} not in table columns {list(table.columns)}")
    col = resolve_column(table, column)
    xp = pd.to_numeric(table[axis], errors="raise").to_numpy(dtype=float)
    fp = pd.to_numeric(table[col], errors="raise").to_numpy(dtype=float)
    if not np.all(np.diff(xp) > 0):
        order = np.argsort(xp)
        xp, fp = xp[order], fp[order]
    result = np.interp(np.asarray(x, dtype=float), xp, fp)
    return float(result) if np.isscalar(x) or np.ndim(x) == 0 else result


def _recovery_steps_from_table(
    name: str,
    scenario: str,
    *,
    params_root: Path | str | None = None,
) -> dict[str, tuple[float, float]]:
    """Load a T26-shaped table's (capacity_50pct_day, capacity_100pct_day)
    steps per damage level, for one named recovery scenario. Pure data
    loading, factored out of :func:`recovery_schedule_from_table` so a
    bridge table and a road table can each be loaded and then evaluated at
    a SHARED set of event days (see
    :func:`recovery_schedule_from_bridge_and_road_tables`)."""
    table = load_table(name, params_root=params_root)
    rows = table.loc[table["recovery_scenario"].isin([scenario, "all"])]
    if rows.loc[rows["recovery_scenario"] == scenario].empty:
        known = sorted(set(table["recovery_scenario"]) - {"all"})
        raise ValueError(
            f"Recovery scenario {scenario!r} not in table {name!r}; known: {known}"
        )
    steps: dict[str, tuple[float, float]] = {}
    for _, row in rows.iterrows():
        if str(row["capacity_50pct_day"]).strip().lower() == "none":
            continue  # no capacity loss (minor_moderate)
        d50 = float(row["capacity_50pct_day"])
        d100 = float(row["capacity_100pct_day"])
        steps[str(row["damage_level"])] = (d50, d100)
    return steps


def _recovery_rate(steps: dict[str, tuple[float, float]], level: str, day: float) -> float:
    source = "minor_moderate" if level in ("minor", "moderate") else level
    if source not in steps:
        return 1.0  # no capacity loss at any day
    d50, d100 = steps[source]
    if day < d50:
        return 0.0
    if day < d100:
        return 0.5
    return 1.0


def recovery_schedule_from_table(
    name: str = "T26_recovery_design_current",
    scenario: str = "average",
    *,
    params_root: Path | str | None = None,
) -> tuple[dict[str, list[float]], list[int]]:
    """Day-by-day recovery rates from the step-wise T26 design table.

    T26 encodes capacity steps 0% -> 50% (``capacity_50pct_day``) -> 100%
    (``capacity_100pct_day``) per damage level for a named recovery scenario
    (fast/average/slow); ``minor_moderate`` rows mean no capacity loss.
    Returns ``(recovery_dict, event_days)`` where ``recovery_dict`` maps each
    of minor/moderate/extensive/severe to a rate per event day — the same
    shape Script 4 builds from the data bundle's recovery design CSV.

    Single-table convenience wrapper; see
    :func:`recovery_schedule_from_bridge_and_road_tables` for the
    bridge/road split (different tables with different event-day
    checkpoints, evaluated at their shared union of days).
    """
    steps = _recovery_steps_from_table(name, scenario, params_root=params_root)
    event_days = {0}
    for d50, d100 in steps.values():
        event_days.update((int(d50), int(d100)))
    days = sorted(event_days)
    recovery_dict: dict[str, list[float]] = {
        level: [_recovery_rate(steps, level, day) for day in days]
        for level in ("minor", "moderate", "extensive", "severe")
    }
    return recovery_dict, days


def recovery_schedule_from_bridge_and_road_tables(
    bridge_table: str,
    road_table: str,
    scenario: str = "average",
    *,
    params_root: Path | str | None = None,
) -> tuple[dict[str, list[float]], dict[str, list[float]], list[int]]:
    """Separate bridge/road recovery schedules, evaluated at their shared
    union of event-day checkpoints.

    Fixes the gap flagged in docs/FLOOD_TABLE_REVIEW.md ("T26 lacks the
    bridge/road split the data bundle's own recovery design CSV has --
    switching flags silently gives bridges the road schedule"): bridges
    and roads recover on genuinely different timelines (e.g. a bridge's
    'average'-scenario extensive-damage full recovery is real-world
    re-anchored to 147 days -- NCHRP WOD 390's Harvey/I-69 case -- vs. a
    road's 90 days), so they need their own tables, not one shared dict.
    The two tables' own day checkpoints rarely coincide, so both are
    evaluated at the UNION of both tables' checkpoints (each table's
    ``_recovery_rate`` already generalizes to any day via its day<d50/
    day<d100 step logic, not just its own native checkpoints).
    """
    bridge_steps = _recovery_steps_from_table(bridge_table, scenario, params_root=params_root)
    road_steps = _recovery_steps_from_table(road_table, scenario, params_root=params_root)

    event_days = {0}
    for steps in (bridge_steps, road_steps):
        for d50, d100 in steps.values():
            event_days.update((int(d50), int(d100)))
    days = sorted(event_days)

    levels = ("minor", "moderate", "extensive", "severe")
    bridge_dict = {level: [_recovery_rate(bridge_steps, level, day) for day in days] for level in levels}
    road_dict = {level: [_recovery_rate(road_steps, level, day) for day in days] for level in levels}
    return bridge_dict, road_dict, days


def residual_speed_factor(
    *,
    hazard: str,
    asset: str,
    damage_level: str,
    event_day: int | float,
    scenario: str = "average",
    table_name: str | None = None,
    params_root: Path | str | None = None,
) -> float:
    """Interpolate residual speed_factor from T37/T38 (or named table).

    Returns 1.0 for damage_level ``no`` or empty/missing series. Holds end
    values outside the tabulated day range (``np.interp``). Raises if the
    table has no rows for the requested hazard/asset/scenario when damage
    is not ``no``.
    """
    level = str(damage_level).strip().lower()
    if level in ("", "no", "none", "nan"):
        return 1.0

    if table_name is None:
        hazard_l = str(hazard).strip().lower()
        if hazard_l == "earthquake":
            table_name = "T37_earthquake_residual_speed_schedule"
        elif hazard_l == "landslide":
            table_name = "T38_landslide_residual_speed_schedule"
        else:
            raise ValueError(
                f"No residual-speed table for hazard={hazard!r}; "
                "pass table_name= or use earthquake/landslide"
            )

    table = load_table(table_name, params_root=params_root)
    for col in (
        "hazard",
        "asset",
        "damage_level",
        "recovery_scenario",
        "event_day",
        "speed_factor",
    ):
        if col not in table.columns:
            raise KeyError(f"{table_name} missing required column {col!r}")

    sub = table.loc[
        (table["hazard"].astype(str).str.lower() == str(hazard).strip().lower())
        & (table["asset"].astype(str).str.lower() == str(asset).strip().lower())
        & (table["damage_level"].astype(str).str.lower() == level)
        & (table["recovery_scenario"].astype(str).str.lower() == str(scenario).strip().lower())
    ]
    if sub.empty:
        raise KeyError(
            f"{table_name} has no rows for hazard={hazard!r} asset={asset!r} "
            f"damage_level={level!r} scenario={scenario!r}"
        )
    days = pd.to_numeric(sub["event_day"], errors="raise").to_numpy(dtype=float)
    factors = pd.to_numeric(sub["speed_factor"], errors="raise").to_numpy(dtype=float)
    order = np.argsort(days)
    days, factors = days[order], factors[order]
    return float(np.interp(float(event_day), days, factors))


# T27's 4 rows always reduce to one of these 3 depth-gated tiers (the 4th,
# "none", needs no gate at all and is the implicit fallback below).
_T27_TIER_ALL = "all"
_T27_TIER_INTERMEDIATE_AND_DEEP = "intermediate_and_deep"
_T27_TIER_DEEP_ONLY = "deep_only"
_T27_TIER_NONE = "none"


def flood_residual_speed_gate(
    event_day: int | float,
    *,
    table_name: str = "T27_speed_restriction_schedule",
    params_root: Path | str | None = None,
) -> str:
    """Which depth tier T27 says gets a speed restriction on this event day.

    Returns one of ``"all"`` (every flooded segment -- T19 speed-depth
    reduction), ``"intermediate_and_deep"`` (segments whose INITIAL depth
    exceeds ``recovery.residual_depth_gates_m.intermediate``),
    ``"deep_only"`` (exceeds ``.deep``), or ``"none"`` (fully restored).
    The depth THRESHOLD values themselves stay driven by that existing SA
    seam, not duplicated into this table; only the DAY RANGE each tier is
    active for is read from T27, so edits to the table's
    ``event_day_from``/``event_day_to`` columns take effect without a code
    change.

    Found and fixed 2026-10-08 (docs/FLOOD_TABLE_REVIEW.md Section 4 item 7):
    Script 4's previous hardcoded ``if event_day == 1/2/3`` gate never
    actually matched this project's real recovery-schedule day checkpoints
    (0, 7, 14, 30, 60, 90 -- see T26/the data bundle's
    ``recovery design_updated.csv``), so the flood residual-speed
    restriction was DEAD CODE in every real run: no real event_day ever
    equalled 1, 2, or 3. This function generalizes to any event_day,
    fixing that silently-inert logic.
    """
    table = load_table(table_name, params_root=params_root)
    for col in ("event_day_from", "event_day_to", "applies_to"):
        if col not in table.columns:
            raise KeyError(f"{table_name} missing required column {col!r}")

    day = float(event_day)
    for row in table.itertuples():
        day_from = float(row.event_day_from)
        day_to_raw = str(row.event_day_to).strip().lower()
        day_to = float("inf") if day_to_raw == "inf" else float(row.event_day_to)
        if not (day_from <= day <= day_to):
            continue
        applies_to = str(row.applies_to).strip().lower()
        if "all flooded segments" in applies_to:
            return _T27_TIER_ALL
        if "6 m" in applies_to:
            return _T27_TIER_DEEP_ONLY
        if "2 m" in applies_to:
            return _T27_TIER_INTERMEDIATE_AND_DEEP
        return _T27_TIER_NONE
    return _T27_TIER_NONE  # no matching row (day beyond the table) -- fully restored
