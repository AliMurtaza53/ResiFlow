"""FAF5 freight OD disaggregation utilities.

This module prepares freight demand for the existing NIRD assignment pipeline.
It deliberately stops at OD table creation: the assignment engine continues to
read ``origin_node``, ``destination_node``, and ``Car21`` from parquet exactly as
it does today.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

try:  # geopandas is an optional runtime dependency for centroid/node mapping.
    import geopandas as gpd  # type: ignore
except Exception:  # pragma: no cover - import availability depends on env setup.
    gpd = None


FAF_FLOW_SCHEMA = {
    "origin_faf_zone": "Origin FAF zone code. FAF CSV aliases: dms_orig, origin_zone.",
    "destination_faf_zone": "Destination FAF zone code. FAF CSV aliases: dms_dest, destination_zone.",
    "commodity": "Commodity group/SCTG code. FAF CSV aliases: sctg2, commodity_group.",
    "mode": "Mode code or label. FAF CSV aliases: dms_mode.",
    "tons": "Annual commodity tons. FAF tons_* columns are usually thousand tons.",
    "value": "Optional annual commodity value.",
    "year": "Flow year.",
}

CROSSWALK_SCHEMA = {
    "faf_zone": "Parent FAF zone code.",
    "subarea_id": "County/subcounty/port/airport/border-crossing unit ID.",
}

WEIGHT_SCHEMA = {
    "subarea_id": "County/subcounty unit ID.",
    "commodity": "Commodity group/SCTG code or 'all'.",
    "production_weight": "Non-negative origin-side weight.",
    "attraction_weight": "Non-negative destination-side weight.",
}

CENTROID_SCHEMA = {
    "subarea_id": "County/subcounty unit ID.",
    "x": "Centroid x coordinate or longitude.",
    "y": "Centroid y coordinate or latitude.",
    "node_id": "Optional pre-mapped assignment node ID.",
}

PAYLOAD_SCHEMA = {
    "commodity": "Commodity group/SCTG code or 'all'.",
    "truck_type": "Truck type label, e.g. single_unit or combination.",
    "payload_tons": "Average tons per truck.",
    "distance_bin": "Optional haul-distance bin.",
}

TONNAGE_OUTPUT_SCHEMA = {
    "origin_faf_zone": "Parent FAF origin zone.",
    "destination_faf_zone": "Parent FAF destination zone.",
    "origin_subarea_id": "Disaggregated origin geography.",
    "destination_subarea_id": "Disaggregated destination geography.",
    "commodity": "Commodity group/SCTG code.",
    "mode": "Mode code or label.",
    "tons": "Disaggregated annual tons.",
    "value": "Disaggregated annual value when provided.",
    "year": "Flow year.",
}

TRUCK_OUTPUT_SCHEMA = {
    **TONNAGE_OUTPUT_SCHEMA,
    "truck_type": "Truck type label from the payload table.",
    "truck_trips_annual": "Annual truck trips.",
    "truck_trips_daily": "Average daily truck trips.",
}

ASSIGNMENT_OD_SCHEMA = {
    "origin_node": "Network node ID consumed by Script 1.",
    "destination_node": "Network node ID consumed by Script 1.",
    "Car21": "Average daily truck trips in the assignment-compatible flow column.",
}


@dataclass(frozen=True)
class FreightDisaggregationInputs:
    """Container for the input tables used by the preprocessing workflow."""

    faf_flows: pd.DataFrame
    crosswalk: pd.DataFrame
    weights: pd.DataFrame
    centroids: pd.DataFrame
    payload_factors: pd.DataFrame
    distance_matrix: pd.DataFrame | None = None


def read_table(path: str | Path, **kwargs) -> pd.DataFrame:
    """Load a CSV, parquet, or geospatial file into a DataFrame."""

    table_path = Path(path)
    suffix = table_path.suffix.lower()
    if suffix in {".pq", ".parquet", ".gpq"}:
        return pd.read_parquet(table_path, **kwargs)
    if suffix == ".csv":
        return pd.read_csv(table_path, **kwargs)
    if suffix in {".gpkg", ".geojson", ".shp"}:
        if gpd is None:
            raise ImportError("geopandas is required to read geospatial input files")
        return gpd.read_file(table_path, **kwargs)
    raise ValueError(f"Unsupported table format: {table_path}")


def load_input_tables(
    faf_flow_path: str | Path,
    crosswalk_path: str | Path,
    weights_path: str | Path,
    centroids_path: str | Path,
    payload_factors_path: str | Path,
    distance_matrix_path: str | Path | None = None,
) -> FreightDisaggregationInputs:
    """Load all required disaggregation inputs from disk."""

    return FreightDisaggregationInputs(
        faf_flows=read_table(faf_flow_path),
        crosswalk=read_table(crosswalk_path),
        weights=read_table(weights_path),
        centroids=read_table(centroids_path),
        payload_factors=read_table(payload_factors_path),
        distance_matrix=read_table(distance_matrix_path) if distance_matrix_path else None,
    )


def normalize_faf_flows(
    faf_flows: pd.DataFrame,
    year: int | str,
    tons_unit: str = "thousand_tons",
    mode_filter: str | int | None = 1,
) -> pd.DataFrame:
    """Normalize FAF flow aliases into the schema consumed by this module.

    FAF public CSVs commonly store yearly tons in ``tons_YYYY`` and use mode
    code ``1`` for truck. If ``tons`` already exists it is used directly.
    """

    df = faf_flows.copy()
    rename_map = {
        "dms_orig": "origin_faf_zone",
        "origin_zone": "origin_faf_zone",
        "dms_dest": "destination_faf_zone",
        "destination_zone": "destination_faf_zone",
        "sctg2": "commodity",
        "commodity_group": "commodity",
        "dms_mode": "mode",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    tons_col = "tons" if "tons" in df.columns else f"tons_{year}"
    if tons_col not in df.columns:
        raise ValueError(f"Could not find a tons column. Expected 'tons' or '{tons_col}'.")
    df["tons"] = pd.to_numeric(df[tons_col], errors="coerce").fillna(0.0)
    if tons_unit == "thousand_tons":
        df["tons"] = df["tons"] * 1000.0
    elif tons_unit != "tons":
        raise ValueError("tons_unit must be either 'tons' or 'thousand_tons'")

    value_col = "value" if "value" in df.columns else f"value_{year}"
    if value_col in df.columns:
        df["value"] = pd.to_numeric(df[value_col], errors="coerce").fillna(0.0)
    else:
        df["value"] = np.nan
    df["year"] = int(year)

    required = ["origin_faf_zone", "destination_faf_zone", "commodity", "mode"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"FAF flow table is missing required columns: {missing}")

    if mode_filter is not None:
        df = df[df["mode"].astype(str) == str(mode_filter)].copy()

    df = df[df["tons"] > 0].copy()
    return df[
        [
            "origin_faf_zone",
            "destination_faf_zone",
            "commodity",
            "mode",
            "tons",
            "value",
            "year",
        ]
    ]


def _as_key(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip()


def validate_required_columns(df: pd.DataFrame, schema: Mapping[str, str], table_name: str) -> None:
    """Raise a clear error if a table is missing required schema columns."""

    missing = [col for col in schema if col not in df.columns]
    if missing:
        raise ValueError(f"{table_name} is missing required columns: {missing}")


def compute_production_attraction_weights(
    crosswalk: pd.DataFrame,
    weights: pd.DataFrame,
) -> pd.DataFrame:
    """Attach normalized production/attraction shares within each FAF zone.

    Commodity-specific rows are retained. If a zone/commodity total is zero, the
    available subareas receive equal shares for that side of the OD.
    """

    validate_required_columns(crosswalk, CROSSWALK_SCHEMA, "crosswalk")
    validate_required_columns(weights, WEIGHT_SCHEMA, "weights")

    cw = crosswalk[["faf_zone", "subarea_id"]].copy()
    w = weights[["subarea_id", "commodity", "production_weight", "attraction_weight"]].copy()
    cw["faf_zone"] = _as_key(cw["faf_zone"])
    cw["subarea_id"] = _as_key(cw["subarea_id"])
    w["subarea_id"] = _as_key(w["subarea_id"])
    w["commodity"] = _as_key(w["commodity"])
    w["production_weight"] = pd.to_numeric(w["production_weight"], errors="coerce").fillna(0.0).clip(lower=0.0)
    w["attraction_weight"] = pd.to_numeric(w["attraction_weight"], errors="coerce").fillna(0.0).clip(lower=0.0)

    merged = cw.merge(w, on="subarea_id", how="left")
    merged["commodity"] = merged["commodity"].fillna("all")
    merged[["production_weight", "attraction_weight"]] = merged[
        ["production_weight", "attraction_weight"]
    ].fillna(1.0)

    group_cols = ["faf_zone", "commodity"]
    prod_total = merged.groupby(group_cols)["production_weight"].transform("sum")
    attr_total = merged.groupby(group_cols)["attraction_weight"].transform("sum")
    group_count = merged.groupby(group_cols)["subarea_id"].transform("count").clip(lower=1)

    merged["production_share"] = np.where(
        prod_total > 0,
        merged["production_weight"] / prod_total,
        1.0 / group_count,
    )
    merged["attraction_share"] = np.where(
        attr_total > 0,
        merged["attraction_weight"] / attr_total,
        1.0 / group_count,
    )
    return merged[
        [
            "faf_zone",
            "subarea_id",
            "commodity",
            "production_weight",
            "attraction_weight",
            "production_share",
            "attraction_share",
        ]
    ]


def _select_zone_weights(
    normalized_weights: pd.DataFrame,
    faf_zone: object,
    commodity: object,
    share_col: str,
) -> pd.DataFrame:
    zone = str(faf_zone).strip()
    comm = str(commodity).strip()
    subset = normalized_weights[
        (normalized_weights["faf_zone"] == zone) & (normalized_weights["commodity"] == comm)
    ].copy()
    if subset.empty:
        subset = normalized_weights[
            (normalized_weights["faf_zone"] == zone) & (normalized_weights["commodity"] == "all")
        ].copy()
    if subset.empty:
        raise ValueError(f"No disaggregation weights found for FAF zone={zone}, commodity={comm}")
    subset = subset[["subarea_id", share_col]].rename(columns={share_col: "share"})
    subset["share"] = pd.to_numeric(subset["share"], errors="coerce").fillna(0.0)
    total = float(subset["share"].sum())
    if total <= 0:
        subset["share"] = 1.0 / len(subset)
    else:
        subset["share"] = subset["share"] / total
    return subset


def build_distance_lookup(distance_matrix: pd.DataFrame | None) -> dict[tuple[str, str], float]:
    """Convert an optional long-form skim into a lookup dictionary."""

    if distance_matrix is None:
        return {}
    required = {"origin_subarea_id", "destination_subarea_id", "distance"}
    missing = required - set(distance_matrix.columns)
    if missing:
        raise ValueError(f"distance_matrix is missing required columns: {sorted(missing)}")
    distances = distance_matrix.copy()
    distances["origin_subarea_id"] = _as_key(distances["origin_subarea_id"])
    distances["destination_subarea_id"] = _as_key(distances["destination_subarea_id"])
    distances["distance"] = pd.to_numeric(distances["distance"], errors="coerce")
    return {
        (row.origin_subarea_id, row.destination_subarea_id): float(row.distance)
        for row in distances.itertuples(index=False)
        if pd.notna(row.distance)
    }


def apply_gravity_disaggregation(
    faf_flows: pd.DataFrame,
    normalized_weights: pd.DataFrame,
    distance_matrix: pd.DataFrame | None = None,
    distance_decay_power: float = 1.0,
    min_distance: float = 1.0,
) -> pd.DataFrame:
    """Disaggregate FAF zone flows to county/subcounty OD tonnage rows."""

    validate_required_columns(faf_flows, FAF_FLOW_SCHEMA, "faf_flows")
    distance_lookup = build_distance_lookup(distance_matrix)
    rows: list[dict[str, object]] = []

    for flow in faf_flows.itertuples(index=False):
        origin = getattr(flow, "origin_faf_zone")
        destination = getattr(flow, "destination_faf_zone")
        commodity = getattr(flow, "commodity")
        prod = _select_zone_weights(normalized_weights, origin, commodity, "production_share")
        attr = _select_zone_weights(normalized_weights, destination, commodity, "attraction_share")
        combos = prod.merge(attr, how="cross", suffixes=("_origin", "_destination"))
        combos = combos.rename(
            columns={
                "subarea_id_origin": "origin_subarea_id",
                "subarea_id_destination": "destination_subarea_id",
                "share_origin": "production_share",
                "share_destination": "attraction_share",
            }
        )
        combos["gravity_weight"] = combos["production_share"] * combos["attraction_share"]

        if distance_lookup:
            distances = [
                distance_lookup.get((str(o), str(d)), np.nan)
                for o, d in zip(combos["origin_subarea_id"], combos["destination_subarea_id"])
            ]
            combos["distance"] = pd.to_numeric(pd.Series(distances), errors="coerce")
            impedance = 1.0 / np.power(combos["distance"].fillna(min_distance).clip(lower=min_distance), distance_decay_power)
            combos["gravity_weight"] = combos["gravity_weight"] * impedance

        total_weight = float(combos["gravity_weight"].sum())
        if total_weight <= 0:
            combos["gravity_weight"] = 1.0 / len(combos)
        else:
            combos["gravity_weight"] = combos["gravity_weight"] / total_weight

        for sub in combos.itertuples(index=False):
            share = float(sub.gravity_weight)
            rows.append(
                {
                    "origin_faf_zone": str(origin).strip(),
                    "destination_faf_zone": str(destination).strip(),
                    "origin_subarea_id": str(sub.origin_subarea_id),
                    "destination_subarea_id": str(sub.destination_subarea_id),
                    "commodity": str(commodity).strip(),
                    "mode": getattr(flow, "mode"),
                    "tons": float(getattr(flow, "tons")) * share,
                    "value": float(getattr(flow, "value")) * share
                    if pd.notna(getattr(flow, "value"))
                    else np.nan,
                    "year": int(getattr(flow, "year")),
                }
            )

    return pd.DataFrame(rows, columns=list(TONNAGE_OUTPUT_SCHEMA))


def balance_to_faf_totals(disaggregated_tons: pd.DataFrame, faf_flows: pd.DataFrame) -> pd.DataFrame:
    """Scale disaggregated rows so every FAF OD/commodity total is preserved."""

    validate_required_columns(disaggregated_tons, TONNAGE_OUTPUT_SCHEMA, "disaggregated_tons")
    key_cols = ["origin_faf_zone", "destination_faf_zone", "commodity", "mode", "year"]
    target = faf_flows.copy()
    target[key_cols[:3]] = target[key_cols[:3]].astype(str)
    target = target.groupby(key_cols, as_index=False)["tons"].sum().rename(columns={"tons": "_target_tons"})

    result = disaggregated_tons.copy()
    current = result.groupby(key_cols, as_index=False)["tons"].sum().rename(columns={"tons": "_current_tons"})
    result = result.merge(target, on=key_cols, how="left").merge(current, on=key_cols, how="left")
    scale = np.where(result["_current_tons"] > 0, result["_target_tons"] / result["_current_tons"], 0.0)
    result["tons"] = result["tons"] * scale
    if "value" in result.columns:
        result["value"] = result["value"] * scale
    return result.drop(columns=["_target_tons", "_current_tons"])


def convert_tons_to_truck_trips(
    disaggregated_tons: pd.DataFrame,
    payload_factors: pd.DataFrame,
    days_per_year: float = 365.0,
) -> pd.DataFrame:
    """Convert annual tons to truck trips using payload factors."""

    validate_required_columns(payload_factors, PAYLOAD_SCHEMA, "payload_factors")
    tons = disaggregated_tons.copy()
    payload = payload_factors.copy()
    tons["commodity"] = _as_key(tons["commodity"])
    payload["commodity"] = _as_key(payload["commodity"])
    payload["payload_tons"] = pd.to_numeric(payload["payload_tons"], errors="coerce")
    payload = payload[payload["payload_tons"] > 0].copy()
    if payload.empty:
        raise ValueError("payload_factors must contain at least one positive payload_tons value")

    exact = tons.merge(payload, on="commodity", how="left")
    missing = exact["payload_tons"].isna()
    if missing.any():
        fallback = payload[payload["commodity"] == "all"].drop(columns=["commodity"])
        if fallback.empty:
            missing_commodities = sorted(exact.loc[missing, "commodity"].unique())
            raise ValueError(f"No payload factor found for commodities: {missing_commodities}")
        replacement = tons.loc[missing, :].merge(fallback, how="cross")
        exact = pd.concat([exact.loc[~missing, :], replacement], ignore_index=True, sort=False)

    exact["truck_trips_annual"] = exact["tons"] / exact["payload_tons"]
    exact["truck_trips_daily"] = exact["truck_trips_annual"] / float(days_per_year)
    return exact[list(TRUCK_OUTPUT_SCHEMA) + ["payload_tons"]]


def export_od_tables(
    tonnage_od: pd.DataFrame,
    truck_od: pd.DataFrame,
    output_dir: str | Path,
    prefix: str = "faf5_freight",
) -> dict[str, Path]:
    """Write disaggregated tonnage and truck-trip tables to parquet."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "tonnage_od": out / f"{prefix}_county_tonnage_od.pq",
        "truck_od": out / f"{prefix}_truck_trip_od.pq",
    }
    tonnage_od.to_parquet(paths["tonnage_od"], index=False)
    truck_od.to_parquet(paths["truck_od"], index=False)
    return paths


def build_assignment_od(
    truck_od: pd.DataFrame,
    subarea_node_map: pd.DataFrame,
    flow_column: str = "truck_trips_daily",
) -> pd.DataFrame:
    """Aggregate truck OD rows into the assignment-compatible OD schema."""

    map_required = {"subarea_id", "node_id"}
    missing = map_required - set(subarea_node_map.columns)
    if missing:
        raise ValueError(f"subarea_node_map is missing required columns: {sorted(missing)}")
    if flow_column not in truck_od.columns:
        raise ValueError(f"truck_od is missing flow column: {flow_column}")

    node_map = subarea_node_map[["subarea_id", "node_id"]].copy()
    node_map["subarea_id"] = _as_key(node_map["subarea_id"])
    node_map = node_map.drop_duplicates("subarea_id")

    od = truck_od.copy()
    od["origin_subarea_id"] = _as_key(od["origin_subarea_id"])
    od["destination_subarea_id"] = _as_key(od["destination_subarea_id"])
    od = od.merge(node_map.rename(columns={"subarea_id": "origin_subarea_id", "node_id": "origin_node"}), on="origin_subarea_id")
    od = od.merge(
        node_map.rename(columns={"subarea_id": "destination_subarea_id", "node_id": "destination_node"}),
        on="destination_subarea_id",
    )
    od["Car21"] = pd.to_numeric(od[flow_column], errors="coerce").fillna(0.0)
    od = od[od["Car21"] > 0]
    return od.groupby(["origin_node", "destination_node"], as_index=False)["Car21"].sum()


def validation_summaries(
    faf_flows: pd.DataFrame,
    disaggregated_tons: pd.DataFrame,
    tolerance: float = 1e-6,
) -> dict[str, pd.DataFrame]:
    """Return diagnostics proving FAF OD/commodity tonnage preservation."""

    key_cols = ["origin_faf_zone", "destination_faf_zone", "commodity", "mode", "year"]
    original = faf_flows.copy()
    original[key_cols[:3]] = original[key_cols[:3]].astype(str)
    original_summary = original.groupby(key_cols, as_index=False)["tons"].sum().rename(columns={"tons": "faf_tons"})
    disagg_summary = (
        disaggregated_tons.groupby(key_cols, as_index=False)["tons"]
        .sum()
        .rename(columns={"tons": "disaggregated_tons"})
    )
    preservation = original_summary.merge(disagg_summary, on=key_cols, how="outer").fillna(0.0)
    preservation["tons_delta"] = preservation["disaggregated_tons"] - preservation["faf_tons"]
    preservation["within_tolerance"] = preservation["tons_delta"].abs() <= tolerance
    commodity_summary = (
        preservation.groupby(["commodity", "year"], as_index=False)[["faf_tons", "disaggregated_tons", "tons_delta"]].sum()
    )
    return {
        "faf_total_preservation": preservation,
        "commodity_summary": commodity_summary,
    }


def write_assignment_od(assignment_od: pd.DataFrame, path: str | Path) -> Path:
    """Write the assignment-ready OD parquet consumed by Script 1."""

    validate_required_columns(assignment_od, ASSIGNMENT_OD_SCHEMA, "assignment_od")
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    assignment_od.to_parquet(output_path, index=False)
    return output_path


def run_freight_disaggregation(
    inputs: FreightDisaggregationInputs,
    year: int | str,
    output_dir: str | Path,
    subarea_node_map: pd.DataFrame | None = None,
    tons_unit: str = "thousand_tons",
    mode_filter: str | int | None = 1,
    prefix: str = "faf5_freight",
) -> dict[str, object]:
    """Run the full FAF-zone to assignment-OD preprocessing workflow."""

    faf_flows = normalize_faf_flows(inputs.faf_flows, year=year, tons_unit=tons_unit, mode_filter=mode_filter)
    normalized_weights = compute_production_attraction_weights(inputs.crosswalk, inputs.weights)
    tonnage_od = apply_gravity_disaggregation(
        faf_flows,
        normalized_weights,
        distance_matrix=inputs.distance_matrix,
    )
    tonnage_od = balance_to_faf_totals(tonnage_od, faf_flows)
    truck_od = convert_tons_to_truck_trips(tonnage_od, inputs.payload_factors)
    paths = export_od_tables(tonnage_od, truck_od, output_dir=output_dir, prefix=prefix)
    diagnostics = validation_summaries(faf_flows, tonnage_od)

    assignment_od = None
    if subarea_node_map is not None:
        assignment_od = build_assignment_od(truck_od, subarea_node_map)

    return {
        "faf_flows": faf_flows,
        "tonnage_od": tonnage_od,
        "truck_od": truck_od,
        "assignment_od": assignment_od,
        "diagnostics": diagnostics,
        "paths": paths,
    }


def schema_markdown() -> str:
    """Render the required schemas as Markdown for handoffs and READMEs."""

    sections = {
        "FAF Flow Input": FAF_FLOW_SCHEMA,
        "Crosswalk Input": CROSSWALK_SCHEMA,
        "Weight Input": WEIGHT_SCHEMA,
        "Centroid Input": CENTROID_SCHEMA,
        "Payload Factor Input": PAYLOAD_SCHEMA,
        "Disaggregated Tonnage Output": TONNAGE_OUTPUT_SCHEMA,
        "Truck Trip Output": TRUCK_OUTPUT_SCHEMA,
        "Assignment OD Output": ASSIGNMENT_OD_SCHEMA,
    }
    lines: list[str] = []
    for title, schema in sections.items():
        lines.append(f"### {title}")
        lines.append("| Column | Description |")
        lines.append("|---|---|")
        for column, description in schema.items():
            lines.append(f"| `{column}` | {description} |")
        lines.append("")
    return "\n".join(lines).strip()


def coerce_subarea_node_map_from_centroids(centroids: pd.DataFrame) -> pd.DataFrame:
    """Use centroid ``node_id`` values as the assignment node map when present."""

    if "node_id" not in centroids.columns:
        raise ValueError("centroids must contain node_id or be mapped to network nodes before assignment export")
    if "subarea_id" not in centroids.columns:
        raise ValueError("centroids must contain subarea_id")
    return centroids[["subarea_id", "node_id"]].dropna().drop_duplicates("subarea_id")


def required_schema_names() -> Iterable[str]:
    """Return schema names for lightweight tests and documentation checks."""

    return (
        "FAF_FLOW_SCHEMA",
        "CROSSWALK_SCHEMA",
        "WEIGHT_SCHEMA",
        "CENTROID_SCHEMA",
        "PAYLOAD_SCHEMA",
        "TONNAGE_OUTPUT_SCHEMA",
        "TRUCK_OUTPUT_SCHEMA",
        "ASSIGNMENT_OD_SCHEMA",
    )
