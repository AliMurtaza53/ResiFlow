"""Build CONUS county OD by SCTG G5 and map to FAF5 assignment centroids.

Pipeline:
  1. FAF5 regional OD + BTS county disaggregation factors -> county OD by sctgG5
  2. County OD -> network loading centroids (preserving sctgG5)
  3. Collapsed assignment OD for Script 1 + commodity-specific OD sidecar
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
for path in (REPO_ROOT / "src", SCRIPTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from resiflow.faf5_conus_county_od import run_conus_county_od_by_sctg
from resiflow.faf5_paths import resolve_faf5_data_root, resolve_regional_od_path, truck_factor_paths
from resiflow.geo_runtime import configure_geo_runtime
from resiflow.utils import load_config
from preprocess.map_bts_od_to_network_centroids import map_county_od_via_county_shp, run_mapping

LOGGER = logging.getLogger(__name__)


def collapse_assignment_od(centroid_od: pd.DataFrame) -> pd.DataFrame:
    """Sum commodity-specific centroid OD to Script 1 assignment schema."""

    flow_col = "Car21" if "Car21" in centroid_od.columns else "daily_truck_trips"
    grouped = (
        centroid_od.groupby(["origin_node", "destination_node"], as_index=False)[flow_col]
        .sum()
        .rename(columns={flow_col: "Car21"})
    )
    grouped["Car21"] = pd.to_numeric(grouped["Car21"], errors="coerce").fillna(0.0)
    return grouped[grouped["Car21"] > 0].reset_index(drop=True)


def write_parquet(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def build_conus_freight_od(
    base_path: Path,
    *,
    year: int = 2022,
    force_county: bool = False,
    force_centroid: bool = False,
    skip_county: bool = False,
    require_gdb: bool = False,
    network_centroids_path: str | None = None,
    default_payload_tons: float = 20.0,
    read_chunksize: int = 50_000,
    od_chunk_size: int = 500,
) -> dict[str, str]:
    faf5_root = resolve_faf5_data_root(base_path, REPO_ROOT)
    if faf5_root is None:
        raise FileNotFoundError("Could not resolve faf5_data root (expected sibling of soge_clusters).")

    regional_od = resolve_regional_od_path(faf5_root)
    if regional_od is None:
        raise FileNotFoundError(f"No regional FAF OD found under {faf5_root}")

    origin_factors, destination_factors = truck_factor_paths(faf5_root)
    processed = faf5_root / "processed"
    processed.mkdir(parents=True, exist_ok=True)

    county_od_path = processed / f"faf5_county_truck_od_usa_{year}_by_sctg.parquet"
    centroid_od_path = processed / f"faf5_bts_conus_centroid_od_{year}_by_sctg.parquet"
    crosswalk_path = processed / f"bts_county_to_network_centroid_crosswalk_{year}.csv"
    county_summary_path = processed / f"faf5_county_truck_od_usa_{year}_by_sctg_summary.json"
    centroid_summary_path = processed / f"faf5_bts_conus_centroid_od_{year}_by_sctg_summary.json"

    census_dir = base_path / "census_datasets"
    census_dir.mkdir(parents=True, exist_ok=True)
    county_dest = census_dir / "faf5_county_od.pq"
    assignment_by_sctg_dest = census_dir / "faf5_od_matrix_by_sctg.pq"
    assignment_dest = census_dir / "faf5_od_matrix.pq"

    network_gdb = faf5_root / "network_data" / "FAF5Network.gdb"
    network_nodes = base_path / "networks" / "faf5" / "faf5_road_nodes.gpq"
    centroids_override = network_centroids_path or os.getenv("NIRD_FAF5_NETWORK_CENTROIDS_PATH")
    network_centroids = Path(centroids_override) if centroids_override else network_gdb
    if not network_centroids.exists():
        raise FileNotFoundError(f"Missing network centroids source: {network_centroids}")
    if not network_nodes.exists():
        raise FileNotFoundError(f"Missing NIRD road nodes: {network_nodes}")

    county_shp = faf5_root / "county_shp" / "tl_2022_us_county.shp"

    if skip_county and not county_od_path.exists():
        raise FileNotFoundError(f"--skip-county set but county OD missing: {county_od_path}")
    elif force_county or not county_od_path.exists():
        LOGGER.info("Building county OD by sctgG5 from %s", regional_od)
        _, county_summary = run_conus_county_od_by_sctg(
            regional_od,
            origin_factors,
            destination_factors,
            county_od_path,
            year=year,
            read_chunksize=read_chunksize,
            od_chunk_size=od_chunk_size,
            default_payload_tons=default_payload_tons,
        )
        county_summary_path.write_text(json.dumps(county_summary, indent=2), encoding="utf-8")
    else:
        LOGGER.info("Reusing existing county OD: %s", county_od_path)

    if force_centroid or not centroid_od_path.exists():
        LOGGER.info("Mapping county OD to network nodes")
        county_od = pd.read_parquet(county_od_path)
        detail_centroids_path = county_shp if county_shp.exists() else None
        try:
            centroid_od, _, centroid_summary = run_mapping(
                bts_od_path=county_od_path,
                network_centroids_path=network_centroids,
                network_nodes_path=network_nodes,
                detail_centroids_path=detail_centroids_path,
                output_od_path=centroid_od_path,
                output_crosswalk_path=crosswalk_path,
                summary_json_path=centroid_summary_path,
                year=year,
                default_payload_tons=default_payload_tons,
            )
            centroid_summary["mapping_method"] = "faf5_loading_centroids"
        except Exception as exc:
            if require_gdb:
                raise
            if not county_shp.exists():
                raise
            LOGGER.warning("FAF5 centroid mapping failed (%s); using county-shapefile nearest-node fallback", exc)
            centroid_od, node_map, centroid_summary = map_county_od_via_county_shp(
                county_od,
                county_shp,
                network_nodes,
                default_payload_tons=default_payload_tons,
            )
            write_parquet(node_map, crosswalk_path.with_suffix(".parquet"))
            crosswalk_path.with_suffix(".csv").write_text(node_map.to_csv(index=False), encoding="utf-8")
            write_parquet(centroid_od, centroid_od_path)
            centroid_summary_path.write_text(json.dumps(centroid_summary, indent=2), encoding="utf-8")
    else:
        LOGGER.info("Reusing existing centroid OD: %s", centroid_od_path)
        centroid_od = pd.read_parquet(centroid_od_path)

    assignment_by_sctg = centroid_od.copy()
    if "Car21" not in assignment_by_sctg.columns and "daily_truck_trips" in assignment_by_sctg.columns:
        assignment_by_sctg["Car21"] = assignment_by_sctg["daily_truck_trips"]
    assignment_od = collapse_assignment_od(assignment_by_sctg)

    write_parquet(pd.read_parquet(county_od_path), county_dest)
    write_parquet(assignment_by_sctg, assignment_by_sctg_dest)
    write_parquet(assignment_od, assignment_dest)

    outputs = {
        "regional_od": str(regional_od),
        "county_od_by_sctg": str(county_od_path),
        "centroid_od_by_sctg": str(centroid_od_path),
        "crosswalk": str(crosswalk_path),
        "faf5_county_od": str(county_dest),
        "faf5_od_matrix_by_sctg": str(assignment_by_sctg_dest),
        "faf5_od_matrix": str(assignment_dest),
    }
    manifest_path = base_path / "tables" / "conus_freight_od_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"year": year, "default_payload_tons": default_payload_tons, **outputs}, indent=2),
        encoding="utf-8",
    )
    LOGGER.info("Wrote assignment OD rows: %s", f"{len(assignment_od):,}")
    LOGGER.info("Wrote commodity-specific OD rows: %s", f"{len(assignment_by_sctg):,}")

    from build_faf5_sctg_summary import build_sctg_summary

    build_sctg_summary(base_path, REPO_ROOT, county_od_path=str(county_dest), year=year)
    outputs["faf5_sctg_daily_trucks"] = str(census_dir / "faf5_sctg_daily_trucks.pq")
    return outputs


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2022)
    parser.add_argument("--force-county", action="store_true")
    parser.add_argument("--skip-county", action="store_true")
    parser.add_argument("--require-gdb", action="store_true", help="Fail instead of county-shapefile fallback")
    parser.add_argument("--network-centroids", default=None, help="Exported FAF5 loading centroids gpq/parquet")
    parser.add_argument("--force-centroid", action="store_true")
    parser.add_argument("--default-payload-tons", type=float, default=20.0)
    parser.add_argument("--read-chunksize", type=int, default=50_000)
    parser.add_argument("--od-chunk-size", type=int, default=500)
    args = parser.parse_args()

    configure_geo_runtime()
    config = load_config()
    base_path = Path(config["paths"]["soge_clusters"])
    outputs = build_conus_freight_od(
        base_path,
        year=args.year,
        force_county=args.force_county,
        force_centroid=args.force_centroid,
        skip_county=args.skip_county,
        require_gdb=args.require_gdb,
        network_centroids_path=args.network_centroids,
        default_payload_tons=args.default_payload_tons,
        read_chunksize=args.read_chunksize,
        od_chunk_size=args.od_chunk_size,
    )
    for key, value in outputs.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
