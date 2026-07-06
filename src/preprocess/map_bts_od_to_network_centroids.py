"""Map BTS county/subcounty freight OD rows to FAF5/NIRD loading centroids.

This preprocessing module treats all OD rows uniformly for the temporary CONUS
run. It does not classify II/IX/XI/XX movements; those can be classified after
network assignment.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

try:
    import geopandas as gpd  # type: ignore
except Exception:  # pragma: no cover - depends on runtime environment.
    gpd = None


LOGGER = logging.getLogger(__name__)
EARTH_RADIUS_MILES = 3958.7613


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result.columns = [str(col).strip() for col in result.columns]
    return result


def _column_lookup(df: pd.DataFrame) -> dict[str, str]:
    return {str(col).strip().lower(): str(col).strip() for col in df.columns}


def _rename_first(df: pd.DataFrame, aliases: Iterable[str], target: str) -> pd.DataFrame:
    lookup = _column_lookup(df)
    for alias in aliases:
        column = lookup.get(alias.lower())
        if column is not None and column != target:
            return df.rename(columns={column: target})
        if column == target:
            return df
    return df


def _as_key(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip()


def _as_zone_id(series: pd.Series) -> pd.Series:
    keys = _as_key(series)
    def normalize(value: object) -> object:
        if value is None or pd.isna(value):
            return pd.NA
        text = str(value).strip()
        if text.endswith(".0") and text[:-2].isdigit():
            text = text[:-2]
        return text.zfill(5) if text.isdigit() and len(text) < 5 else text

    return keys.map(normalize)


def _numeric_or_zero(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(0.0, index=df.index, dtype="float64")
    return pd.to_numeric(df[column], errors="coerce").fillna(0.0).astype(float)


def read_table(path: str | Path) -> pd.DataFrame:
    """Load CSV, parquet, or geospatial input."""

    table_path = Path(path)
    suffix = table_path.suffix.lower()
    if suffix == ".csv":
        return _clean_columns(pd.read_csv(table_path, dtype=str, low_memory=False))
    if suffix in {".pq", ".parquet", ".gpq"}:
        errors: list[str] = []
        if gpd is not None:
            try:
                return _clean_columns(gpd.read_parquet(table_path))
            except Exception as exc:
                errors.append(f"geoparquet: {exc}")
        try:
            return _clean_columns(pd.read_parquet(table_path))
        except Exception as exc:
            errors.append(f"parquet: {exc}")
        if gpd is not None:
            try:
                return _clean_columns(gpd.read_file(table_path))
            except Exception as exc:
                errors.append(f"geopackage: {exc}")
        try:
            return _clean_columns(pd.read_csv(table_path, dtype=str, low_memory=False))
        except Exception as exc:
            errors.append(f"csv: {exc}")
        raise ValueError(
            f"Could not read {table_path} as parquet/geopackage/csv. "
            f"Errors: {' | '.join(errors)}"
        )
    if suffix in {".gpkg", ".geojson", ".shp"}:
        if gpd is None:
            raise ImportError("geopandas is required to read geospatial inputs")
        return _clean_columns(gpd.read_file(table_path))
    raise ValueError(f"Unsupported table format: {table_path}")


def read_network_centroid_table(path: str | Path, layer: str = "FAF5_Nodes") -> pd.DataFrame:
    """Load network loading centroids from a table or FAF5 geodatabase."""

    table_path = Path(path)
    if table_path.suffix.lower() == ".gdb":
        if gpd is None:
            raise ImportError("geopandas is required to read FAF5 geodatabases")
        if table_path.is_dir():
            payload = sum(f.stat().st_size for f in table_path.rglob("*") if f.is_file())
            if payload < 50_000_000:
                raise FileNotFoundError(
                    f"{table_path} appears incomplete ({payload / 1_048_576:.2f} MB). "
                    "Replace it with the full FAF5Network.gdb download, or pass an exported "
                    "centroid parquet via --network-centroids / NIRD_FAF5_NETWORK_CENTROIDS_PATH."
                )
        errors: list[str] = []
        for engine in ("pyogrio", "fiona"):
            try:
                centroids = gpd.read_file(table_path, layer=layer, engine=engine, where="Centroid = 1")
                return _clean_columns(centroids)
            except Exception as exc:
                errors.append(f"{engine}: {exc}")
        try:
            nodes = gpd.read_file(table_path, layer=layer, engine="pyogrio")
            if "Centroid" not in nodes.columns:
                raise ValueError(f"{table_path} layer {layer!r} does not contain a Centroid column")
            centroids = nodes[nodes["Centroid"] == 1].copy()
            return _clean_columns(centroids)
        except Exception as exc:
            errors.append(f"pyogrio-unfiltered: {exc}")
        raise FileNotFoundError(
            f"Could not open {table_path}. GDAL errors: {' | '.join(errors)}"
        )
    return read_table(table_path)


def _resolve_year_column(df: pd.DataFrame, base_name: str, year: int | str | None) -> str | None:
    lookup = _column_lookup(df)
    direct = lookup.get(base_name.lower())
    if direct is not None:
        return direct
    if year is not None:
        yearly = lookup.get(f"{base_name}_{year}".lower())
        if yearly is not None:
            return yearly
    candidates = [col for col in df.columns if str(col).lower().startswith(f"{base_name}_")]
    return candidates[0] if candidates else None


def normalize_bts_od(
    od: pd.DataFrame,
    year: int | str | None = None,
    default_payload_tons: float | None = None,
) -> pd.DataFrame:
    """Normalize BTS county/subcounty OD aliases to mapper columns."""

    df = _clean_columns(od)
    df = _rename_first(
        df,
        ["origin_detail_zone", "origin_zone", "origin_county", "orig_county", "dms_orig_cnty", "dms_orig_c"],
        "origin_detail_zone",
    )
    df = _rename_first(
        df,
        [
            "destination_detail_zone",
            "destination_zone",
            "destination_county",
            "dest_county",
            "dms_dest_cnty",
            "dms_dest_c",
        ],
        "destination_detail_zone",
    )
    df = _rename_first(df, ["sctgG5", "sctgg5", "commodity_group"], "sctgG5")
    df = _rename_first(df, ["dms_mode", "mode"], "mode")
    df = _rename_first(df, ["annual_truck_trips", "truck_trips_annual"], "annual_truck_trips")
    df = _rename_first(df, ["daily_truck_trips", "truck_trips_daily", "Car21"], "daily_truck_trips")

    tons_col = _resolve_year_column(df, "annual_tons", year) or _resolve_year_column(df, "tons", year)
    value_col = _resolve_year_column(df, "value", year)
    required = {"origin_detail_zone", "destination_detail_zone"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"BTS OD table is missing required columns: {sorted(missing)}")
    if tons_col is None:
        raise ValueError("BTS OD table must contain tons, tons_YEAR, annual_tons, or annual_tons_YEAR")

    result = pd.DataFrame(
        {
            "origin_detail_zone": _as_zone_id(df["origin_detail_zone"]),
            "destination_detail_zone": _as_zone_id(df["destination_detail_zone"]),
            "sctgG5": _as_key(df["sctgG5"]) if "sctgG5" in df.columns else "all",
            "mode": _as_key(df["mode"]) if "mode" in df.columns else "all",
            "year": int(year) if year is not None else (pd.to_numeric(df["year"], errors="coerce") if "year" in df.columns else 0),
            "annual_tons": pd.to_numeric(df[tons_col], errors="coerce").fillna(0.0).astype(float),
            "value": pd.to_numeric(df[value_col], errors="coerce").fillna(0.0).astype(float) if value_col else 0.0,
            "annual_truck_trips": _numeric_or_zero(df, "annual_truck_trips"),
            "daily_truck_trips": _numeric_or_zero(df, "daily_truck_trips"),
        }
    )
    result["daily_tons"] = result["annual_tons"] / 365.0
    missing_daily_trips = (result["daily_truck_trips"] <= 0) & (result["annual_truck_trips"] > 0)
    result.loc[missing_daily_trips, "daily_truck_trips"] = result.loc[missing_daily_trips, "annual_truck_trips"] / 365.0
    missing_annual_trips = (result["annual_truck_trips"] <= 0) & (result["daily_truck_trips"] > 0)
    result.loc[missing_annual_trips, "annual_truck_trips"] = result.loc[missing_annual_trips, "daily_truck_trips"] * 365.0
    if default_payload_tons is not None:
        missing_trips = (result["annual_truck_trips"] <= 0) & (result["annual_tons"] > 0)
        result.loc[missing_trips, "annual_truck_trips"] = (
            result.loc[missing_trips, "annual_tons"] / float(default_payload_tons)
        )
        result.loc[missing_trips, "daily_truck_trips"] = (
            result.loc[missing_trips, "annual_truck_trips"] / 365.0
        )
    return result[result["annual_tons"] > 0].reset_index(drop=True)


def _extract_lon_lat(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    result = _clean_columns(df)
    result = _rename_first(result, ["lon", "longitude", "x"], "lon")
    result = _rename_first(result, ["lat", "latitude", "y"], "lat")
    if {"lon", "lat"}.issubset(result.columns):
        result["lon"] = pd.to_numeric(result["lon"], errors="coerce")
        result["lat"] = pd.to_numeric(result["lat"], errors="coerce")
        return result
    if "geometry" in result.columns and gpd is not None:
        gdf = result if isinstance(result, gpd.GeoDataFrame) else gpd.GeoDataFrame(result, geometry="geometry")
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        gdf = gdf.to_crs("EPSG:4326")
        point_geometry = gdf.geometry
        if not point_geometry.geom_type.isin(["Point", "MultiPoint"]).all():
            projected = gdf.to_crs("EPSG:5070")
            point_geometry = projected.geometry.centroid.to_crs("EPSG:4326")
        result = pd.DataFrame(gdf.drop(columns="geometry"))
        result["lon"] = point_geometry.x
        result["lat"] = point_geometry.y
        return result
    raise ValueError(f"{table_name} must contain lon/lat, x/y, or geometry")


def normalize_detail_zone_centroids(detail_centroids: pd.DataFrame) -> pd.DataFrame:
    """Normalize BTS detail-zone centroids."""

    df = _extract_lon_lat(detail_centroids, "detail_zone_centroids")
    df = _rename_first(
        df,
        ["detail_zone_id", "zone_id", "county_id", "geoid", "GEOID", "origin_detail_zone", "countyfp"],
        "detail_zone_id",
    )
    if "detail_zone_id" not in df.columns:
        raise ValueError("detail zone centroid table must contain a detail zone ID column")
    result = df[["detail_zone_id", "lon", "lat"]].copy()
    result["detail_zone_id"] = _as_zone_id(result["detail_zone_id"])
    return result.dropna(subset=["lon", "lat"]).drop_duplicates("detail_zone_id")


def normalize_network_centroids(network_centroids: pd.DataFrame) -> pd.DataFrame:
    """Normalize network loading centroid IDs, node IDs, and coordinates."""

    df = _extract_lon_lat(network_centroids, "network_centroids")
    df = _rename_first(df, ["centroid_id", "CentroidID", "FAFID", "fafid"], "centroid_id")
    df = _rename_first(df, ["node_id", "ID", "id", "DATA"], "node_id")
    if "centroid_id" not in df.columns:
        raise ValueError("network centroid table must contain centroid_id, CentroidID, or FAFID")
    if "node_id" not in df.columns:
        raise ValueError("network centroid table must contain node_id, ID, id, or DATA")
    result = df[["centroid_id", "node_id", "lon", "lat"]].copy()
    result["centroid_id"] = _as_key(result["centroid_id"])
    result["node_id"] = _as_key(result["node_id"])
    return result.dropna(subset=["lon", "lat"]).drop_duplicates("centroid_id")


def map_network_centroids_to_assignment_nodes(
    network_centroids: pd.DataFrame,
    network_nodes: pd.DataFrame,
    target_crs: str = "EPSG:2163",
) -> pd.DataFrame:
    """Replace centroid node IDs with nearest NIRD assignment-node IDs."""

    if gpd is None:
        raise ImportError("geopandas is required to nearest-map centroids to assignment nodes")

    centroids = normalize_network_centroids(network_centroids)
    nodes = _extract_lon_lat(network_nodes, "network_nodes")
    nodes = _rename_first(nodes, ["node_id", "ID", "id"], "node_id")
    if "node_id" not in nodes.columns:
        raise ValueError("network node table must contain node_id, ID, or id")

    centroid_gdf = gpd.GeoDataFrame(
        centroids.drop(columns=["node_id"]).copy(),
        geometry=gpd.points_from_xy(centroids["lon"], centroids["lat"]),
        crs="EPSG:4326",
    ).to_crs(target_crs)
    node_gdf = gpd.GeoDataFrame(
        nodes[["node_id", "lon", "lat"]].copy(),
        geometry=gpd.points_from_xy(nodes["lon"], nodes["lat"]),
        crs="EPSG:4326",
    ).to_crs(target_crs)
    nearest = gpd.sjoin_nearest(
        centroid_gdf,
        node_gdf[["node_id", "geometry"]],
        how="left",
        distance_col="_node_distance_m",
    )
    result = pd.DataFrame(nearest.drop(columns=["geometry", "index_right"], errors="ignore"))
    result["node_id"] = _as_key(result["node_id"])
    result["lon"] = centroids.set_index("centroid_id").loc[result["centroid_id"], "lon"].to_numpy()
    result["lat"] = centroids.set_index("centroid_id").loc[result["centroid_id"], "lat"].to_numpy()
    return result[["centroid_id", "node_id", "lon", "lat", "_node_distance_m"]].drop_duplicates("centroid_id")


def _haversine_miles(lon: float, lat: float, lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    lon1 = np.radians(float(lon))
    lat1 = np.radians(float(lat))
    lon2 = np.radians(lons.astype(float))
    lat2 = np.radians(lats.astype(float))
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def build_detail_zone_crosswalk(
    detail_zones: Iterable[object],
    network_centroids: pd.DataFrame,
    detail_zone_centroids: pd.DataFrame | None = None,
    exact_match_columns: tuple[str, str] = ("detail_zone_id", "centroid_id"),
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Assign every BTS detail zone to a network loading centroid."""

    zones = pd.Series(sorted({_as_zone_id(pd.Series([zone])).iloc[0] for zone in detail_zones}), dtype="string")
    network = normalize_network_centroids(network_centroids)
    crosswalk = pd.DataFrame({"detail_zone_id": zones})

    left_col, right_col = exact_match_columns
    if left_col != "detail_zone_id":
        raise ValueError("detail-zone exact match column must normalize to detail_zone_id")
    exact_lookup = network[["centroid_id", "node_id"]].copy()
    exact_lookup["detail_zone_id"] = _as_zone_id(network[right_col])
    exact_lookup = exact_lookup[["detail_zone_id", "centroid_id", "node_id"]]
    exact_lookup["detail_zone_id"] = _as_zone_id(exact_lookup["detail_zone_id"])
    crosswalk = crosswalk.merge(exact_lookup, on="detail_zone_id", how="left")
    crosswalk["assignment_method"] = np.where(crosswalk["centroid_id"].notna(), "exact_match", pd.NA)
    crosswalk["distance_miles"] = np.where(crosswalk["centroid_id"].notna(), 0.0, np.nan)

    unmatched_mask = crosswalk["centroid_id"].isna()
    unmatched_before_fallback = int(unmatched_mask.sum())
    if unmatched_before_fallback:
        if detail_zone_centroids is None:
            raise ValueError(
                f"{unmatched_before_fallback:,} detail zones did not exact-match network centroids; "
                "provide detail-zone centroids for nearest-loading-node fallback"
            )
        detail = normalize_detail_zone_centroids(detail_zone_centroids)
        network_lons = network["lon"].to_numpy(dtype=float)
        network_lats = network["lat"].to_numpy(dtype=float)
        network_centroid_ids = network["centroid_id"].to_numpy()
        network_node_ids = network["node_id"].to_numpy()
        detail_lookup = detail.set_index("detail_zone_id")

        for idx in crosswalk.index[unmatched_mask]:
            zone_id = crosswalk.at[idx, "detail_zone_id"]
            if zone_id not in detail_lookup.index:
                continue
            zone = detail_lookup.loc[zone_id]
            distances = _haversine_miles(float(zone["lon"]), float(zone["lat"]), network_lons, network_lats)
            nearest_idx = int(np.nanargmin(distances))
            crosswalk.at[idx, "centroid_id"] = network_centroid_ids[nearest_idx]
            crosswalk.at[idx, "node_id"] = network_node_ids[nearest_idx]
            crosswalk.at[idx, "assignment_method"] = "nearest_loading_node"
            crosswalk.at[idx, "distance_miles"] = float(distances[nearest_idx])

    crosswalk = crosswalk.rename(columns={"centroid_id": "assigned_centroid", "node_id": "assigned_node_id"})
    crosswalk["warning_flag"] = ""
    crosswalk.loc[crosswalk["assigned_centroid"].isna(), "warning_flag"] = "unmapped"
    crosswalk.loc[
        crosswalk["assigned_centroid"].notna() & (pd.to_numeric(crosswalk["distance_miles"], errors="coerce") > 50.0),
        "warning_flag",
    ] = "distance_gt_50_miles"
    crosswalk.loc[
        (crosswalk["warning_flag"] == "")
        & crosswalk["assigned_centroid"].notna()
        & (pd.to_numeric(crosswalk["distance_miles"], errors="coerce") > 25.0),
        "warning_flag",
    ] = "distance_gt_25_miles"
    summary = {
        "detail_zones": int(len(crosswalk)),
        "unmatched_before_nearest_fallback": unmatched_before_fallback,
        "unmapped_after_fallback": int(crosswalk["assigned_centroid"].isna().sum()),
        "mappings_beyond_25_miles": int((pd.to_numeric(crosswalk["distance_miles"], errors="coerce") > 25.0).sum()),
        "mappings_beyond_50_miles": int((pd.to_numeric(crosswalk["distance_miles"], errors="coerce") > 50.0).sum()),
    }
    return crosswalk[
        [
            "detail_zone_id",
            "assigned_centroid",
            "assigned_node_id",
            "assignment_method",
            "distance_miles",
            "warning_flag",
        ]
    ], summary


def aggregate_od_to_network_centroids(
    od: pd.DataFrame,
    crosswalk: pd.DataFrame,
    default_payload_tons: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Map BTS OD rows to centroids and aggregate demand."""

    normalized_od = normalize_bts_od(od, default_payload_tons=default_payload_tons)
    cw = crosswalk.copy()
    cw["detail_zone_id"] = _as_zone_id(cw["detail_zone_id"])
    origin_cw = cw.rename(
        columns={
            "detail_zone_id": "origin_detail_zone",
            "assigned_centroid": "origin_centroid",
            "assigned_node_id": "origin_node",
        }
    )[["origin_detail_zone", "origin_centroid", "origin_node"]]
    dest_cw = cw.rename(
        columns={
            "detail_zone_id": "destination_detail_zone",
            "assigned_centroid": "destination_centroid",
            "assigned_node_id": "destination_node",
        }
    )[["destination_detail_zone", "destination_centroid", "destination_node"]]
    mapped = normalized_od.merge(origin_cw, on="origin_detail_zone", how="left").merge(
        dest_cw,
        on="destination_detail_zone",
        how="left",
    )
    mapped = mapped.dropna(subset=["origin_centroid", "destination_centroid"])
    grouped = mapped.groupby(
        [
            "origin_detail_zone",
            "destination_detail_zone",
            "origin_centroid",
            "destination_centroid",
            "origin_node",
            "destination_node",
            "sctgG5",
            "mode",
            "year",
        ],
        as_index=False,
        dropna=False,
    ).agg(
        annual_tons=("annual_tons", "sum"),
        daily_tons=("daily_tons", "sum"),
        value=("value", "sum"),
        annual_truck_trips=("annual_truck_trips", "sum"),
        daily_truck_trips=("daily_truck_trips", "sum"),
    )
    grouped["Car21"] = grouped["daily_truck_trips"]
    return grouped, mapped


def validation_summary(
    input_od: pd.DataFrame,
    mapped_od: pd.DataFrame,
    crosswalk: pd.DataFrame,
    default_payload_tons: float | None = None,
) -> dict[str, object]:
    """Build validation checks for the centroid mapping run."""

    original = normalize_bts_od(input_od, default_payload_tons=default_payload_tons)
    distance = pd.to_numeric(crosswalk["distance_miles"], errors="coerce")
    return {
        "total_tons_before_mapping": float(original["annual_tons"].sum()),
        "total_tons_after_mapping": float(mapped_od["annual_tons"].sum()) if "annual_tons" in mapped_od else 0.0,
        "total_truck_trips_before_mapping": float(original["daily_truck_trips"].sum()),
        "total_truck_trips_after_mapping": float(mapped_od["daily_truck_trips"].sum()) if "daily_truck_trips" in mapped_od else 0.0,
        "unique_bts_origin_zones": int(original["origin_detail_zone"].nunique()),
        "unique_bts_destination_zones": int(original["destination_detail_zone"].nunique()),
        "unique_network_centroids_used": int(
            pd.concat([mapped_od["origin_centroid"], mapped_od["destination_centroid"]]).nunique()
        )
        if not mapped_od.empty
        else 0,
        "unmatched_zones_before_nearest_fallback": int((crosswalk["assignment_method"] == "nearest_loading_node").sum()),
        "mappings_beyond_25_miles": int((distance > 25.0).sum()),
        "mappings_beyond_50_miles": int((distance > 50.0).sum()),
        "centroid_intrazonal_od_rows": int((mapped_od["origin_centroid"] == mapped_od["destination_centroid"]).sum())
        if not mapped_od.empty
        else 0,
        "ii_ix_xi_xx_classification_applied": False,
    }


def write_table(df: pd.DataFrame, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower()
    if suffix in {".pq", ".parquet", ".gpq"}:
        if gpd is not None and isinstance(df, gpd.GeoDataFrame):
            df.to_parquet(output_path, index=False)
        elif gpd is not None and "geometry" in df.columns:
            gpd.GeoDataFrame(df).to_parquet(output_path, index=False)
        else:
            pd.DataFrame(df).to_parquet(output_path, index=False)
    else:
        df.to_csv(output_path, index=False)
    return output_path


def map_county_od_via_county_shp(
    county_od: pd.DataFrame,
    county_shp_path: str | Path,
    network_nodes_path: str | Path,
    *,
    default_payload_tons: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """Map county OD rows to assignment nodes using county centroids and nearest network nodes."""

    if gpd is None:
        raise ImportError("geopandas is required for county-shapefile mapping")

    od = normalize_bts_od(county_od, default_payload_tons=default_payload_tons)
    counties = gpd.read_file(county_shp_path)
    if "GEOID" not in counties.columns:
        raise ValueError(f"{county_shp_path} must contain GEOID")
    counties = counties.assign(county_id=_as_zone_id(counties["GEOID"])).to_crs("EPSG:2163")
    county_pts = counties[["county_id", "geometry"]].copy()
    county_pts["geometry"] = county_pts.geometry.centroid

    nodes = read_table(network_nodes_path)
    if "geometry" not in nodes.columns:
        raise ValueError(f"{network_nodes_path} must contain geometry")
    node_gdf = nodes if isinstance(nodes, gpd.GeoDataFrame) else gpd.GeoDataFrame(nodes, geometry="geometry")
    if node_gdf.crs is None:
        node_gdf = node_gdf.set_crs("EPSG:4326")
    node_gdf = node_gdf.to_crs("EPSG:2163")
    node_gdf = _rename_first(node_gdf, ["node_id", "ID", "id"], "node_id")

    nearest = gpd.sjoin_nearest(
        county_pts,
        node_gdf[["node_id", "geometry"]],
        how="left",
        distance_col="distance_m",
    )
    node_map = nearest[["county_id", "node_id", "distance_m"]].drop_duplicates("county_id")

    mapped = od.copy()
    mapped["origin_detail_zone"] = _as_zone_id(mapped["origin_detail_zone"])
    mapped["destination_detail_zone"] = _as_zone_id(mapped["destination_detail_zone"])
    mapped = mapped.merge(
        node_map.rename(columns={"county_id": "origin_detail_zone", "node_id": "origin_node"}),
        on="origin_detail_zone",
        how="inner",
    )
    mapped = mapped.merge(
        node_map.rename(columns={"county_id": "destination_detail_zone", "node_id": "destination_node"}),
        on="destination_detail_zone",
        how="inner",
    )
    grouped = mapped.groupby(
        ["origin_node", "destination_node", "sctgG5", "mode", "year"],
        as_index=False,
        dropna=False,
    ).agg(
        annual_tons=("annual_tons", "sum"),
        daily_tons=("daily_tons", "sum"),
        value=("value", "sum"),
        annual_truck_trips=("annual_truck_trips", "sum"),
        daily_truck_trips=("daily_truck_trips", "sum"),
    )
    grouped["Car21"] = grouped["daily_truck_trips"]
    summary = {
        "mapping_method": "county_shapefile_nearest_node",
        "county_rows_mapped": int(len(mapped)),
        "assignment_rows_by_sctg": int(len(grouped)),
        "counties_in_crosswalk": int(len(node_map)),
        "unmapped_counties": int(node_map["node_id"].isna().sum()),
    }
    return grouped, node_map, summary


def run_mapping(
    bts_od_path: str | Path,
    network_centroids_path: str | Path,
    output_od_path: str | Path = "data/processed/faf5_bts_conus_centroid_od.csv",
    output_crosswalk_path: str | Path = "data/processed/bts_detail_zone_to_network_centroid_crosswalk.csv",
    detail_centroids_path: str | Path | None = None,
    network_nodes_path: str | Path | None = None,
    summary_json_path: str | Path | None = None,
    year: int | str | None = None,
    default_payload_tons: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """Run the BTS detail-zone to network-centroid mapping workflow."""

    od = normalize_bts_od(read_table(bts_od_path), year=year, default_payload_tons=default_payload_tons)
    network_centroids = read_network_centroid_table(network_centroids_path)
    if network_nodes_path is not None:
        network_centroids = map_network_centroids_to_assignment_nodes(
            network_centroids,
            read_table(network_nodes_path),
        )
    detail_centroids = read_table(detail_centroids_path) if detail_centroids_path else None
    detail_zones = pd.concat([od["origin_detail_zone"], od["destination_detail_zone"]]).dropna().unique()
    crosswalk, crosswalk_summary = build_detail_zone_crosswalk(detail_zones, network_centroids, detail_centroids)
    centroid_od, mapped_rows = aggregate_od_to_network_centroids(
        od,
        crosswalk,
        default_payload_tons=default_payload_tons,
    )
    summary = validation_summary(od, mapped_rows, crosswalk, default_payload_tons=default_payload_tons)
    summary.update(crosswalk_summary)
    summary["output_od_path"] = str(output_od_path)
    summary["output_crosswalk_path"] = str(output_crosswalk_path)
    summary["network_centroids_path"] = str(network_centroids_path)
    summary["network_nodes_path"] = str(network_nodes_path) if network_nodes_path else None
    summary["default_payload_tons"] = default_payload_tons

    write_table(crosswalk, output_crosswalk_path)
    write_table(centroid_od, output_od_path)
    if summary_json_path:
        summary_path = Path(summary_json_path)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return centroid_od, crosswalk, summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Map BTS county/subcounty OD to FAF5/NIRD loading centroids")
    parser.add_argument("--bts-od", required=True, help="BTS experimental county/subcounty OD CSV/parquet")
    parser.add_argument(
        "--network-centroids",
        required=True,
        help="FAF5/NIRD network centroid/loading node table, or FAF5Network.gdb",
    )
    parser.add_argument(
        "--network-nodes",
        default=None,
        help="Optional NIRD road node table; nearest-maps loading centroids to assignment node IDs.",
    )
    parser.add_argument("--detail-centroids", default=None, help="Optional BTS detail-zone centroid table")
    parser.add_argument("--output-od", default="data/processed/faf5_bts_conus_centroid_od.csv")
    parser.add_argument(
        "--output-crosswalk",
        default="data/processed/bts_detail_zone_to_network_centroid_crosswalk.csv",
    )
    parser.add_argument("--summary-json", default="data/processed/faf5_bts_conus_centroid_od_summary.json")
    parser.add_argument("--year", default=None, help="Optional year for tons_YEAR/value_YEAR inputs")
    parser.add_argument(
        "--default-payload-tons",
        type=float,
        default=None,
        help="Optional tons-per-truck fallback when BTS OD has no truck-trip columns.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    args = build_arg_parser().parse_args(argv)
    centroid_od, crosswalk, summary = run_mapping(
        bts_od_path=args.bts_od,
        network_centroids_path=args.network_centroids,
        network_nodes_path=args.network_nodes,
        detail_centroids_path=args.detail_centroids,
        output_od_path=args.output_od,
        output_crosswalk_path=args.output_crosswalk,
        summary_json_path=args.summary_json,
        year=args.year,
        default_payload_tons=args.default_payload_tons,
    )
    LOGGER.info("Wrote %s centroid OD rows to %s", f"{len(centroid_od):,}", args.output_od)
    LOGGER.info("Wrote %s crosswalk rows to %s", f"{len(crosswalk):,}", args.output_crosswalk)
    LOGGER.info("Validation summary: %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
