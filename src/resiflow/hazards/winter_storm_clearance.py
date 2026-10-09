"""Winter storm plow-clearance model: T33 class->rank, T34 day_open, T35
post-reopening residual speed, peak-day closure flag.

Consumes the damage level from the shared classification
(``fragility/winter_storm_categorical.py``) and the raw FAF5 ``Class`` code
(``faf5_class`` column; ``road_classification`` is NOT used here because it
collapses classes T33 needs to tell apart -- 23 -> 'primary', 16/17/18/19/36/41
-> 'service'). Produces, per link:

  * ``clearance_rank``          1..5 (nullable Int64); NA for excluded/unclassified links
  * ``clearance_rank_source``   direct | topology | isolated_default | excluded | unclassified
  * ``day_open``                day the link becomes passable, counted from end of storm
                                (T34; 0 = damage level "no", never closed; NA = no rank)
  * ``winter_peak_closure_flag`` rank-5 link whose PEAK depth reached the passenger-car
                                clearance threshold (200 mm)

The closure flag is deliberately a one-time PEAK-DAY flag, NOT a dynamic gate.
Only a single peak-day depth snapshot exists per event (no post-storm daily
series), so a gate re-evaluated each day against that frozen depth would either
fail forever or never be re-checked. The flag marks links whose T34 ``day_open``
should be trusted less (they may still be buried past clearance when T34 says
"open"); it does not close or reopen anything.

T33 rank assignment
  * classes with a direct rank take it;
  * TOPOLOGY classes (ramps, C/D lanes, circles, ...) inherit the best (lowest)
    rank of any link sharing a node -- undirected, repeated until stable
    (multi-hop, so a ramp chain resolves through its neighbours);
  * TOPOLOGY links with no ranked link reachable (isolated components) get
    ``DEFAULT_ISOLATED_RANK`` = 2, the network's modal rank;
  * EXCLUDE classes (41 ferry, 50 centroid connector) get no rank and no damage
    level -- always treated as open/unaffected.
Note ranks 3 and 4 have no member classes under T33-new (only 1, 2 and 5), so
T34's rank-3/4 columns are unused by construction.

T34 region: T34 needs a per-link snowfall-region class (high/moderate/low
capability) that does not exist in the pipeline yet. Until it does, one region
applies to every link (default "moderate", region_factor 1; override via
``hazard_disruption.winter_storm_snow_region``).
"""

from __future__ import annotations

import csv
import logging
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from resiflow.parameters import get_parameter
from resiflow.tables import tables_root

logger = logging.getLogger(__name__)

T33_TABLE = "T33_winter_storm_clearance_order_new.csv"
T34_TABLE = "T34_winter_storm_clearance_schedule.csv"
T35_TABLE = "T35_winter_storm_speed_recovery.csv"

DEFAULT_ISOLATED_RANK = 2
CLOSURE_FLAG_RANK = 5
CLOSURE_FLAG_DEPTH_MM = 200.0  # passenger-car ground clearance, T19-winter closure block (200-250 mm)
EXCLUDED_CLASSES = (41, 50)

_TOPOLOGY = "TOPOLOGY"
_EXCLUDE = "EXCLUDE"
_MAX_HOPS = 500


@lru_cache(maxsize=1)
def load_class_rank_map(params_root: str | None = None) -> dict[int, int | str]:
    """faf5 Class code -> rank (int) | "TOPOLOGY" | "EXCLUDE", from T33-new's first block.

    T33's CSV stacks the class->rank block and the rank->fleet-share block under
    different columns; only the first (from the ``network_class_code`` header to the
    next ``#`` row) is class-keyed.
    """
    path = Path(tables_root(params_root)) / T33_TABLE
    out: dict[int, int | str] = {}
    in_block = False
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            first = row[0].strip()
            if not in_block:
                in_block = first == "network_class_code"
                continue
            if first.startswith("#"):
                break
            assigned = row[3].strip().upper()
            out[int(first)] = assigned if assigned in (_TOPOLOGY, _EXCLUDE) else int(assigned)
    if not out:
        raise ValueError(f"{T33_TABLE}: no class->rank rows found")
    return out


@lru_cache(maxsize=1)
def load_day_open_table(params_root: str | None = None) -> dict[tuple[str, str], tuple[int, ...]]:
    """(region, damage_level) -> (day_open_rank1 .. day_open_rank5) from T34."""
    path = Path(tables_root(params_root)) / T34_TABLE
    out: dict[tuple[str, str], tuple[int, ...]] = {}
    regions = {"high_capability", "moderate", "low_capability"}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if len(row) >= 8 and row[0].strip() in regions:
                out[(row[0].strip(), row[2].strip())] = tuple(int(v) for v in row[3:8])
    if not out:
        raise ValueError(f"{T34_TABLE}: no schedule rows found")
    return out


def assign_clearance_rank(
    links: pd.DataFrame,
    *,
    class_col: str = "faf5_class",
    from_col: str = "from_id",
    to_col: str = "to_id",
    default_isolated_rank: int = DEFAULT_ISOLATED_RANK,
) -> pd.DataFrame:
    """T33 rank per link (see module docstring). Returns a frame indexed like ``links`` with
    ``clearance_rank`` (Int64) and ``clearance_rank_source``."""
    mapping = load_class_rank_map()
    codes = pd.to_numeric(links[class_col], errors="coerce")
    known = codes.map(lambda c: c in mapping if pd.notna(c) else False)
    assigned = codes.map(lambda c: mapping.get(int(c)) if pd.notna(c) and int(c) in mapping else None)

    direct = assigned.map(lambda a: isinstance(a, int))
    topo = assigned.eq(_TOPOLOGY)
    excluded = assigned.eq(_EXCLUDE)

    rank = pd.Series(np.where(direct, assigned.where(direct, np.nan), np.nan), index=links.index, dtype="float64")
    source = pd.Series("unclassified", index=links.index, dtype=object)
    source[direct] = "direct"
    source[topo] = "topology"
    source[excluded] = "excluded"

    frm = links[from_col].astype(str).to_numpy()
    to = links[to_col].astype(str).to_numpy()
    resolved_topo = pd.Series(False, index=links.index)
    for _ in range(_MAX_HOPS):
        node_best = (
            pd.concat([pd.Series(rank.to_numpy(), index=frm), pd.Series(rank.to_numpy(), index=to)])
            .dropna()
            .groupby(level=0)
            .min()
        )
        cand = np.fmin(pd.Series(frm).map(node_best).to_numpy(dtype=float), pd.Series(to).map(node_best).to_numpy(dtype=float))
        new = topo.to_numpy() & rank.isna().to_numpy() & ~np.isnan(cand)
        if not new.any():
            break
        rank[new] = cand[new]
        resolved_topo[new] = True

    isolated = topo & rank.isna()
    if isolated.any():
        logger.warning(
            "%d topology-inherited links have no ranked neighbour; defaulting to rank %d",
            int(isolated.sum()),
            default_isolated_rank,
        )
        rank[isolated] = float(default_isolated_rank)
        source[isolated] = "isolated_default"

    return pd.DataFrame(
        {"clearance_rank": rank.round().astype("Int64"), "clearance_rank_source": source},
        index=links.index,
    )


def day_open_for(
    damage_level: pd.Series,
    clearance_rank: pd.Series,
    *,
    region: str | None = None,
) -> pd.Series:
    """T34 day_open per link. "no" damage -> 0 (never closed); no rank -> NA."""
    region = region or str(get_parameter("hazard_disruption", "winter_storm_snow_region", "moderate"))
    table = load_day_open_table()
    levels = damage_level.fillna("no").astype(str).str.lower()
    rank = pd.to_numeric(clearance_rank, errors="coerce")
    out = pd.Series(pd.NA, index=damage_level.index, dtype="Int64")
    out[levels.eq("no")] = 0
    for level in ("minor", "moderate", "extensive", "severe"):
        row = table.get((region, level))
        if row is None:
            raise KeyError(f"T34 has no schedule for region={region!r} damage_level={level!r}")
        for r in range(1, 6):
            mask = levels.eq(level) & rank.eq(r)
            out[mask] = row[r - 1]
    return out


@lru_cache(maxsize=1)
def load_speed_recovery_table(params_root: str | None = None) -> dict[int, tuple[float, float]]:
    """days_since_open -> (speed_factor_major, speed_factor_minor), from T35."""
    path = Path(tables_root(params_root)) / T35_TABLE
    table = pd.read_csv(path, comment="#")
    for col in ("days_since_open", "speed_factor_major", "speed_factor_minor"):
        if col not in table.columns:
            raise KeyError(f"{T35_TABLE} missing required column {col!r}")
    out = {
        int(row.days_since_open): (float(row.speed_factor_major), float(row.speed_factor_minor))
        for row in table.itertuples()
    }
    if not out:
        raise ValueError(f"{T35_TABLE}: no recovery rows found")
    return out


def residual_speed_factor_winter_storm(
    event_day: int | float,
    day_open: pd.Series,
    is_major: pd.Series,
    *,
    params_root: str | None = None,
) -> pd.Series:
    """Per-link capacity/speed factor on ``event_day``, from T35's post-reopening
    recovery curve (days_since_open -> speed_factor_major|minor).

    ``day_open`` (T34, via :func:`add_clearance_columns`) is the day a link's
    clearance rank becomes passable, counted from end of storm; NA (no rank,
    e.g. non-FAF5 networks) returns a factor of 1.0 (unaffected) rather than
    guessing. ``event_day < day_open`` -- the link hasn't been reached by the
    plow fleet yet -- returns 0.0 (still fully closed), matching T34's own
    "day_open" semantics (the link is impassable before that day). Beyond
    T35's last tabulated day (4, "fully recovered"), the day is clamped to 4
    (speed_factor 1.0 at both major/minor by that point) rather than
    extrapolated or re-interpolated -- T35 is a short, discrete step curve
    (0..4 days), not a continuous one like T37/T38's residual_speed_factor.

    ``is_major`` should come from the project's one canonical major/minor
    split (``resiflow.hpms_fclass.damage_threshold_major_from_fclass``,
    F1-F3 major) for consistency with flood/T20's own use of that same
    split -- T33 has no literal "road_class" column of its own despite
    T35's header comment implying one.
    """
    table = load_speed_recovery_table(params_root=params_root)
    max_day = max(table)
    day_open_num = pd.to_numeric(day_open, errors="coerce")
    days_since_open = (float(event_day) - day_open_num).clip(lower=0, upper=max_day)

    factor = pd.Series(1.0, index=day_open.index, dtype=float)
    has_rank = day_open_num.notna()
    not_yet_open = has_rank & (float(event_day) < day_open_num)
    factor[not_yet_open] = 0.0

    open_now = has_rank & ~not_yet_open
    for day, (major_factor, minor_factor) in table.items():
        mask = open_now & (days_since_open.round().astype("Int64") == day)
        factor[mask & is_major.astype(bool)] = major_factor
        factor[mask & ~is_major.astype(bool)] = minor_factor
    return factor


def peak_closure_flag(clearance_rank: pd.Series, peak_depth_mm: pd.Series) -> pd.Series:
    """Rank-5 link whose peak-day depth reached the passenger-car clearance threshold."""
    rank = pd.to_numeric(clearance_rank, errors="coerce")
    depth = pd.to_numeric(peak_depth_mm, errors="coerce")
    return (rank.eq(CLOSURE_FLAG_RANK) & (depth >= CLOSURE_FLAG_DEPTH_MM)).fillna(False).astype(bool)


def add_clearance_columns(
    links: pd.DataFrame,
    *,
    depth_col: str = "winter_storm_max_mm",
    damage_col: str = "damage_level_max",
) -> pd.DataFrame:
    """Attach rank / day_open / closure-flag columns; neutralise excluded classes.

    Without a ``faf5_class`` column (non-FAF5 networks, toy testbeds) ranks cannot be
    computed: the columns are still added (NA / False) so output schemas stay stable.
    """
    out = links.copy()
    if "faf5_class" not in out.columns:
        logger.warning("No faf5_class column: clearance_rank/day_open left NA (T33 is keyed on FAF5 Class)")
        out["clearance_rank"] = pd.array([pd.NA] * len(out), dtype="Int64")
        out["clearance_rank_source"] = "unclassified"
        out["day_open"] = pd.array([pd.NA] * len(out), dtype="Int64")
        out["winter_peak_closure_flag"] = False
        out["clearance_excluded"] = False
        return out

    ranks = assign_clearance_rank(out)
    out["clearance_rank"] = ranks["clearance_rank"]
    out["clearance_rank_source"] = ranks["clearance_rank_source"]
    out["clearance_excluded"] = ranks["clearance_rank_source"].eq("excluded")
    # Excluded links (ferry, centroid connector) never carry a damage level.
    out.loc[out["clearance_excluded"], damage_col] = "no"
    out["day_open"] = day_open_for(out[damage_col], out["clearance_rank"])
    out.loc[out["clearance_excluded"], "day_open"] = pd.NA  # no rank, no schedule
    depth = out[depth_col] if depth_col in out.columns else pd.Series(0.0, index=out.index)
    out["winter_peak_closure_flag"] = peak_closure_flag(out["clearance_rank"], depth)
    return out
