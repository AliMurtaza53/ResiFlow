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
    """
    table = load_table(name, params_root=params_root)
    rows = table.loc[table["recovery_scenario"].isin([scenario, "all"])]
    if rows.loc[rows["recovery_scenario"] == scenario].empty:
        known = sorted(set(table["recovery_scenario"]) - {"all"})
        raise ValueError(
            f"Recovery scenario {scenario!r} not in table {name!r}; known: {known}"
        )

    steps: dict[str, tuple[float, float]] = {}
    event_days = {0}
    for _, row in rows.iterrows():
        if str(row["capacity_50pct_day"]).strip().lower() == "none":
            continue  # no capacity loss (minor_moderate)
        d50 = float(row["capacity_50pct_day"])
        d100 = float(row["capacity_100pct_day"])
        steps[str(row["damage_level"])] = (d50, d100)
        event_days.update((int(d50), int(d100)))
    days = sorted(event_days)

    def _rate(level: str, day: int) -> float:
        source = "minor_moderate" if level in ("minor", "moderate") else level
        if source not in steps:
            return 1.0  # no capacity loss at any day
        d50, d100 = steps[source]
        if day < d50:
            return 0.0
        if day < d100:
            return 0.5
        return 1.0

    recovery_dict: dict[str, list[float]] = {
        level: [_rate(level, day) for day in days]
        for level in ("minor", "moderate", "extensive", "severe")
    }
    return recovery_dict, days
