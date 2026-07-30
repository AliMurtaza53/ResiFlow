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
from resiflow.combined_od import resolve_passenger_od_path
from resiflow.demand import (
    load_assignment_demand,
    demand_spec_from_env,
    apply_sample_od_n,
    restrict_od_to_pairs,
    sample_od_n_from_env,
)
from resiflow.networks import load_assignment_profiles, normalize_network_links
from resiflow.networks.assignment import map_tier_profile
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
    fallback when no Pass-B-specific event_candidates output exists. Mirrors
    load_path_index_disrupted_candidates's filtered-query approach; simpler
    here since odpfc's ``path`` column already stores e_id strings directly
    (no edge_lookup index translation needed).
    """
    conn = duckdb.connect()
    duckdb_memory_limit = os.environ.get("NIRD_DUCKDB_MEMORY_LIMIT", "24GB")
    conn.execute(f"PRAGMA memory_limit='{duckdb_memory_limit}'")
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
    result = conn.execute(
        f"""
        SELECT o.*
        FROM {source_sql} o
        WHERE EXISTS (
            SELECT 1 FROM UNNEST(o.path) AS u(e_id)
            WHERE u.e_id IN (SELECT e_id FROM damaged_edges)
        )
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
    """Load recovery rates for bridges and ordinary roads."""
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

    reroute_modes: list[tuple[str, pd.DataFrame]] = [("freight", freight_candidates)]
    passenger_reroute_enabled = os.environ.get(
        "RESIFLOW_ENABLE_PASSENGER_REROUTING",
        os.environ.get("NIRD_ENABLE_PASSENGER_REROUTING", "0"),
    ).strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if passenger_reroute_enabled and passenger_od_df is not None:
        reroute_modes.append(
            ("passenger", overlay_passenger_flows(base_disrupted_candidates, passenger_od_df))
        )
    elif passenger_reroute_enabled:
        logging.warning("Passenger rerouting enabled but passenger OD not found.")

    out_path = (
        base_path.parent
        / "results"
        / "rerouting_analysis"
        / results_variant
        / str(depth_key)
        / str(flood_key)
    )
    out_path.mkdir(parents=True, exist_ok=True)

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
        cost_rows = []

        # Load link recovery scenarios (both capacity and speed)
        for day_idx, (scenario_id, event_day) in enumerate(zip(scenarios, conditions)):
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
            total_disrupted_flow = float(disrupted_od.disrupted_flow.sum())
            unique_disrupted_flow = float(
                disrupted_od.groupby(["origin_node", "destination_node"])["disrupted_flow"]
                .sum()
                .sum()
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
            road_links["acc_flow"] = (
                road_links["current_flow"] - road_links["disrupted_flow"]
            )

            logging.info("Updating road speed limits...")
            func.update_edge_speed(road_links, inplace=True)
            if event_day == 1:  # apply speed constraint to every road
                road_links["acc_speed"] = road_links[["acc_speed", "max_speed"]].min(axis=1)
            if (
                event_day == 2
            ):  # only apply speed constraint to roads with flooddepth (2-6) meters
                mask = (road_links["flood_depth_max"] >= 2) & (
                    road_links["flood_depth_max"] < 6
                )
                road_links.loc[mask, "acc_speed"] = road_links.loc[
                    mask, ["acc_speed", "max_speed"]
                ].min(axis=1)
            if event_day == 3:  # only for roads > 6 meters
                mask = road_links["flood_depth_max"] >= 6
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
                        disrupted_od[
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

            # estimate rerouting cost matrix
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

            logging.info("Saving results to disk...")

            # rerouting costs (one row per recovery day; see cost_rows note above)
            cost_rows.append(
                {
                    "scenario": scenario_id,
                    "event_day": event_day,
                    "total_disrupted_flow": total_disrupted_flow,
                    "total_disrupted_flow_unique_od": unique_disrupted_flow,
                    "rer_time": rer_time,
                    "rer_operate": rer_operate,
                    "rer_toll": rer_toll,
                    "rerouting_cost": rerouting_cost,
                }
            )
            cost_df = pd.DataFrame(cost_rows)
            cost_df["direct_damage_total_musd"] = direct_damage_total_musd
            cost_df["direct_damage_total_usd"] = direct_damage_total
            cost_df["direct_damage_total"] = direct_damage_total
            cost_df["combined_total_cost"] = cost_df["rerouting_cost"] + cost_df["direct_damage_total"]
            cost_df.to_csv(
                out_path / f"rerouting_cost_{mode_name}_s{scenario_id}_day{event_day}.csv", index=False
            )

            # trip isolations
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
            isolation_df.to_csv(
                out_path / f"trip_isolations_{mode_name}_s{scenario_id}_day{event_day}.csv",
                index=False,
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
            road_links.to_parquet(
                out_path / f"edge_flows_{mode_name}_s{scenario_id}_day{event_day}.gpq"
            )

            # reset road_links for next scenario
            road_links = road_links[initial_road_links_cols]

            del disrupted_od
            del disrupted_edge_flow
            del valid_road_links
            gc.collect()

        logging.info("Saving overall rerouting costs to disk (mode=%s)...", mode_name)
        if len(cost_rows) == 0:
            logging.info("No rerouting results to save for mode=%s.", mode_name)
            continue
        cost_df = pd.DataFrame(cost_rows)
        cost_df["direct_damage_total_musd"] = direct_damage_total_musd
        cost_df["direct_damage_total_usd"] = direct_damage_total
        cost_df["direct_damage_total"] = direct_damage_total
        cost_df["combined_total_cost"] = cost_df["rerouting_cost"] + cost_df["direct_damage_total"]
        cost_df.to_csv(out_path / f"cost_matrix_{mode_name}_by_scenario.csv", index=False)
        if mode_name == "freight":
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
