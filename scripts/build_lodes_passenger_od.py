"""Build county-to-county LODES passenger OD and map to network assignment nodes.

Pipeline:
  1. LODES block OD (main + aux per state) + geographic crosswalk -> county OD
  2. County OD -> FAF5 loading centroids / road nodes (same paths as freight)
  3. Collapsed assignment OD for Script 1 (vehicle_type=car, merged with freight)
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
for path in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from resiflow.faf5_paths import resolve_faf5_data_root
from resiflow.geo_runtime import configure_geo_runtime
from resiflow.lodes_county_od import county_od_to_assignment_schema, run_lodes_county_od
from resiflow.lodes_paths import CONUS_STATE_ABBRS, resolve_lodes_data_root
from resiflow.utils import load_config
from preprocess.map_bts_od_to_network_centroids import map_county_od_via_county_shp, run_mapping

LOGGER = logging.getLogger(__name__)


def collapse_passenger_assignment_od(centroid_od: pd.DataFrame) -> pd.DataFrame:
    """Sum county-mapped passenger flows to Script 1 assignment schema."""
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


def build_lodes_passenger_od(
    base_path: Path,
    *,
    year: int = 2022,
    job_type: str = "JT00",
    states: list[str] | None = None,
    force_county: bool = False,
    force_centroid: bool = False,
    skip_centroid: bool = False,
    resume: bool = True,
    network_centroids_path: str | None = None,
) -> dict[str, str]:
    faf5_root = resolve_faf5_data_root(base_path, REPO_ROOT)
    if faf5_root is None:
        raise FileNotFoundError("Could not resolve faf5_data root.")

    lodes_root = resolve_lodes_data_root(base_path, REPO_ROOT) or (base_path.parent / "lodes_data")
    processed = Path(lodes_root) / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    census_dir = base_path / "census_datasets"
    census_dir.mkdir(parents=True, exist_ok=True)

    county_od_path = processed / f"lodes_county_od_{job_type.lower()}_{year}.parquet"
    centroid_od_path = processed / f"lodes_passenger_centroid_od_{job_type.lower()}_{year}.parquet"
    assignment_od_path = processed / f"lodes_passenger_assignment_od_{job_type.lower()}_{year}.parquet"
    county_dest = census_dir / f"lodes_county_od_{job_type.lower()}_{year}.pq"
    assignment_dest = census_dir / "lodes_passenger_od_matrix.pq"
    summary_path = processed / f"lodes_county_od_{job_type.lower()}_{year}_summary.json"

    requested_states = {s.lower() for s in (states or list(CONUS_STATE_ABBRS))}
    if county_od_path.exists() and not force_county and summary_path.exists():
        try:
            prior = json.loads(summary_path.read_text(encoding="utf-8"))
            prior_states = {str(s).lower() for s in prior.get("states", [])}
            if prior_states != requested_states:
                LOGGER.warning(
                    "Existing county OD covers %s states but %s requested; rebuilding county OD.",
                    len(prior_states),
                    len(requested_states),
                )
                force_county = True
                force_centroid = True
        except (json.JSONDecodeError, OSError):
            pass

    if force_county or not county_od_path.exists():
        LOGGER.info("Building CONUS LODES county OD -> %s", county_od_path)
        run_lodes_county_od(
            county_od_path,
            states=states or list(CONUS_STATE_ABBRS),
            job_type=job_type,
            year=year,
            base_path=base_path,
            repo_root=REPO_ROOT,
            parts_dir=processed / "state_parts",
            resume=resume and not force_county,
            summary_json_path=summary_path,
        )
    else:
        LOGGER.info("Reusing existing county OD: %s", county_od_path)

    write_parquet(pd.read_parquet(county_od_path), county_dest)

    outputs: dict[str, str] = {
        "county_od": str(county_od_path),
        "lodes_county_od_pq": str(county_dest),
        "centroid_od": str(centroid_od_path),
        "assignment_od": str(assignment_od_path),
    }

    if skip_centroid:
        return outputs

    network_gdb = faf5_root / "network_data" / "FAF5Network.gdb"
    network_nodes = base_path / "networks" / "faf5" / "faf5_road_nodes.gpq"
    centroids_override = network_centroids_path or os.getenv("NIRD_FAF5_NETWORK_CENTROIDS_PATH")
    network_centroids = Path(centroids_override) if centroids_override else network_gdb
    if not network_centroids.exists():
        raise FileNotFoundError(f"Missing network centroids source: {network_centroids}")
    if not network_nodes.exists():
        raise FileNotFoundError(f"Missing NIRD road nodes: {network_nodes}")

    county_shp = faf5_root / "county_shp" / "tl_2022_us_county.shp"
    crosswalk_path = processed / f"lodes_county_to_network_crosswalk_{job_type.lower()}_{year}.csv"

    if force_centroid or not centroid_od_path.exists():
        county_od = pd.read_parquet(county_od_path)
        mapper_od = county_od_to_assignment_schema(county_od)
        mapper_staging = processed / f"lodes_county_od_mapper_staging_{year}.parquet"
        write_parquet(mapper_od, mapper_staging)

        try:
            centroid_od, _, centroid_summary = run_mapping(
                bts_od_path=mapper_staging,
                network_centroids_path=network_centroids,
                network_nodes_path=network_nodes,
                detail_centroids_path=county_shp if county_shp.exists() else None,
                output_od_path=centroid_od_path,
                output_crosswalk_path=crosswalk_path,
                summary_json_path=processed / f"lodes_passenger_centroid_map_{job_type.lower()}_{year}_summary.json",
                year=year,
                default_payload_tons=1.0,
            )
            centroid_summary["mapping_method"] = "faf5_loading_centroids"
        except Exception as exc:
            if not county_shp.exists():
                raise
            LOGGER.warning("FAF5 centroid mapping failed (%s); using county-shapefile fallback", exc)
            centroid_od, node_map, centroid_summary = map_county_od_via_county_shp(
                mapper_od,
                county_shp,
                network_nodes,
                default_payload_tons=1.0,
            )
            write_parquet(node_map, crosswalk_path.with_suffix(".parquet"))
            crosswalk_path.write_text(node_map.to_csv(index=False), encoding="utf-8")
            write_parquet(centroid_od, centroid_od_path)
            summary_path = processed / f"lodes_passenger_centroid_map_{job_type.lower()}_{year}_summary.json"
            summary_path.write_text(json.dumps(centroid_summary, indent=2), encoding="utf-8")
    else:
        LOGGER.info("Reusing existing centroid OD: %s", centroid_od_path)
        centroid_od = pd.read_parquet(centroid_od_path)

    assignment_od = collapse_passenger_assignment_od(centroid_od)
    write_parquet(assignment_od, assignment_od_path)
    write_parquet(assignment_od, assignment_dest)

    outputs["assignment_od"] = str(assignment_od_path)
    outputs["lodes_passenger_od_matrix"] = str(assignment_dest)
    outputs["assignment_rows"] = str(len(assignment_od))
    outputs["crosswalk"] = str(crosswalk_path)

    manifest_path = base_path / "tables" / "lodes_passenger_od_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"year": year, "job_type": job_type, **outputs}, indent=2), encoding="utf-8")
    outputs["manifest"] = str(manifest_path)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Build CONUS LODES county-to-county passenger OD.")
    parser.add_argument("--year", type=int, default=2022)
    parser.add_argument("--job-type", default="JT00", help="LODES job type (JT00=all jobs, JT01=primary)")
    parser.add_argument(
        "--states",
        nargs="*",
        default=None,
        help="Optional state abbreviations. Default: all CONUS states.",
    )
    parser.add_argument("--force-county", action="store_true")
    parser.add_argument("--force-centroid", action="store_true")
    parser.add_argument("--skip-centroid", action="store_true", help="Only build county OD; skip network mapping.")
    parser.add_argument("--no-resume", action="store_true", help="Rebuild all state parts even if cached.")
    parser.add_argument("--network-centroids", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    configure_geo_runtime()
    config = load_config()
    base_path = Path(config["paths"]["soge_clusters"])

    outputs = build_lodes_passenger_od(
        base_path,
        year=args.year,
        job_type=args.job_type,
        states=args.states,
        force_county=args.force_county,
        force_centroid=args.force_centroid,
        skip_centroid=args.skip_centroid,
        resume=not args.no_resume,
        network_centroids_path=args.network_centroids,
    )
    for key, value in outputs.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
