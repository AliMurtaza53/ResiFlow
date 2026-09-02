# %%
import sys
import json
import warnings
import gc
import ast
from functools import lru_cache

from pathlib import Path
from typing import Tuple, Dict
import logging

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(1, str(REPO_ROOT))

import geopandas as gpd
import pandas as pd
import numpy as np
from tqdm import tqdm
from collections import defaultdict

import resiflow.road_revised as func
import resiflow.constants as cons
from resiflow.combined_od import resolve_passenger_od_path
from resiflow.demand import (
    load_assignment_demand,
    demand_spec_from_env,
    apply_sample_od_n,
    restrict_od_to_pairs,
    sample_od_n_from_env,
    combine_freight_passenger_od,
)
from resiflow.networks import load_assignment_profiles, normalize_network_links
from resiflow.networks.assignment import map_tier_profile
from resiflow.parameters import active_overrides_path, get_parameter
from resiflow.utils import get_results_variant, load_config, get_flow_on_edges
import duckdb
import os

# %%
warnings.simplefilter("ignore")
base_path = Path(load_config()["paths"]["soge_clusters"])
tqdm.pandas()

# Optional performance controls (disabled by default)
VECTORIZE_PATH_PARSING = os.environ.get("NIRD_VECTORIZE_PATH_PARSING", "0").strip().lower() in {
    "1",
    "true",
    "yes",
}
USE_SET_BASED_FLOOD_LOOKUP = os.environ.get("NIRD_USE_SET_BASED_FLOOD_LOOKUP", "0").strip().lower() in {
    "1",
    "true",
    "yes",
}


def first_existing(paths):
    """Return first existing path from a sequence, else None."""
    for path in paths:
        p = Path(path)
        if p.exists():
            return p
    return None


def odpfc_source_exists(path: Path) -> bool:
    if path.is_file():
        return True
    if path.is_dir() and any(path.glob("*.pq")):
        return True
    return False


def load_odpfc_source(path: Path, damaged_edges: set[str]) -> pd.DataFrame:
    """Load only the OD rows whose realized path crosses a damaged edge.

    An unfiltered load (previously ``pd.read_parquet``/unfiltered
    ``read_parquet(...).fetchdf()``) works fine against a small toy baseline
    but OOMs immediately against a CONUS-scale baseline's odpfc (hundreds of
    GB) -- this baseline is typically the Pass A convergence run itself
    (``base_scenario/<results_variant>/odpfc.pq``), read here as Script 4's
    fallback when no Pass-B-specific event_candidates output exists.

    Root-cause history (2026-07-31/08-01, confirmed on Hopper): CROSS JOIN
    UNNEST(path) has to touch every edge of every one of the baseline's
    ~9.68M paths to find matches, regardless of how many edges you're
    matching against -- a hazard with 95 damaged edges ran 6+ hours without
    finishing on a from-scratch explode. Doing that explode once PER HAZARD
    EVENT (up to 4x for this project) was the real, avoidable cost -- see
    scripts/build_odpfc_edge_index.py, which does the explode exactly once
    into a persistent (e_id, od_id) index. If that index exists, use it (a
    cheap filtered lookup, no UNNEST at query time); otherwise fall back to
    the direct explode (fine for a small toy baseline, slow at CONUS scale).

    Second root-cause round (2026-08-03/04, confirmed on Hopper): even with
    the index, a hazard whose damaged-edge set is a large fraction of the
    network (winter_storm/601: 11,556 of 483K CONUS edges, 2.4%) can still
    OOM -- diagnosed by timing the two stages of this function separately.
    Stage 1 (this function's ``hit_od_ids`` build, just distinct od_id
    matches) completed in ~20 min at 8 CPU/140GB with no issue. The old
    Stage 2 (``SELECT o.* ... SEMI JOIN`` -> ``fetchdf()``) is what died: it
    pulled all 16.67M matched ROWS (not OD pairs) into one pandas
    DataFrame, each with a ``path`` list column -- ``od_id`` is assigned
    fresh per Pass-A iteration (``road_revised.py``'s
    ``next_od_id_base + ROW_NUMBER()``), so the same (origin, destination)
    pair recurs once per iteration it got rerouted through, and the
    overlay_assignment_flows() caller was already deduping down to one row
    per (origin_node, destination_node) anyway -- just AFTER paying the full
    materialization cost.

    First attempt at a fix (2026-08-04) did that same dedup in SQL, but
    against ``o.*`` directly (``QUALIFY ROW_NUMBER() OVER (PARTITION BY
    origin_node, destination_node ORDER BY od_id) = 1``) -- confirmed on
    Hopper (2026-08-05) that this STILL OOMs (120.7/121GiB used), because
    the window function has to buffer/sort every matched row, ``path``
    array included, to rank it -- reducing the final result size doesn't
    reduce the peak memory needed to compute it. Fixed by ranking on a
    NARROW projection first (just ``od_id``, ``origin_node``,
    ``destination_node`` -- Parquet's columnar layout means this never
    touches ``path`` at all, same narrow footprint as Stage 1, which was
    already proven tractable at this row count), then joining back to fetch
    full rows only for the winning (much smaller) od_id set.
    """
    conn = duckdb.connect()
    duckdb_memory_limit = os.environ.get("NIRD_DUCKDB_MEMORY_LIMIT", "24GB")
    conn.execute(f"PRAGMA memory_limit='{duckdb_memory_limit}'")
    conn.execute("PRAGMA preserve_insertion_order=false")
    duckdb_temp_dir = os.environ.get("NIRD_DUCKDB_TEMP_DIRECTORY")
    if duckdb_temp_dir:
        conn.execute(f"PRAGMA temp_directory='{duckdb_temp_dir}'")
    damaged_df = pd.DataFrame({"e_id": sorted(str(e) for e in damaged_edges)})
    conn.register("damaged_edges", damaged_df)
    if path.is_dir():
        pattern = (path / "*.pq").as_posix().replace("'", "''")
        source_sql = f"read_parquet('{pattern}')"
        logging.info("Loading filtered odpfc parts from %s", path)
    else:
        single_path = path.as_posix().replace("'", "''")
        source_sql = f"read_parquet('{single_path}')"
        logging.info("Loading filtered single odpfc parquet from %s", path)

    index_dir = path.parent / "odpfc_edge_index"
    if index_dir.is_dir() and any(index_dir.glob("part_*.pq")):
        index_pattern = (index_dir / "part_*.pq").as_posix().replace("'", "''")
        logging.info("Using prebuilt edge/od_id index at %s", index_dir)
        conn.execute(
            f"""
            CREATE TEMP TABLE hit_od_ids AS
            SELECT DISTINCT idx.od_id
            FROM read_parquet('{index_pattern}') idx
            JOIN damaged_edges d ON d.e_id = idx.e_id
            """
        )
    else:
        logging.warning(
            "No prebuilt edge/od_id index at %s -- falling back to a direct "
            "UNNEST explode, which is slow at CONUS scale (confirmed 6h+ for "
            "a 95-damaged-edge hazard). Run scripts/build_odpfc_edge_index.py "
            "once against this baseline to avoid repeating this per hazard event.",
            index_dir,
        )
        conn.execute(
            f"""
            CREATE TEMP TABLE hit_od_ids AS
            SELECT DISTINCT o.od_id
            FROM {source_sql} o
            CROSS JOIN UNNEST(o.path) AS u(e_id)
            JOIN damaged_edges d ON d.e_id = u.e_id
            """
        )
    # Narrow-then-widen: rank on just (od_id, origin_node, destination_node) --
    # NOT `o.*` -- so the window function never has to buffer every matched
    # row's `path` array to do the ranking. Confirmed on Hopper (2026-08-05)
    # that doing the QUALIFY/ROW_NUMBER dedup against `o.*` directly still
    # OOMs (120.7/121GiB used) even though the FINAL result is small, because
    # DuckDB has to materialize/sort the full-width intermediate (path arrays
    # included) to rank it before QUALIFY can discard the losers. Parquet's
    # columnar layout means a query that only ever references od_id/
    # origin_node/destination_node never touches the path column's data at
    # all, so this ranking pass has the same narrow footprint as Stage 1
    # (hit_od_ids), which already proved tractable at this row count.
    conn.execute(
        f"""
        CREATE TEMP TABLE winning_od_ids AS
        SELECT od_id FROM (
            SELECT
                o.od_id,
                ROW_NUMBER() OVER (
                    PARTITION BY o.origin_node, o.destination_node ORDER BY o.od_id
                ) AS rn
            FROM {source_sql} o
            JOIN hit_od_ids h ON h.od_id = o.od_id
        ) ranked
        WHERE rn = 1
        """
    )
    result = conn.execute(
        f"""
        SELECT o.*
        FROM {source_sql} o
        JOIN winning_od_ids w ON w.od_id = o.od_id
        """
    ).fetchdf()
    conn.unregister("damaged_edges")
    conn.close()
    logging.info(
        "Filtered odpfc source produced %s candidate rows (of a much larger baseline).",
        len(result),
    )
    return result


def overlay_assignment_flows(
    disrupted_candidates: pd.DataFrame,
    assignment_od: pd.DataFrame,
) -> pd.DataFrame:
    """Overlay raw assignment demand onto one disrupted candidate row per OD pair."""
    demand = assignment_od.copy()
    for col in ("origin_node", "destination_node"):
        if col not in demand.columns:
            raise ValueError(f"Assignment OD missing {col}")
        demand[col] = demand[col].astype(str)
    flow_col = "Car21" if "Car21" in demand.columns else "flow"
    demand = demand.groupby(["origin_node", "destination_node"], as_index=False)[flow_col].sum()
    demand = demand[demand[flow_col] > 0]

    candidates = disrupted_candidates.copy()
    if "origin_node" not in candidates.columns or "destination_node" not in candidates.columns:
        raise ValueError(
            "disrupted_candidates must include origin_node and destination_node for demand overlay"
        )
    candidates["origin_node"] = candidates["origin_node"].astype(str)
    candidates["destination_node"] = candidates["destination_node"].astype(str)
    candidates = candidates.drop_duplicates(
        subset=["origin_node", "destination_node"],
        keep="first",
    )

    merged = candidates.merge(
        demand,
        on=["origin_node", "destination_node"],
        how="inner",
    )
    merged["flow"] = pd.to_numeric(merged[flow_col], errors="coerce").fillna(0.0)
    if flow_col != "flow" and flow_col in merged.columns:
        merged = merged.drop(columns=[flow_col])
    return merged.reset_index(drop=True)


def overlay_passenger_flows(
    disrupted_candidates: pd.DataFrame,
    passenger_od: pd.DataFrame,
) -> pd.DataFrame:
    """Restrict disrupted path candidates to passenger OD pairs and use passenger demand."""
    return overlay_assignment_flows(disrupted_candidates, passenger_od)


def overlay_combined_flows(
    disrupted_candidates: pd.DataFrame,
    freight_od: pd.DataFrame,
    passenger_od: pd.DataFrame,
) -> pd.DataFrame:
    """Overlay freight+passenger demand as one combined, capacity-competing flow.

    Freight and passenger vehicles physically share the same road capacity.
    Routing them as two independent ``network_flow_model`` solves (the
    previous per-mode loop -- see git history) let each mode see the *full*
    remaining post-disruption capacity as if the other mode's disrupted flow
    didn't exist, so both could independently fill the same detour link up
    to its capacity -- double-counting one physical capacity pool as two.
    Combining into a single ``Car21`` total (mirroring how Pass A/Script 1
    already combines demand via ``combine_freight_passenger_od``) fixes that
    for the one thing that matters physically: how much total vehicle flow
    competes for a link. ``freight_flow``/``passenger_flow`` are kept per OD
    pair so results can still be split back out by mode afterwards.

    That post-hoc split is a per-OD-pair *known-composition* allocation
    (exact for isolation, which is reported per OD pair; a flow-share
    proportion for rerouting cost and edge flow, which the solver only
    returns as network-wide aggregates) -- not a full per-path trace of
    which mode's vehicles used which edge. Getting the latter would require
    re-enabling per-path (``odpfc``) output inside this recovery loop, which
    is deliberately skipped here for performance at CONUS scale (see
    ``NIRD_ODPFC_OUTPUT_MODE=skip`` below).

    Access restrictions (a corridor open to cars but closed to trucks) would
    break the "equal, shared access" assumption this relies on. Not modeled:
    the current network has no such link attribute, and isn't dense enough
    for one to be meaningful yet.
    """
    combined_demand = combine_freight_passenger_od(freight_od, passenger_od)

    candidates = disrupted_candidates.copy()
    if "origin_node" not in candidates.columns or "destination_node" not in candidates.columns:
        raise ValueError(
            "disrupted_candidates must include origin_node and destination_node for demand overlay"
        )
    candidates["origin_node"] = candidates["origin_node"].astype(str)
    candidates["destination_node"] = candidates["destination_node"].astype(str)
    candidates = candidates.drop_duplicates(
        subset=["origin_node", "destination_node"],
        keep="first",
    )

    merged = candidates.merge(
        combined_demand,
        on=["origin_node", "destination_node"],
        how="inner",
    )
    merged["freight_flow"] = pd.to_numeric(merged["freight_flow"], errors="coerce").fillna(0.0)
    merged["passenger_flow"] = pd.to_numeric(merged["passenger_flow"], errors="coerce").fillna(0.0)
    merged["flow"] = pd.to_numeric(merged["Car21"], errors="coerce").fillna(0.0)
    merged = merged.drop(columns=["Car21"])
    return merged.reset_index(drop=True)


def safe_event_id(value) -> str:
    text = str(value).strip() if value is not None else "event_000001"
    if not text:
        text = "event_000001"
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)


def event_candidate_source_exists(event_dir: Path) -> bool:
    combined = event_dir / "disrupted_candidates.pq"
    parts = event_dir / "parts"
    return combined.exists() or (parts.is_dir() and any(parts.glob("*.pq")))


def load_event_disrupted_candidates(base_output_dir: Path, event_id: str) -> pd.DataFrame:
    """Load Patch 4 prefiltered disrupted candidates for one event."""
    event_dir = base_output_dir / "event_disrupted_candidates" / safe_event_id(event_id)
    combined = event_dir / "disrupted_candidates.pq"
    parts = event_dir / "parts"
    if combined.exists():
        logging.info("Loading event disrupted candidates from %s", combined)
        candidates = pd.read_parquet(combined)
    elif parts.is_dir() and any(parts.glob("*.pq")):
        pattern = (parts / "*.pq").as_posix().replace("'", "''")
        logging.info("Loading event disrupted candidate parts from %s", parts)
        candidates = duckdb.connect().execute(
            f"SELECT * FROM read_parquet('{pattern}')"
        ).fetchdf()
    else:
        raise FileNotFoundError(
            f"Missing event disrupted candidates for event_id={event_id} under {event_dir}"
        )
    logging.info(
        "Script 4 event-candidate loader produced %s candidate rows for event_id=%s.",
        len(candidates),
        event_id,
    )
    return candidates


def load_path_index_disrupted_candidates(
    base_output_dir: Path,
    damaged_edges: set[str],
) -> pd.DataFrame:
    """Load disrupted candidates from baseline path-index artifacts."""
    meta_path = base_output_dir / "baseline_od_meta.pq"
    index_dir = base_output_dir / "baseline_path_index_parts"
    edge_lookup_path = base_output_dir / "edge_lookup.pq"
    if not meta_path.exists() or not index_dir.exists() or not edge_lookup_path.exists():
        raise FileNotFoundError(
            "Missing path-index artifacts. Expected baseline_od_meta.pq, "
            "baseline_path_index_parts/, and edge_lookup.pq under "
            f"{base_output_dir}"
        )
    con = duckdb.connect()
    damaged_df = pd.DataFrame({"e_id": sorted(str(e) for e in damaged_edges)})
    con.register("damaged_edges", damaged_df)
    index_pattern = (index_dir / "*.pq").as_posix().replace("'", "''")
    meta_sql = meta_path.as_posix().replace("'", "''")
    lookup_sql = edge_lookup_path.as_posix().replace("'", "''")
    damaged_edge_count = len(damaged_df)
    damaged_idx_count = con.execute(
        f"""
        SELECT COUNT(*)
        FROM read_parquet('{lookup_sql}') e
        JOIN damaged_edges d USING (e_id)
        """
    ).fetchone()[0]
    logging.info(
        "Script 4 path_index loader: damaged_edges=%s, damaged_edge_idx=%s",
        damaged_edge_count,
        damaged_idx_count,
    )
    disrupted_candidates = con.execute(
        f"""
        WITH damaged_idx AS (
            SELECT edge_idx, e_id
            FROM read_parquet('{lookup_sql}') e
            JOIN damaged_edges d USING (e_id)
        ),
        hits AS (
            SELECT
                p.od_id,
                LIST(d.e_id ORDER BY p.path_pos) AS flood_links
            FROM read_parquet('{index_pattern}') p
            JOIN damaged_idx d USING (edge_idx)
            GROUP BY p.od_id
        ),
        affected_paths AS (
            SELECT
                p.od_id,
                LIST(e.e_id ORDER BY p.path_pos) AS path
            FROM read_parquet('{index_pattern}') p
            JOIN hits h USING (od_id)
            JOIN read_parquet('{lookup_sql}') e USING (edge_idx)
            GROUP BY p.od_id
        )
        SELECT
            m.*,
            ap.path,
            h.flood_links
        FROM read_parquet('{meta_sql}') m
        JOIN hits h USING (od_id)
        JOIN affected_paths ap USING (od_id)
        """
    ).fetchdf()
    con.unregister("damaged_edges")
    con.close()
    logging.info(
        "Script 4 path_index loader produced %s disrupted candidates; "
        "full path reconstruction performed for affected ODs only.",
        len(disrupted_candidates),
    )
    return disrupted_candidates


def to_edge_id_list(value):
    """Convert path-like values from parquet into a normalized list of edge-id strings."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []

    # already list-like
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v is not None and str(v) != "nan"]

    # numpy array from parquet/object coercion
    if isinstance(value, np.ndarray):
        vals = value.tolist()
        # Handle character-array encodings of a stringified list
        if vals and all(isinstance(v, str) and len(v) == 1 for v in vals):
            joined = "".join(vals)
            if joined.startswith("[") and joined.endswith("]"):
                try:
                    parsed = ast.literal_eval(joined)
                    return [str(v) for v in parsed if v is not None and str(v) != "nan"]
                except Exception:
                    pass
        if value.dtype.kind in {"U", "S"}:
            joined = "".join(vals)
            if joined.startswith("[") and joined.endswith("]"):
                try:
                    parsed = ast.literal_eval(joined)
                    return [str(v) for v in parsed if v is not None and str(v) != "nan"]
                except Exception:
                    return [str(v) for v in vals if v not in {"[", "]", ",", " "}]
        return [str(v) for v in vals if v is not None and str(v) != "nan"]

    # stringified list
    if isinstance(value, str):
        return list(_parse_edge_id_string_cached(value))

    return [str(value)]


@lru_cache(maxsize=200_000)
def _parse_edge_id_string_cached(raw: str) -> tuple:
    """Parse string path payloads with caching (helps repeated OD path strings)."""
    s = str(raw).strip()
    if not s or s == "nan":
        return tuple()
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, np.ndarray):
                parsed = parsed.tolist()
            if isinstance(parsed, (list, tuple, set)):
                return tuple(str(v) for v in parsed if v is not None and str(v) != "nan")
        except Exception:
            pass
    return tuple(tok.strip() for tok in s.split(",") if tok.strip())


def to_edge_id_list_vectorized(series: pd.Series) -> pd.Series:
    """Batch parse Series values; caches repeated string payloads."""
    if series.empty:
        return series

    out = pd.Series(index=series.index, dtype=object)
    str_mask = series.map(lambda v: isinstance(v, str))

    if str_mask.any():
        str_values = series[str_mask]
        unique_vals = pd.unique(str_values)
        parsed_map = {val: list(_parse_edge_id_string_cached(val)) for val in unique_vals}
        out.loc[str_mask] = str_values.map(parsed_map)

    if (~str_mask).any():
        out.loc[~str_mask] = series[~str_mask].apply(to_edge_id_list)

    return out


# %%
def bridge_recovery(
    day: int,
    damage_level: str,
    pre_event_capacity: float,
    acc_capacity: float,
    bridge_recovery_dict: Dict,
) -> float:
    if damage_level != "no":  # minor, moderate, extensive, severe
        recovery_rate = bridge_recovery_dict.get(damage_level, [])[day]
        acc_capacity = pre_event_capacity * recovery_rate
    return acc_capacity


def ordinary_road_recovery(
    day: int,
    damage_level: str,
    pre_event_capacity: float,
    acc_capacity: float,
    road_recovery_dict: Dict,
) -> float:
    if damage_level != "no":  # minor, moderate, extensive, severe
        recovery_rate = road_recovery_dict.get(damage_level, [])[day]
        acc_capacity = pre_event_capacity * recovery_rate
    return acc_capacity


def load_scenarios(base_path: Path) -> Tuple[Dict, Dict]:
    """Load recovery rates for bridges and ordinary roads.

    Default: the data bundle's ``tables/recovery design_updated.csv`` (current
    behavior). With ``recovery.use_table_recovery_design`` enabled, the
    day-by-day rates are derived instead from the step-wise T26 design table
    in ``parameters/tables`` for the scenario named by
    ``recovery.table_recovery_scenario`` (fast/average/slow); T26 does not
    distinguish bridges from ordinary roads, so both dicts share the schedule.
    """
    if get_parameter("recovery", "use_table_recovery_design", False):
        from resiflow.tables import recovery_schedule_from_table

        recovery_dict, event_days = recovery_schedule_from_table(
            get_parameter(
                "recovery", "recovery_design_table", "T26_recovery_design_current"
            ),
            str(get_parameter("recovery", "table_recovery_scenario", "average")),
        )
        bridge_recovery_dict = defaultdict(list, {k: list(v) for k, v in recovery_dict.items()})
        road_recovery_dict = defaultdict(list, {k: list(v) for k, v in recovery_dict.items()})
        scenarios = [1] * len(event_days)  # matches the bundle's scenario=1 reuse
        return (bridge_recovery_dict, road_recovery_dict, scenarios, event_days)

    scenario_path = base_path / "tables" / "recovery design_updated.csv"
    if not scenario_path.exists():
        raise FileNotFoundError(
            "Could not find recovery design_updated.csv in the tables directory"
        )
    df = pd.read_csv(scenario_path)

    bridge_recovery_dict = defaultdict(list)
    road_recovery_dict = defaultdict(list)
    scenarios = []
    conditions = []
    for _, row in df.iterrows():
        bridge_recovery_dict["minor"].append(row["bridge_minor"])
        bridge_recovery_dict["moderate"].append(row["bridge_moderate"])
        bridge_recovery_dict["extensive"].append(row["bridge_extensive"])
        bridge_recovery_dict["severe"].append(row["bridge_severe"])
        road_recovery_dict["minor"].append(row["road_minor"])
        road_recovery_dict["moderate"].append(row["road_moderate"])
        road_recovery_dict["extensive"].append(row["road_extensive"])
        road_recovery_dict["severe"].append(row["road_severe"])
        scenarios.append(int(row["scenario"]))
        conditions.append(int(row["event_day"]))

    return (bridge_recovery_dict, road_recovery_dict, scenarios, conditions)


def load_event_damage_from_script3(
    base_path: Path,
    scenario_param: int | str,
    event_key: int | str,
) -> Tuple[pd.DataFrame, float]:
    """Load script-3 event damage CSV and aggregate per-edge damage level.

    Returns
    -------
    Tuple[pd.DataFrame, float]
        - DataFrame with columns ["e_id", "damage_level_max", "road_label"]
        - total direct damage (sum of all *_damage_value_mean columns)
    """
    variant = get_results_variant()
    event_stem = f"intersections_{event_key}"
    damage_csv = (
        base_path.parent
        / "results"
        / "damage_analysis"
        / variant
        / str(scenario_param)
        / f"{event_stem}_with_damage_values.csv"
    )
    legacy_damage_csv = (
        base_path.parent
        / "results"
        / "damage_analysis"
        / variant
        / f"{event_stem}_with_damage_values.csv"
    )
    if not damage_csv.exists():
        damage_csv = legacy_damage_csv
    if not damage_csv.exists():
        logging.warning(
            "Script-3 damage output not found for scenario=%s event=%s: %s",
            scenario_param,
            event_key,
            damage_csv,
        )
        return pd.DataFrame(columns=["e_id", "damage_level_max", "road_label"]), 0.0

    damage_df = pd.read_csv(damage_csv, low_memory=False)
    if damage_df.empty:
        return pd.DataFrame(columns=["e_id", "damage_level_max", "road_label"]), 0.0

    from resiflow.damage_aggregation import total_direct_damage_musd

    direct_damage_total_musd = total_direct_damage_musd(damage_df)
    direct_damage_total = direct_damage_total_musd * 1_000_000.0

    # aggregate event damage levels to a per-edge max
    level_map = {"no": 0, "minor": 1, "moderate": 2, "extensive": 3, "severe": 4}
    level_rev = {v: k for k, v in level_map.items()}

    for col in ["damage_level_surface", "damage_level_river"]:
        if col not in damage_df.columns:
            damage_df[col] = "no"
        # tolerate mixed str/int in CSV by coercing robustly
        as_num = pd.to_numeric(damage_df[col], errors="coerce")
        as_str_num = damage_df[col].astype(str).str.lower().map(level_map)
        damage_df[col] = as_num.fillna(as_str_num).fillna(0).astype(int)

    if "road_label" not in damage_df.columns:
        damage_df["road_label"] = "road"
    damage_df["road_label"] = damage_df["road_label"].astype(str).str.lower()
    damage_df.loc[~damage_df["road_label"].isin(["road", "bridge", "tunnel"]), "road_label"] = "road"

    damage_by_edge = (
        damage_df.assign(damage_level_max_num=damage_df[["damage_level_surface", "damage_level_river"]].max(axis=1))
        .groupby("e_id", as_index=False)
        .agg(
            {
                "damage_level_max_num": "max",
                "road_label": "first",
            }
        )
    )
    damage_by_edge["e_id"] = damage_by_edge["e_id"].astype(str)
    damage_by_edge["damage_level_max"] = damage_by_edge["damage_level_max_num"].map(level_rev)
    damage_by_edge = damage_by_edge[["e_id", "damage_level_max", "road_label"]]

    logging.info(
        "Loaded script-3 damages for scenario=%s event=%s: edges=%s, direct_damage_total=%.2f",
        scenario_param,
        event_key,
        len(damage_by_edge),
        direct_damage_total,
    )
    return damage_by_edge, direct_damage_total


RESUME_SKIP_COMPLETED_DAYS = os.environ.get(
    "RESIFLOW_RESUME_SKIP_COMPLETED_DAYS",
    os.environ.get("NIRD_RESUME_SKIP_COMPLETED_DAYS", "0"),
).strip().lower() in {"1", "true", "yes"}


def load_completed_day_cost_row(out_path: Path, out_mode: str, scenario_id, event_day) -> dict | None:
    """Reconstruct one day's final-aggregate cost row from its per-day artifacts.

    Used by the resume path (``RESIFLOW_RESUME_SKIP_COMPLETED_DAYS=1``) to
    skip re-running a recovery day that already completed before a prior
    invocation was killed (e.g. a SLURM time-limit kill) and is now being
    resubmitted. Each day already writes ``rerouting_cost_{out_mode}_s
    {scenario}_day{day}.csv`` and ``trip_isolations_{out_mode}_s{scenario}_
    day{day}.csv`` to disk as it completes (see the day loop below), but two
    fields (``isolation_flow``, ``isolation_cost_usd``) are only ever added
    to the IN-MEMORY row after the per-day cost CSV is written, so they're
    absent from that CSV -- recompute them here from the isolations file
    (``sum(Car21)`` / ``sum(isolation_cost_usd)``) so a resumed run's final
    ``cost_matrix_*_by_scenario.csv`` matches what an uninterrupted run would
    have produced. Days are independent of each other (each resets from the
    same fixed pre-event capacity, scaled only by that day's own recovery
    rate), so skipping a completed day changes nothing about correctness.
    """
    cost_csv = out_path / f"rerouting_cost_{out_mode}_s{scenario_id}_day{event_day}.csv"
    iso_csv = out_path / f"trip_isolations_{out_mode}_s{scenario_id}_day{event_day}.csv"
    if not cost_csv.exists() or not iso_csv.exists():
        return None
    cost_df = pd.read_csv(cost_csv)
    if cost_df.empty:
        return None
    row = cost_df.iloc[-1].to_dict()
    iso_df = pd.read_csv(iso_csv)
    row["isolation_flow"] = float(
        pd.to_numeric(iso_df.get("Car21", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()
    )
    row["isolation_cost_usd"] = float(
        pd.to_numeric(iso_df.get("isolation_cost_usd", pd.Series(dtype=float)), errors="coerce")
        .fillna(0.0)
        .sum()
    )
    return row


def main(
    depth_key,
    flood_key,
    num_of_chunk,
    num_of_cpu,
):
    logging.info("Start...")
    db_path = base_path / "dbs" / f"recovery_{depth_key}_{flood_key}.duckdb"
    recovery_db_override = os.environ.get("NIRD_RECOVERY_DB_PATH", "").strip()
    if recovery_db_override:
        db_path = Path(recovery_db_override)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    logging.info(f"Database path is: {db_path}")

    params_root = first_existing(
        [
            base_path / "parameters",
            base_path / "inputs" / "parameters",
        ]
    )
    if params_root is None:
        raise FileNotFoundError(
            "Could not find parameter folder. Checked base_path/parameters and base_path/inputs/parameters"
        )
    profiles = load_assignment_profiles(params_root)
    flow_breakpoint_dict = profiles["flow_breakpoint"]

    # Load recovery scenarios
    (
        bridge_recovery_dict,
        road_recovery_dict,
        scenarios,  # list of scenarios
        conditions,  # condition == 1: day 0, otherwise: day > 0
    ) = load_scenarios(base_path)

    # Locate pre-identified odpfc or base-scenario path-index artifacts.
    results_variant = get_results_variant()
    odpfc_path = (
        base_path.parent
        / "results"
        / "disruption_analysis"
        / results_variant
        / "od"
        / f"odpfc_{depth_key}_{flood_key}.pq"
    )
    odpfc_parts_path = odpfc_path.parent / "odpfc_parts"
    candidate_source_mode = "legacy_odpfc"
    candidate_source_path = odpfc_path
    event_id_candidates = [
        safe_event_id(f"{depth_key}_{flood_key}"),
        safe_event_id(flood_key),
    ]
    if not odpfc_path.exists() and odpfc_source_exists(odpfc_parts_path):
        candidate_source_path = odpfc_parts_path
    if not odpfc_source_exists(candidate_source_path):
        logging.warning(
            f"Missing odpfc at {candidate_source_path}. Falling back to base scenario artifacts."
        )
        base_odpfc_path = (
            base_path.parent / "results" / "base_scenario" / results_variant / "odpfc.pq"
        )
        base_odpfc_parts = (
            base_path.parent
            / "results"
            / "base_scenario"
            / results_variant
            / "odpfc_parts"
        )
        base_path_index_dir = (
            base_path.parent / "results" / "base_scenario" / results_variant
        )
        base_event_candidates_dir = base_path_index_dir
        selected_event_id = None
        for event_id in event_id_candidates:
            if event_candidate_source_exists(
                base_event_candidates_dir / "event_disrupted_candidates" / event_id
            ):
                selected_event_id = event_id
                break
        if selected_event_id is not None:
            candidate_source_mode = "event_candidates"
            candidate_source_path = base_event_candidates_dir
            candidate_source_event_id = selected_event_id
        elif odpfc_source_exists(base_odpfc_path):
            candidate_source_path = base_odpfc_path
        elif odpfc_source_exists(base_odpfc_parts):
            candidate_source_path = base_odpfc_parts
        elif (
            (base_path_index_dir / "baseline_od_meta.pq").exists()
            and (base_path_index_dir / "baseline_path_index_parts").exists()
            and (base_path_index_dir / "edge_lookup.pq").exists()
        ):
            candidate_source_mode = "path_index"
            candidate_source_path = base_path_index_dir
        else:
            logging.error(
                "Base scenario path artifacts missing. Checked %s, %s, and %s",
                base_odpfc_path,
                base_odpfc_parts,
                base_path_index_dir,
            )
            sys.exit(1)
    if candidate_source_mode != "event_candidates":
        candidate_source_event_id = None

    logging.info(
        "Script 4 candidate loader selected mode=%s source=%s event_id=%s",
        candidate_source_mode,
        candidate_source_path,
        candidate_source_event_id,
    )
    # Load road links with damage (e.g., flood depth and damage level)
    road_links = gpd.read_parquet(
        base_path.parent
        / "results"
        / "disruption_analysis"
        / results_variant
        / str(depth_key)
        / "links"
        / f"road_links_{flood_key}.gpq"
    )
    road_links["e_id"] = road_links["e_id"].astype(str)
    if "assignment_tier" not in road_links.columns:
        road_links = normalize_network_links(road_links, params_root=str(params_root))

    # Wire to script-3 outputs (direct damage table by event)
    damage_by_edge, direct_damage_total = load_event_damage_from_script3(
        base_path, depth_key, flood_key
    )
    direct_damage_total_musd = direct_damage_total / 1_000_000.0
    if len(damage_by_edge) > 0:
        if "damage_level_max" in road_links.columns:
            road_links = road_links.drop(columns=["damage_level_max"])
        road_links = road_links.merge(damage_by_edge, on="e_id", how="left")
        road_links["damage_level_max"] = road_links["damage_level_max"].fillna("no")

        # Prefer road_label from script 3 if present
        if "road_label_x" in road_links.columns and "road_label_y" in road_links.columns:
            road_links["road_label"] = road_links["road_label_y"].fillna(road_links["road_label_x"])
            road_links = road_links.drop(columns=["road_label_x", "road_label_y"])

    # FAF data does not include road_label; create a default
    if "road_label" not in road_links.columns:
        road_links["road_label"] = "road"
        if "road_bridge" in road_links.columns:
            road_links.loc[road_links["road_bridge"].astype(str).str.lower() == "yes", "road_label"] = "bridge"
    road_links["breakpoint_flows"] = map_tier_profile(road_links, flow_breakpoint_dict)
    # SA seam: same breakpoint-flow scale as edge_initial_speed_func (Script 1),
    # so the factor moves both assignment passes coherently. Default 1.0.
    _breakpoint_scale = float(get_parameter("assignment", "breakpoint_scale", 1.0))
    if _breakpoint_scale != 1.0:
        road_links["breakpoint_flows"] = (
            pd.to_numeric(road_links["breakpoint_flows"], errors="coerce")
            * _breakpoint_scale
        )
    initial_road_links_cols = road_links.columns
    flooded_edges = set(
        road_links.loc[road_links["damage_level_max"] != "no", "e_id"].astype(str)
    )
    if candidate_source_mode == "path_index":
        disrupted_candidates = load_path_index_disrupted_candidates(
            Path(candidate_source_path),
            flooded_edges,
        )
    elif candidate_source_mode == "event_candidates":
        disrupted_candidates = load_event_disrupted_candidates(
            Path(candidate_source_path),
            candidate_source_event_id,
        )
        if "path" in disrupted_candidates.columns:
            disrupted_candidates["path"] = to_edge_id_list_vectorized(
                disrupted_candidates["path"]
            )
        if "flood_links" in disrupted_candidates.columns:
            disrupted_candidates["flood_links"] = to_edge_id_list_vectorized(
                disrupted_candidates["flood_links"]
            )
        if "od_id" not in disrupted_candidates.columns:
            disrupted_candidates["od_id"] = disrupted_candidates.index
    else:
        disrupted_candidates = load_odpfc_source(Path(candidate_source_path), flooded_edges)
        if "path" in disrupted_candidates.columns:
            if VECTORIZE_PATH_PARSING:
                disrupted_candidates["path"] = to_edge_id_list_vectorized(
                    disrupted_candidates["path"]
                )
            else:
                disrupted_candidates["path"] = disrupted_candidates["path"].apply(
                    to_edge_id_list
                )
        if "flood_links" in disrupted_candidates.columns:
            if VECTORIZE_PATH_PARSING:
                disrupted_candidates["flood_links"] = to_edge_id_list_vectorized(
                    disrupted_candidates["flood_links"]
                )
            else:
                disrupted_candidates["flood_links"] = disrupted_candidates[
                    "flood_links"
                ].apply(to_edge_id_list)
        if "od_id" not in disrupted_candidates.columns:
            disrupted_candidates["od_id"] = disrupted_candidates.index
        logging.info(
            "Script 4 legacy odpfc loader produced %s candidate rows.",
            len(disrupted_candidates),
        )

    # Build flood_links if missing (FAF pipeline uses base scenario odpfc)
    if "flood_links" not in disrupted_candidates.columns:
        if "path" not in disrupted_candidates.columns:
            logging.error("odpfc is missing 'path' column; cannot derive flood_links.")
            sys.exit(1)
        if USE_SET_BASED_FLOOD_LOOKUP:
            # Use set-based filtering (already optimized; flag available for future improvements)
            disrupted_candidates["flood_links"] = disrupted_candidates["path"].apply(
                lambda p: [e for e in p if e in flooded_edges]
            )
        else:
            disrupted_candidates["flood_links"] = disrupted_candidates["path"].apply(
                lambda p: [e for e in p if e in flooded_edges]
            )
        disrupted_candidates = disrupted_candidates[
            disrupted_candidates["flood_links"].map(len) > 0
        ].reset_index(drop=True)

    base_disrupted_candidates = disrupted_candidates.copy()
    demand_result = load_assignment_demand(base_path, demand_spec_from_env(base_path))
    passenger_od_df = demand_result.passenger_od
    freight_od_df = demand_result.freight_od
    sample_od_n = sample_od_n_from_env()
    if sample_od_n > 0 and demand_result.assignment_od is not None:
        sampled_pairs = apply_sample_od_n(demand_result.assignment_od.copy(), sample_od_n)[
            ["origin_node", "destination_node"]
        ]
        freight_od_df = restrict_od_to_pairs(freight_od_df, sampled_pairs)
        passenger_od_df = restrict_od_to_pairs(passenger_od_df, sampled_pairs)
        logging.info(
            "Smoke OD cap=%s: restricted overlay demand to %s freight rows and %s passenger rows",
            sample_od_n,
            0 if freight_od_df is None else len(freight_od_df),
            0 if passenger_od_df is None else len(passenger_od_df),
        )
    if passenger_od_df is not None:
        logging.info("Loaded passenger assignment OD (%s rows)", len(passenger_od_df))
    if freight_od_df is not None:
        logging.info("Loaded freight assignment OD (%s rows)", len(freight_od_df))
    elif demand_result.assignment_od is not None:
        freight_od_df = demand_result.assignment_od
        logging.info(
            "Using combined assignment OD as freight overlay (%s rows)",
            len(freight_od_df),
        )

    if freight_od_df is not None:
        freight_candidates = overlay_assignment_flows(base_disrupted_candidates, freight_od_df)
    else:
        freight_candidates = base_disrupted_candidates.copy()

    passenger_reroute_enabled = os.environ.get(
        "RESIFLOW_ENABLE_PASSENGER_REROUTING",
        os.environ.get("NIRD_ENABLE_PASSENGER_REROUTING", "0"),
    ).strip().lower() in {
        "1",
        "true",
        "yes",
    }
    # Freight and passenger vehicles physically share the same road capacity,
    # so when both are requested they're routed as ONE combined mode (single
    # network_flow_model solve per recovery day) and split back out by mode
    # afterwards -- see overlay_combined_flows() for why two independent
    # per-mode solves double-count shared capacity, and what is/isn't exact
    # about the post-hoc split.
    if passenger_reroute_enabled and passenger_od_df is not None and freight_od_df is not None:
        combined_candidates = overlay_combined_flows(
            base_disrupted_candidates, freight_od_df, passenger_od_df
        )
        reroute_modes: list[tuple[str, pd.DataFrame]] = [("combined", combined_candidates)]
    else:
        if passenger_reroute_enabled:
            logging.warning(
                "Passenger rerouting enabled but freight or passenger OD not found; "
                "falling back to freight-only."
            )
        reroute_modes = [("freight", freight_candidates)]

    out_path = (
        base_path.parent
        / "results"
        / "rerouting_analysis"
        / results_variant
        / str(depth_key)
        / str(flood_key)
    )
    out_path.mkdir(parents=True, exist_ok=True)

    if active_overrides_path() is not None:
        logging.info("Parameter overrides in force: %s", active_overrides_path())

    # Recovery reruns only need edge flows and cost totals, not path-index artifacts.
    os.environ["NIRD_BASELINE_PATH_OUTPUT_MODE"] = "none"
    os.environ["NIRD_ODPFC_OUTPUT_MODE"] = "skip"
    os.environ["NIRD_CREATE_FULL_TEMP_FLOW_MATRIX"] = "0"

    for mode_name, mode_disrupted_candidates in reroute_modes:
        logging.info(
            "Script 4 rerouting mode=%s with %s disrupted candidates",
            mode_name,
            len(mode_disrupted_candidates),
        )
        if mode_disrupted_candidates.empty:
            logging.info("No disrupted candidates for mode=%s; skipping.", mode_name)
            continue

        # Recovery analysis loop
        # Keyed by recovery day: the recovery design table reuses scenario=1 for every
        # event_day, so we must NOT key results by scenario_id (that collapses all days
        # into one overwritten row, leaving only the fully-recovered final day).
        # A "combined" solve still reports out as separate freight/passenger cost
        # rows (see overlay_combined_flows docstring for how that split works).
        output_modes = ("freight", "passenger") if mode_name == "combined" else (mode_name,)
        cost_rows_by_output: Dict[str, list] = {m: [] for m in output_modes}

        # Load link recovery scenarios (both capacity and speed)
        for day_idx, (scenario_id, event_day) in enumerate(zip(scenarios, conditions)):
            if RESUME_SKIP_COMPLETED_DAYS:
                completed_rows = {
                    m: load_completed_day_cost_row(out_path, m, scenario_id, event_day)
                    for m in output_modes
                }
                if all(row is not None for row in completed_rows.values()):
                    logging.info(
                        "Resume: scenario=%s day=%s already completed for mode(s)=%s -- "
                        "reusing saved results instead of recomputing.",
                        scenario_id,
                        event_day,
                        list(output_modes),
                    )
                    for out_mode, row in completed_rows.items():
                        cost_rows_by_output[out_mode].append(row)
                    continue

            logging.info(f"Rerouting Analysis on Scenario-{scenario_id} of recovery...")
            logging.info(f"Updating edge capacities on D-{event_day} of recovery...")
            road_links["acc_capacity"] = road_links["current_capacity"]
            road_links["acc_capacity"] = road_links.apply(
                lambda row: (
                    bridge_recovery(
                        day_idx,
                        row["damage_level_max"],
                        row["current_capacity"],
                        row["acc_capacity"],
                        bridge_recovery_dict,
                    )
                    if row["road_label"] == "bridge"
                    else (
                        ordinary_road_recovery(
                            day_idx,
                            row["damage_level_max"],
                            row["current_capacity"],
                            row["acc_capacity"],
                            road_recovery_dict,
                        )
                    )
                ),
                axis=1,
            )
            # Extract disrupted od after road recovery
            logging.info("Extracting disrupted OD pairs...")
            disrupted_od = mode_disrupted_candidates.copy()

            # conduct exploded chunks
            total_disrupted = len(disrupted_od)
            if total_disrupted == 0:
                logging.info("No flooded od pairs detected for current scenario.")
                continue

            max_chunk_size = 10_000
            if max_chunk_size > total_disrupted:
                chunk_size = total_disrupted
            else:
                n_chunk = min(100, max(1, total_disrupted // max_chunk_size))
                chunk_size = max(1, total_disrupted // n_chunk)
            logging.info(f"disrupted_od size: {total_disrupted}")
            logging.info(f"chunk_size: {chunk_size}")

            # create Duckdb to store mid-outputs
            conn = duckdb.connect(db_path)
            # mirrors road_revised.network_flow_model's PRAGMA threads fix
            conn.execute(f"PRAGMA threads={max(1, int(num_of_cpu))}")
            conn.execute("DROP TABLE IF EXISTS od_results")  # reset table
            conn.execute("DROP TABLE IF EXISTS edge_flows")  # reset table
            first = True
            for start in tqdm(
                range(0, total_disrupted, chunk_size),
                desc="Processing chunks",
                unit="chunk",
            ):
                chunk = disrupted_od.iloc[start : start + chunk_size].copy()
                chunk = chunk.explode("flood_links")  # list of e_id
                if chunk.empty:
                    continue
                link_cols = ["e_id", "acc_capacity"]
                if "max_speed" in road_links.columns:
                    link_cols.append("max_speed")
                chunk = chunk.merge(
                    road_links[link_cols],
                    how="left",
                    left_on="flood_links",
                    right_on="e_id",
                )
                if "max_speed" in chunk.columns:
                    closed = pd.to_numeric(chunk["max_speed"], errors="coerce").fillna(999) <= 0
                    chunk.loc[closed, "acc_capacity"] = 0
                od_df = chunk.groupby(by=["od_id"])["acc_capacity"].min().reset_index()
                if first:
                    conn.register("od_df", od_df)
                    conn.execute("CREATE TABLE od_results AS SELECT * FROM od_df")
                    first = False
                else:
                    conn.append("od_results", od_df)
                del chunk, od_df
                gc.collect()

            logging.info("Aggregating final results...")
            # to retrieve min edge capacity for each od
            min_capacity = conn.execute(
                """
                SELECT od_id, MIN(acc_capacity) AS acc_capacity
                FROM od_results
                GROUP BY od_id
            """
            ).df()
            conn.close()
            logging.info("Completing chunk process...")

            # calculate disrupted flow
            disrupted_od = disrupted_od.merge(min_capacity, how="left", on="od_id")
            disrupted_od["disrupted_flow"] = (
                disrupted_od["flow"] - disrupted_od["acc_capacity"]
            ).clip(lower=0)
            disrupted_od = disrupted_od[disrupted_od["disrupted_flow"] > 0].reset_index(
                drop=True
            )

            # Per-OD-pair mode composition, known exactly from the input demand
            # (not estimated) -- used below to split the combined solve's
            # disrupted-flow totals by mode. See overlay_combined_flows() for
            # what downstream of this (rerouting cost, edge flow) can and can't
            # inherit this same exactness.
            if mode_name == "combined":
                denom = (disrupted_od["freight_flow"] + disrupted_od["passenger_flow"]).replace(
                    0, np.nan
                )
                disrupted_od["freight_share"] = (
                    disrupted_od["freight_flow"] / denom
                ).fillna(0.0)
            else:
                disrupted_od["freight_share"] = 1.0 if mode_name == "freight" else 0.0
            disrupted_od["freight_disrupted_flow"] = (
                disrupted_od["disrupted_flow"] * disrupted_od["freight_share"]
            )
            disrupted_od["passenger_disrupted_flow"] = (
                disrupted_od["disrupted_flow"] - disrupted_od["freight_disrupted_flow"]
            )

            total_disrupted_flow = float(disrupted_od.disrupted_flow.sum())
            unique_disrupted_flow = float(
                disrupted_od.groupby(["origin_node", "destination_node"])["disrupted_flow"]
                .sum()
                .sum()
            )
            total_disrupted_flow_by_output = {
                "freight": float(disrupted_od.freight_disrupted_flow.sum()),
                "passenger": float(disrupted_od.passenger_disrupted_flow.sum()),
            }
            unique_disrupted_flow_by_output = {
                "freight": float(
                    disrupted_od.groupby(["origin_node", "destination_node"])[
                        "freight_disrupted_flow"
                    ]
                    .sum()
                    .sum()
                ),
                "passenger": float(
                    disrupted_od.groupby(["origin_node", "destination_node"])[
                        "passenger_disrupted_flow"
                    ]
                    .sum()
                    .sum()
                ),
            }
            # Aggregate allocator for rerouting cost / edge flow below: each
            # mode's share of this day's total disrupted flow. Exact as a
            # flow-share number; applying it to the solver's network-wide
            # aggregate dollar/flow totals is a proportional allocation, not a
            # per-path trace (the solver doesn't tag which mode's vehicles
            # used which path).
            freight_share_of_disrupted = (
                total_disrupted_flow_by_output["freight"] / total_disrupted_flow
                if total_disrupted_flow > 0
                else 0.0
            )
            logging.info(f"The total disrupted flows: {total_disrupted_flow}")
            logging.info(f"The unique-OD disrupted flows: {unique_disrupted_flow}")

            # estimate the pre-event cost matrix for disrupted flows
            pre_time = (disrupted_od.disrupted_flow * disrupted_od.time_cost_per_flow).sum()
            pre_operate = (
                disrupted_od.disrupted_flow * disrupted_od.operating_cost_per_flow
            ).sum()
            pre_toll = (disrupted_od.disrupted_flow * disrupted_od.toll_cost_per_flow).sum()
            total_pre_cost = pre_time + pre_operate + pre_toll

            # Restore capacity for non-disrupted roads
            logging.info("Calibrate capacity for non-flooded links...")
            disrupted_edge_flow = get_flow_on_edges(
                disrupted_od, "e_id", "path", "disrupted_flow"
            )

            road_links = road_links.merge(disrupted_edge_flow, on="e_id", how="left")
            road_links["disrupted_flow"] = road_links["disrupted_flow"].fillna(0)

            """ Update road link attributes for rerouting analysis
            """
            road_links.current_capacity = (
                pd.to_numeric(road_links.current_capacity, errors="coerce")
                .fillna(0)
                .round(0)
                .astype(int)
            )
            road_links.acc_capacity = (
                pd.to_numeric(road_links.acc_capacity, errors="coerce")
                .fillna(0)
                .round(0)
                .astype(int)
            )
            road_links.current_flow = (
                pd.to_numeric(road_links.current_flow, errors="coerce")
                .fillna(0)
                .round(0)
                .astype(int)
            )
            road_links.disrupted_flow = (
                pd.to_numeric(road_links.disrupted_flow, errors="coerce")
                .fillna(0)
                .round(0)
                .astype(int)
            )

            road_links["acc_capacity"] = (
                road_links["acc_capacity"] + road_links["disrupted_flow"]
            )
            # Seed acc_flow with background flow only (current_flow) -- NOT
            # current_flow - disrupted_flow. network_flow_model() accumulates
            # onto this seed additively (road_links["acc_flow"] +=
            # road_links["flow"] in road_revised.py), which is correct for
            # Pass A's own multi-iteration convergence (building up a running
            # total from 0) but wrong here: current_flow is always 0 in this
            # recovery loop (Script 4 tracks only the incremental disrupted/
            # rerouted flow, not Pass A's absolute totals), so subtracting
            # disrupted_flow left a bare negative seed. An edge the new route
            # doesn't use ended up permanently negative in the written output
            # (never receiving an offsetting += ). Worse, an edge on BOTH the
            # old and new route (a shared downstream segment) netted to a
            # falsely-plausible 0 -- its real rerouted flow was silently
            # cancelled by the erroneous negative seed, not just an obviously-
            # wrong negative number. Confirmed via
            # scripts/diagnostics/validate_rerouting_physics.py's
            # acc_flow_not_updated_by_solver finding, and reproduced on the
            # untouched (pre-this-fix) default freight-only path -- not
            # specific to the freight/passenger combined-capacity fix.
            road_links["acc_flow"] = road_links["current_flow"]

            logging.info("Updating road speed limits...")
            func.update_edge_speed(road_links, inplace=True)
            # SA seam: residual-floodwater depth gates (m) controlling which
            # links keep the speed constraint as the water recedes. Defaults
            # equal the historical literals (2 m / 6 m); one Morris factor
            # scales both gates coherently via `_scales: recovery.residual_depth_gates_m`.
            _gates = get_parameter(
                "recovery", "residual_depth_gates_m", {"intermediate": 2.0, "deep": 6.0}
            )
            gate_intermediate = float(_gates.get("intermediate", 2.0))
            gate_deep = float(_gates.get("deep", 6.0))
            if event_day == 1:  # apply speed constraint to every road
                road_links["acc_speed"] = road_links[["acc_speed", "max_speed"]].min(axis=1)
            if (
                event_day == 2
            ):  # only apply speed constraint to roads with flooddepth (2-6) meters
                mask = (road_links["flood_depth_max"] >= gate_intermediate) & (
                    road_links["flood_depth_max"] < gate_deep
                )
                road_links.loc[mask, "acc_speed"] = road_links.loc[
                    mask, ["acc_speed", "max_speed"]
                ].min(axis=1)
            if event_day == 3:  # only for roads > 6 meters
                mask = road_links["flood_depth_max"] >= gate_deep
                road_links.loc[mask, "acc_speed"] = road_links.loc[
                    mask, ["acc_speed", "max_speed"]
                ].min(axis=1)

            # create network (time-consuming when updating network edge index)
            logging.info("Creating igraph network...")
            valid_road_links = road_links[
                (road_links["acc_capacity"] > 0) & (road_links["acc_speed"] > 0)
            ].reset_index(drop=True)
            valid_road_links["from_id"] = valid_road_links["from_id"].astype(str)
            valid_road_links["to_id"] = valid_road_links["to_id"].astype(str)
            network, valid_road_links = func.create_igraph_network(valid_road_links, vehicle_type="car")

            # !!! make sure to pass disrupted flow for rerouting analysis
            if "Car21" in disrupted_od.columns:
                disrupted_od = disrupted_od.drop(columns=["Car21"])
            disrupted_od = disrupted_od.rename(columns={"disrupted_flow": "Car21"})
            disrupted_od["origin_node"] = disrupted_od["origin_node"].astype(str)
            disrupted_od["destination_node"] = disrupted_od["destination_node"].astype(str)

            # Run flow model
            logging.info("Running flow simulation...")
            isolation_path = out_path / f"trip_isolations_{mode_name}_s{scenario_id}_day{event_day}.pq"
            odpfc_path_iter = out_path / f"odpfc_{mode_name}_s{scenario_id}_day{event_day}.pq"
            valid_road_links, (post_time, post_operate, post_toll, total_post_cost) = func.network_flow_model(
                valid_road_links,  # update this one
                network,
                disrupted_od[
                    ["origin_node", "destination_node", "Car21"]
                ],  # update this one
                flow_breakpoint_dict,
                num_of_chunk,
                num_of_cpu,
                db_path,
                iso_out_path=str(isolation_path),
                odpfc_out_path=str(odpfc_path_iter),
                vehicle_type="car",
            )

            # Trip isolations from the post-disruption (damaged) network -- read here
            # (rather than at write-out time below) so isolated_flow_total is available
            # for the SC (isolation cost) term before cost_rows is built.
            if isolation_path.exists():
                isolation_df = pd.read_parquet(isolation_path)
                if "flow" in isolation_df.columns:
                    isolation_df = isolation_df.rename(columns={"flow": "Car21"})
            else:
                isolation_df = pd.DataFrame(columns=["origin_node", "destination_node", "Car21"])

            isolation_df = isolation_df[
                (isolation_df.origin_node != isolation_df.destination_node)
                & (isolation_df.Car21 > 0)
            ].reset_index(drop=True)
            isolated_flow_total = float(isolation_df["Car21"].sum())

            # Rerouting baseline: by default, pre-event cost is recomputed on the
            # same loaded-speed undisrupted network as post (apples-to-apples).
            # The legacy path used free-flow Pass A per-flow costs for pre while
            # post used the congestion-loaded recovery network — that mismatch
            # can produce negative rerouting costs. Set
            # NIRD_LEGACY_FREEFLOW_BASELINE=1 to restore the old behavior.
            legacy_freeflow_baseline = os.environ.get(
                "NIRD_LEGACY_FREEFLOW_BASELINE", "0"
            ).strip().lower() in {"1", "true", "yes"}
            consistent_baseline = not legacy_freeflow_baseline

            # OD pairs with no path in the disrupted network are dropped into
            # isolated_od by network_flow_model above and contribute $0 to
            # total_post_cost (excluded, not penalized). If the baseline "pre"
            # cost is computed over the *full* disrupted_od demand, those same
            # pairs still contribute their (fully-served, undisrupted) cost to
            # total_pre_cost -- so isolating a trip looks like a cost *saving*
            # in (post - pre), which can drive rerouting_cost sharply negative.
            # Isolation impact is already tracked separately (isolation_rows /
            # isolation_flow), so restrict the baseline demand to the same OD
            # pairs actually served post-disruption for a like-for-like delta.
            baseline_demand = disrupted_od
            if isolation_path.exists():
                iso_od = pd.read_parquet(isolation_path)
                if not iso_od.empty:
                    iso_keys = iso_od[["origin_node", "destination_node"]].astype(str).drop_duplicates()
                    iso_keys["_isolated"] = True
                    baseline_demand = disrupted_od.merge(
                        iso_keys, how="left", on=["origin_node", "destination_node"]
                    )
                    baseline_demand = baseline_demand[
                        baseline_demand["_isolated"].isna()
                    ].drop(columns="_isolated").reset_index(drop=True)

            if consistent_baseline:
                logging.info(
                    "Consistent rerouting baseline (default): recomputing pre-event "
                    "cost on the undisrupted loaded network."
                )
                baseline_links = road_links.copy()
                baseline_links["acc_capacity"] = baseline_links["current_capacity"]
                baseline_links["acc_flow"] = baseline_links["current_flow"]
                func.update_edge_speed(baseline_links, inplace=True)
                baseline_valid = baseline_links[
                    (baseline_links["acc_capacity"] > 0)
                    & (baseline_links["acc_speed"] > 0)
                ].reset_index(drop=True)
                baseline_valid["from_id"] = baseline_valid["from_id"].astype(str)
                baseline_valid["to_id"] = baseline_valid["to_id"].astype(str)
                baseline_network, baseline_valid = func.create_igraph_network(
                    baseline_valid, vehicle_type="car"
                )
                baseline_iso_path = (
                    out_path
                    / f"trip_isolations_{mode_name}_s{scenario_id}_day{event_day}_baseline.pq"
                )
                baseline_odpfc_path = (
                    out_path
                    / f"odpfc_{mode_name}_s{scenario_id}_day{event_day}_baseline.pq"
                )
                baseline_db_path = (
                    db_path.parent
                    / f"{db_path.stem}_baseline_{mode_name}_s{scenario_id}_day{event_day}.duckdb"
                )
                if baseline_db_path.exists():
                    baseline_db_path.unlink()
                _, (pre_time, pre_operate, pre_toll, total_pre_cost) = (
                    func.network_flow_model(
                        baseline_valid,
                        baseline_network,
                        baseline_demand[
                            ["origin_node", "destination_node", "Car21"]
                        ],
                        flow_breakpoint_dict,
                        num_of_chunk,
                        num_of_cpu,
                        str(baseline_db_path),
                        iso_out_path=str(baseline_iso_path),
                        odpfc_out_path=str(baseline_odpfc_path),
                        vehicle_type="car",
                    )
                )

            # estimate rerouting cost matrix (RC, Eq. 7 of the source stress-testing
            # framework -- Li et al., "Stress-testing road network resilience using
            # counterfactual flood events", TRD 2026). RC is deliberately computed
            # only over routed (non-isolated) flow, post minus pre -- it is NOT
            # expected to also account for isolated flow, and can be small/negative
            # in principle. Isolation is priced separately as SC below (Eq. 8-9) and
            # only combined with RC in combined_total_cost, never inside RC itself.
            rer_time = post_time - pre_time
            rer_operate = post_operate - pre_operate
            rer_toll = post_toll - pre_toll
            rerouting_cost = rer_time + rer_operate + rer_toll
            logging.info(
                f"The original travel costs for disrupted od: $ million {total_pre_cost/ 1e6}"
            )
            logging.info(
                f"The total travel costs after disruption: $ million {total_post_cost/ 1e6}"
            )
            logging.info(
                f"The rerouting cost for scenario {scenario_id}: $ million {rerouting_cost / 1e6}"
            )

            # isolation cost (SC, Eq. 8-9): omega is a per-unit-flow-per-day economic
            # loss for flow that cannot be routed at all on the post-disruption
            # network. The paper anchors omega on labour-productivity loss for
            # passenger commuters (GBP/hr x 7hr workday); for freight, a stranded
            # vehicle isn't a commuter losing wages, it's cargo/hauling capacity
            # lost for the day, so we use the existing sourced VOT_USD_PER_HOUR
            # value-of-time constant for the relevant vehicle type x 24h/day.
            #
            # For a combined solve, isolation splits by mode EXACTLY: isolation_df
            # is already one row per OD pair, so each isolated pair's own known
            # freight/passenger composition (disrupted_od["freight_share"]) gives
            # an exact freight/passenger isolated-flow split -- no network-wide
            # proportional assumption needed here (unlike rerouting cost / edge
            # flow below, which the solver only returns as aggregates).
            if mode_name == "combined":
                iso_shares = disrupted_od[
                    ["origin_node", "destination_node", "freight_share"]
                ].drop_duplicates(subset=["origin_node", "destination_node"])
                isolation_df = isolation_df.merge(
                    iso_shares, on=["origin_node", "destination_node"], how="left"
                )
                isolation_df["freight_share"] = isolation_df["freight_share"].fillna(0.0)
                freight_isolated_flow = float(
                    (isolation_df["Car21"] * isolation_df["freight_share"]).sum()
                )
                isolated_flow_by_output = {
                    "freight": freight_isolated_flow,
                    "passenger": isolated_flow_total - freight_isolated_flow,
                }
            else:
                isolated_flow_by_output = {mode_name: isolated_flow_total}

            isolation_cost_by_output = {}
            for out_mode, iso_flow in isolated_flow_by_output.items():
                vot_key = "ogv" if out_mode == "freight" else "car"
                isolation_cost_by_output[out_mode] = iso_flow * cons.VOT_USD_PER_HOUR[vot_key] * 24
            logging.info(
                f"Isolated flow (post-disruption, unroutable): {isolated_flow_total}"
            )
            logging.info(
                f"The isolation cost for scenario {scenario_id}: $ million "
                f"{sum(isolation_cost_by_output.values()) / 1e6}"
            )

            logging.info("Saving results to disk...")

            # Rerouting cost / edge flow (below) are network-wide aggregates the
            # solver returns for the combined flow -- split proportionally by
            # each mode's share of this day's disrupted flow (freight_share_of_
            # disrupted), not per-path-exact. See overlay_combined_flows().
            isolation_usd_per_day = float(
                get_parameter("cost_time", "isolation_usd_per_day", 50.0)
            )
            isolation_df["isolation_cost_usd"] = (
                pd.to_numeric(isolation_df["Car21"], errors="coerce").fillna(0.0)
                * isolation_usd_per_day
            )

            for out_mode in output_modes:
                if mode_name == "combined":
                    share = (
                        freight_share_of_disrupted
                        if out_mode == "freight"
                        else (1.0 - freight_share_of_disrupted)
                    )
                    out_disrupted_flow = total_disrupted_flow_by_output[out_mode]
                    out_unique_disrupted_flow = unique_disrupted_flow_by_output[out_mode]
                    iso_share_col = (
                        isolation_df["freight_share"]
                        if out_mode == "freight"
                        else (1.0 - isolation_df["freight_share"])
                    )
                    out_iso_df = isolation_df.copy()
                    out_iso_df["Car21"] = (
                        pd.to_numeric(out_iso_df["Car21"], errors="coerce").fillna(0.0)
                        * iso_share_col
                    )
                    out_iso_df["isolation_cost_usd"] = out_iso_df["isolation_cost_usd"] * iso_share_col
                    out_iso_df = out_iso_df.drop(columns=["freight_share"])
                else:
                    share = 1.0
                    out_disrupted_flow = total_disrupted_flow
                    out_unique_disrupted_flow = unique_disrupted_flow
                    out_iso_df = isolation_df

                # rerouting costs (one row per recovery day; see cost_rows note above)
                cost_rows_by_output[out_mode].append(
                    {
                        "scenario": scenario_id,
                        "event_day": event_day,
                        "total_disrupted_flow": out_disrupted_flow,
                        "total_disrupted_flow_unique_od": out_unique_disrupted_flow,
                        "rer_time": rer_time * share,
                        "rer_operate": rer_operate * share,
                        "rer_toll": rer_toll * share,
                        "rerouting_cost": rerouting_cost * share,
                        "isolated_flow_total": isolated_flow_by_output[out_mode],
                        "isolation_cost": isolation_cost_by_output[out_mode],
                    }
                )
                cost_df = pd.DataFrame(cost_rows_by_output[out_mode])
                cost_df["direct_damage_total_musd"] = direct_damage_total_musd
                cost_df["direct_damage_total_usd"] = direct_damage_total
                cost_df["direct_damage_total"] = direct_damage_total
                cost_df["combined_total_cost"] = (
                    cost_df["rerouting_cost"]
                    + cost_df["isolation_cost"]
                    + cost_df["direct_damage_total"]
                )
                cost_df.to_csv(
                    out_path / f"rerouting_cost_{out_mode}_s{scenario_id}_day{event_day}.csv",
                    index=False,
                )

                # trip isolations (isolation_df already read/filtered above, right
                # after the post-disruption flow simulation, to compute
                # isolated_flow_total for the SC term -- rerouting_cost +
                # isolation_cost above uses that VOT-anchored SC.
                # isolation_cost_usd below is a second, independently-parameterized
                # isolation valuation (SA seam, default $/trip-day from
                # parameters/unified_parameters.json), kept alongside rather than
                # merged with SC so both are auditable and Morris can screen the
                # isolation-valuation assumption on its own axis.
                out_iso_df.to_csv(
                    out_path / f"trip_isolations_{out_mode}_s{scenario_id}_day{event_day}.csv",
                    index=False,
                )
                cost_rows_by_output[out_mode][-1]["isolation_flow"] = float(
                    pd.to_numeric(out_iso_df["Car21"], errors="coerce").fillna(0.0).sum()
                )
                cost_rows_by_output[out_mode][-1]["isolation_cost_usd"] = float(
                    out_iso_df["isolation_cost_usd"].sum()
                )

            # edge flows
            def _to_scalar_float(value):
                if isinstance(value, np.ndarray):
                    arr = np.asarray(value).reshape(-1)
                    if arr.size == 0:
                        return np.nan
                    return float(arr[0])
                if isinstance(value, (list, tuple, set)):
                    arr = np.asarray(list(value)).reshape(-1)
                    if arr.size == 0:
                        return np.nan
                    return float(arr[0])
                if value is None:
                    return np.nan
                try:
                    return float(value)
                except Exception:
                    return np.nan

            valid_road_links = valid_road_links.copy()
            valid_road_links["acc_flow"] = valid_road_links["acc_flow"].apply(_to_scalar_float).astype(float)
            road_links["acc_flow"] = pd.to_numeric(road_links["acc_flow"], errors="coerce").astype(float)
            road_links["current_flow"] = pd.to_numeric(road_links["current_flow"], errors="coerce").astype(float)
            road_links = road_links.set_index("e_id")
            updated_acc_flow = valid_road_links.set_index("e_id")["acc_flow"].astype(float)
            road_links.loc[updated_acc_flow.index, "acc_flow"] = updated_acc_flow.to_numpy(dtype=float)
            road_links = road_links.reset_index()
            road_links["change_flow"] = road_links["acc_flow"] - road_links["current_flow"]

            # Edge flow is the solver's network-wide result for the combined
            # flow -- same proportional-allocation caveat as rerouting cost
            # above (no per-edge mode trace available without per-path output).
            for out_mode in output_modes:
                if mode_name == "combined":
                    share = (
                        freight_share_of_disrupted
                        if out_mode == "freight"
                        else (1.0 - freight_share_of_disrupted)
                    )
                    out_links = road_links.copy()
                    out_links["change_flow"] = road_links["change_flow"] * share
                    out_links["acc_flow"] = road_links["current_flow"] + out_links["change_flow"]
                else:
                    out_links = road_links
                out_links.to_parquet(
                    out_path / f"edge_flows_{out_mode}_s{scenario_id}_day{event_day}.gpq"
                )

            # reset road_links for next scenario
            road_links = road_links[initial_road_links_cols]

            del disrupted_od
            del disrupted_edge_flow
            del valid_road_links
            gc.collect()

        for out_mode in output_modes:
            logging.info("Saving overall rerouting costs to disk (mode=%s)...", out_mode)
            rows = cost_rows_by_output[out_mode]
            if len(rows) == 0:
                logging.info("No rerouting results to save for mode=%s.", out_mode)
                continue
            cost_df = pd.DataFrame(rows)
            cost_df["direct_damage_total_musd"] = direct_damage_total_musd
            cost_df["direct_damage_total_usd"] = direct_damage_total
            cost_df["direct_damage_total"] = direct_damage_total
            cost_df["combined_total_cost"] = (
                cost_df["rerouting_cost"]
                + cost_df["isolation_cost"]
                + cost_df["direct_damage_total"]
            )
            cost_df.to_csv(out_path / f"cost_matrix_{out_mode}_by_scenario.csv", index=False)
            if out_mode == "freight":
                cost_df.to_csv(out_path / "cost_matrix_by_scenario.csv", index=False)


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s %(process)d %(filename)s %(message)s", level=logging.INFO
    )
    try:
        depth_key, event_key, num_of_chunk, num_of_cpu = sys.argv[1:]
        main(int(depth_key), int(event_key), int(num_of_chunk), int(num_of_cpu))
    except (IndexError, ValueError) as exc:
        logging.exception("Script 4 failed while parsing CLI args or during execution")
        logging.info(
            "Please provide inputs: depth_key, event_key, num_of_chunk, and num_of_cpu!"
        )
        sys.exit(1)
