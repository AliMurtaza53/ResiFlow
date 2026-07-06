"""
Virginia FAF5-to-NIRD workflow.

This script starts from the FAF5 GDB, clips the road network to Virginia,
extracts Virginia centroid connectors, and builds a synthetic OD matrix using
an inverse-distance model with a 3M trip benchmark.

It reuses the existing converter helpers in `convert_faf5_to_nird.py` and
`convert_faf5_od_to_nird.py` so the workflow stays aligned with the repo's
standard conversion logic.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import fiona


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
import convert_faf5_to_nird as links_conv  # noqa: E402
import convert_faf5_od_to_nird as od_conv  # noqa: E402
from resiflow import freight_od_disaggregation as freight_od  # noqa: E402


DEFAULT_GDB_PATH = (
    r"C:\Users\alimu\Desktop\Github\FAF5_Model_Highway_Network\Networks\Geodatabase Format\FAF5Network.gdb"
)
DEFAULT_TARGET_CRS = "EPSG:2163"
DEFAULT_TOTAL_TRIPS = 3_000_000
DEFAULT_STATE = "VA"


def load_config() -> dict:
    config_path = REPO_ROOT / "config.json"
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text())


def load_gdb_layers(gdb_path: Path):
    print(f"Loading FAF5 GDB from: {gdb_path}")
    print("Available layers:", fiona.listlayers(str(gdb_path)))
    links = gpd.read_file(gdb_path, layer="FAF5_Links")
    nodes = gpd.read_file(gdb_path, layer="FAF5_Nodes")
    print(f"Loaded {len(links):,} links and {len(nodes):,} nodes")
    return links, nodes


def normalize_state_filter(state_value: str | list[str] | None):
    if state_value is None:
        return None
    if isinstance(state_value, str):
        state_value = [state_value]
    return [value.strip().upper() for value in state_value if value and value.strip()]


def filter_va_centroids(nodes: gpd.GeoDataFrame, state_id: int = 51) -> gpd.GeoDataFrame:
    """Extract all centroid nodes for Virginia (StateID==51).
    
    FAF5 centroid nodes are marked with Centroid==1. Virginia is StateID==51.
    Uses StateID instead of StateName to avoid catching West Virginia.
    
    Args:
        nodes: FAF5_Nodes GeoDataFrame
        state_id: Virginia's StateID (51)
        
    Returns:
        GeoDataFrame with all VA centroid nodes
    """
    if "Centroid" not in nodes.columns:
        raise ValueError("FAF5_Nodes layer does not have a 'Centroid' column")

    centroids = nodes[nodes["Centroid"] == 1].copy()
    
    # Filter by StateID (51 = Virginia, avoids West Virginia)
    if "StateID" in centroids.columns:
        centroids = centroids[centroids["StateID"] == state_id]
    
    print(f"Virginia centroids: {len(centroids):,} (Centroid==1 with StateID=={state_id})")
    return centroids


def build_nodes_from_link_connectivity(nird_links: gpd.GeoDataFrame, crs: str):
    _, _, nodes_dict = links_conv.extract_node_connectivity(nird_links, link_id_col="e_id")
    return links_conv.create_node_geodataframe(nodes_dict, crs=crs)


def save_gdf(gdf: gpd.GeoDataFrame, path: Path, layer: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".pq", ".gpq", ".parquet"}:
        gdf.to_parquet(path, index=False)
    else:
        gdf.to_file(path, driver="GPKG", layer=layer)
    print(f"Wrote {len(gdf):,} rows to {path}")


def subarea_node_map_from_centroids(
    centroids: pd.DataFrame,
    road_nodes: gpd.GeoDataFrame,
    crs: str,
) -> pd.DataFrame:
    """Build the subarea-to-network-node map needed by Script 1 OD export."""

    if "node_id" in centroids.columns:
        return freight_od.coerce_subarea_node_map_from_centroids(centroids)
    if "subarea_id" not in centroids.columns:
        raise ValueError("Freight centroid table must include subarea_id")

    if "geometry" in centroids.columns:
        if not isinstance(centroids, gpd.GeoDataFrame):
            centroid_gdf = gpd.GeoDataFrame(centroids, geometry="geometry")
        else:
            centroid_gdf = centroids.copy()
        if centroid_gdf.crs is None:
            centroid_gdf = centroid_gdf.set_crs(crs)
        centroid_gdf = centroid_gdf.to_crs(road_nodes.crs)
    elif {"x", "y"}.issubset(centroids.columns):
        centroid_gdf = gpd.GeoDataFrame(
            centroids.copy(),
            geometry=gpd.points_from_xy(centroids["x"], centroids["y"]),
            crs=crs,
        ).to_crs(road_nodes.crs)
    else:
        raise ValueError("Freight centroid table must include node_id, geometry, or x/y columns")

    nearest = gpd.sjoin_nearest(
        centroid_gdf[["subarea_id", "geometry"]],
        road_nodes[["node_id", "geometry"]],
        how="left",
    )
    return nearest[["subarea_id", "node_id"]].dropna().drop_duplicates("subarea_id")


def assignment_od_from_county_od(
    county_od_df: pd.DataFrame,
    county_node_map_path: str | None = None,
) -> pd.DataFrame:
    """Convert a county-level freight OD table to Script 1 OD when possible."""

    if {"origin_node", "destination_node", "Car21"}.issubset(county_od_df.columns):
        od_df = county_od_df[["origin_node", "destination_node", "Car21"]].copy()
        od_df["Car21"] = pd.to_numeric(od_df["Car21"], errors="coerce").fillna(0.0)
        return od_df.groupby(["origin_node", "destination_node"], as_index=False)["Car21"].sum()

    if county_node_map_path is None:
        raise ValueError(
            "County experimental OD is county-level only. Provide --county-node-map "
            "with county_id,node_id columns, or prebuild origin_node,destination_node,Car21."
        )
    node_map = pd.read_csv(county_node_map_path, dtype=str)
    node_map.columns = [str(col).strip() for col in node_map.columns]
    if not {"county_id", "node_id"}.issubset(node_map.columns):
        raise ValueError("--county-node-map must contain county_id,node_id columns")
    required = {"origin_county", "destination_county"}
    if not required.issubset(county_od_df.columns):
        raise ValueError("County experimental OD must contain origin_county,destination_county columns")
    flow_col = "daily_truck_trips" if "daily_truck_trips" in county_od_df.columns else (
        "annual_truck_trips" if "annual_truck_trips" in county_od_df.columns else None
    )
    if flow_col is None:
        raise ValueError("County experimental OD must contain daily_truck_trips or annual_truck_trips")
    od = county_od_df.copy()
    if flow_col == "annual_truck_trips":
        od["Car21"] = pd.to_numeric(od[flow_col], errors="coerce").fillna(0.0) / 365.0
    else:
        od["Car21"] = pd.to_numeric(od[flow_col], errors="coerce").fillna(0.0)
    node_map = node_map[["county_id", "node_id"]].drop_duplicates("county_id")
    od["origin_county"] = od["origin_county"].astype(str).str.strip()
    od["destination_county"] = od["destination_county"].astype(str).str.strip()
    od = od.merge(
        node_map.rename(columns={"county_id": "origin_county", "node_id": "origin_node"}),
        on="origin_county",
        how="inner",
    )
    od = od.merge(
        node_map.rename(columns={"county_id": "destination_county", "node_id": "destination_node"}),
        on="destination_county",
        how="inner",
    )
    return od.groupby(["origin_node", "destination_node"], as_index=False)["Car21"].sum()


def read_od_table(path: str | Path) -> pd.DataFrame:
    od_path = Path(path)
    if od_path.suffix.lower() in {".pq", ".parquet"}:
        return pd.read_parquet(od_path)
    return pd.read_csv(od_path, dtype=str)


def build_inverse_distance_od(
    centroid_nodes: gpd.GeoDataFrame,
    road_nodes: gpd.GeoDataFrame,
    total_trips: int,
    decay_power: float = 1.0,
    min_distance_m: float = 1.0,
    tolerance: float = 0.01,
) -> pd.DataFrame:
    """Build synthetic routable OD matrix using inverse-distance weights.
    
    Centroids can collapse to the same nearest network node. Those collapsed
    self-pairs cannot be routed, so they are excluded before final scaling.
    
    Args:
        centroid_nodes: GeoDataFrame with all Virginia centroid nodes
        road_nodes: GeoDataFrame with all road network nodes (to find nearest matches)
        total_trips: Total trips to distribute (e.g., 3,000,000)
        decay_power: Power for inverse-distance decay (1.0 = 1/d)
        min_distance_m: Minimum distance to avoid division by zero
        tolerance: Acceptable relative difference from target total after scaling
        
    Returns:
        DataFrame with origin_node, destination_node, Car21 (trips) columns
    """
    centroid_nodes = centroid_nodes.copy().to_crs(DEFAULT_TARGET_CRS)
    road_nodes = road_nodes.copy().to_crs(DEFAULT_TARGET_CRS)
    
    if centroid_nodes.empty:
        raise ValueError("No Virginia centroid nodes provided")
    if road_nodes.empty:
        raise ValueError("No road network nodes provided")
    
    print(f"\nBuilding synthetic {total_trips:,}-trip OD matrix for {len(centroid_nodes):,} centroids...")
    
    # Map each centroid to its nearest network node
    print("  Mapping centroids to network nodes...")
    centroid_to_network_node = {}
    for idx, cent_row in centroid_nodes.iterrows():
        cent_geom = cent_row.geometry
        distances = road_nodes.geometry.distance(cent_geom)
        nearest_idx = distances.idxmin()
        nearest_node_id = road_nodes.loc[nearest_idx, 'node_id']
        centroid_to_network_node[idx] = nearest_node_id
    
    # Extract coordinates for distance calculation (keep original index for mapping)
    coordinates = np.column_stack((
        centroid_nodes.geometry.x.to_numpy(),
        centroid_nodes.geometry.y.to_numpy()
    ))
    
    # Calculate pairwise distances
    delta = coordinates[:, None, :] - coordinates[None, :, :]
    distance_matrix = np.sqrt((delta**2).sum(axis=2))
    np.fill_diagonal(distance_matrix, np.inf)  # Exclude self-pairs
    
    # Build inverse-distance weights
    weights = 1.0 / np.power(np.maximum(distance_matrix, min_distance_m), decay_power)
    weights[np.isinf(weights)] = 0.0
    weights[np.isnan(weights)] = 0.0
    
    total_weight = weights.sum()
    if total_weight <= 0:
        raise ValueError("Inverse-distance weights sum to zero")

    # Build OD rows using raw weights first. Exclude pairs whose centroids map
    # to the same network node, because igraph returns an empty path for them.
    rows = []
    centroid_indices = list(centroid_to_network_node.keys())
    collapsed_self_pair_count = 0
    collapsed_self_pair_weight = 0.0
    
    for origin_idx_pos, origin_idx in enumerate(centroid_indices):
        origin_node = centroid_to_network_node[origin_idx]
        
        for dest_idx_pos, dest_idx in enumerate(centroid_indices):
            if origin_idx_pos == dest_idx_pos:
                continue  # Skip self-pairs
            
            destination_node = centroid_to_network_node[dest_idx]
            trip_weight = float(weights[origin_idx_pos, dest_idx_pos])
            
            if trip_weight <= 0:
                continue
            if str(origin_node) == str(destination_node):
                collapsed_self_pair_count += 1
                collapsed_self_pair_weight += trip_weight
                continue
            
            rows.append({
                "origin_node": origin_node,
                "destination_node": destination_node,
                "weight": trip_weight,
                "distance_m": float(distance_matrix[origin_idx_pos, dest_idx_pos]),
            })
    
    raw_routable_od = pd.DataFrame(rows)
    if raw_routable_od.empty:
        raise ValueError("OD generation produced no routable rows")

    raw_routable_weight = float(raw_routable_od["weight"].sum())
    if raw_routable_weight <= 0:
        raise ValueError("Routable inverse-distance weights sum to zero")

    raw_routable_od["distance_weight"] = (
        raw_routable_od["distance_m"] * raw_routable_od["weight"]
    )
    od_df = raw_routable_od.groupby(
        ["origin_node", "destination_node"], as_index=False
    ).agg(
        weight=("weight", "sum"),
        distance_weight=("distance_weight", "sum"),
    )
    od_df["distance_m"] = od_df["distance_weight"] / od_df["weight"]
    od_df["Car21"] = od_df["weight"] * (float(total_trips) / raw_routable_weight)
    od_df = od_df[["origin_node", "destination_node", "Car21", "distance_m"]]

    final_total = float(od_df["Car21"].sum())
    relative_error = abs(final_total - float(total_trips)) / float(total_trips)
    if relative_error > tolerance:
        raise ValueError(
            f"Final OD total {final_total:,.3f} differs from target "
            f"{total_trips:,.3f} by {relative_error:.2%}, above {tolerance:.2%}"
        )
    
    print(f"  Raw centroid pair weight: {total_weight:,.6f}")
    print(
        "  Removed collapsed self-pairs after node mapping: "
        f"{collapsed_self_pair_count:,} pairs, weight={collapsed_self_pair_weight:,.6f}"
    )
    print(f"  Routable centroid-pair rows before aggregation: {len(raw_routable_od):,}")
    print(f"  Routable OD pairs after aggregation: {len(od_df):,}")
    print(f"  Scale target: {total_trips:,.0f}")
    print(f"  Final OD total: {final_total:,.3f}")
    print(f"  Final OD target error: {relative_error:.4%}")
    
    return od_df


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Virginia-only FAF5 → NIRD workflow")
    parser.add_argument("--gdb", default=DEFAULT_GDB_PATH, help="Path to FAF5 geodatabase")
    parser.add_argument("--state", default=DEFAULT_STATE, help="State abbreviation to clip to (default: VA)")
    parser.add_argument("--boundary", default=None, help="Optional state boundary file to clip the network")
    parser.add_argument("--total-trips", type=int, default=DEFAULT_TOTAL_TRIPS, help="Benchmark trips for synthetic OD")
    parser.add_argument("--decay-power", type=float, default=1.0, help="Inverse-distance decay power")
    parser.add_argument("--dry-run", action="store_true", help="Only report actions; do not write files")
    parser.add_argument(
        "--od-source",
        choices=["synthetic", "freight_gravity", "faf5_county_experimental"],
        default="synthetic",
        help="OD source to write for Script 1. Default keeps current synthetic inverse-distance behavior.",
    )
    parser.add_argument("--freight-flow-table", default=None, help="Optional FAF5 commodity flow table for freight OD disaggregation")
    parser.add_argument("--freight-crosswalk", default=None, help="Optional FAF zone-to-subarea crosswalk")
    parser.add_argument("--freight-weights", default=None, help="Optional subarea production/attraction weight table")
    parser.add_argument("--freight-centroids", default=None, help="Optional subarea centroid or node-map table")
    parser.add_argument("--freight-payloads", default=None, help="Optional commodity/truck payload factor table")
    parser.add_argument("--freight-distance-matrix", default=None, help="Optional subarea-to-subarea skim table")
    parser.add_argument("--freight-year", default="2021", help="FAF flow year for freight OD disaggregation")
    parser.add_argument(
        "--freight-tons-unit",
        default="thousand_tons",
        choices=["tons", "thousand_tons"],
        help="Unit of the FAF tons column",
    )
    parser.add_argument("--freight-mode-filter", default="1", help="Mode to keep for freight preprocessing; use 'all' to disable")
    parser.add_argument("--county-od-path", default=None, help="County OD output from resiflow.faf5_county_disaggregation")
    parser.add_argument("--county-node-map", default=None, help="Optional county_id,node_id map for county OD assignment export")
    args = parser.parse_args()

    config = load_config()
    input_root_value = config.get("paths", {}).get("soge_clusters")
    input_root = Path(input_root_value) if input_root_value else None
    output_root = Path(config.get("paths", {}).get("output_path", "results"))
    if output_root.exists() and output_root.is_dir():
        va_root = output_root / "va_workflow"
    else:
        va_root = REPO_ROOT / "results_va_workflow"
        if output_root.exists() and output_root.is_file():
            print(f"Warning: configured output path {output_root} is a file; using {va_root} instead")
    va_root.mkdir(parents=True, exist_ok=True)

    gdb_path = Path(args.gdb)
    if not gdb_path.exists():
        print(f"FAF5 GDB not found: {gdb_path}")
        return 1

    links, nodes = load_gdb_layers(gdb_path)
    state_filter = normalize_state_filter(args.state)
    boundary_gdf = gpd.read_file(args.boundary) if args.boundary else None

    # Convert and clip the road network using the existing converter logic.
    # IMPORTANT: Keep class-50 centroid connectors (filter_centroids=False) because
    # they're the attachment points for the OD matrix.
    nird_links = links_conv.convert_faf5_links_to_nird(
        links,
        target_crs=DEFAULT_TARGET_CRS,
        filter_centroids=False,
        states=state_filter,
        boundary_gdf=boundary_gdf,
    )
    road_nodes = build_nodes_from_link_connectivity(nird_links, DEFAULT_TARGET_CRS)

    # Extract Virginia centroids from the FAF5 node layer.
    va_centroids = filter_va_centroids(nodes, state_id=51)
    va_centroids = va_centroids.to_crs(DEFAULT_TARGET_CRS)

    centroid_path = va_root / f"faf5_centroid_nodes_{args.state.upper()}.gpq"
    road_links_path = va_root / f"faf5_road_links_{args.state.upper()}.gpq"
    road_nodes_path = va_root / f"faf5_road_nodes_{args.state.upper()}.gpq"
    od_path = va_root / f"faf5_od_matrix_{args.state.upper()}_inverse_distance_{int(args.total_trips/1_000_000)}m.pq"
    freight_od_path = va_root / f"faf5_freight_od_matrix_{args.state.upper()}_{args.freight_year}.pq"
    script1_od_path = input_root / "census_datasets" / "faf5_od_matrix.pq" if input_root is not None else None
    freight_paths = [
        args.freight_flow_table,
        args.freight_crosswalk,
        args.freight_weights,
        args.freight_centroids,
        args.freight_payloads,
    ]
    use_freight_od = args.od_source == "freight_gravity" or any(freight_paths)
    if use_freight_od and not all(freight_paths):
        missing = [
            name
            for name, value in [
                ("--freight-flow-table", args.freight_flow_table),
                ("--freight-crosswalk", args.freight_crosswalk),
                ("--freight-weights", args.freight_weights),
                ("--freight-centroids", args.freight_centroids),
                ("--freight-payloads", args.freight_payloads),
            ]
            if not value
        ]
        raise ValueError(f"Freight OD preprocessing requires all core freight inputs. Missing: {missing}")
    if args.od_source == "faf5_county_experimental" and not args.county_od_path:
        raise ValueError("--od-source faf5_county_experimental requires --county-od-path")

    if args.dry_run:
        print(f"Dry run: would write road links to {road_links_path}")
        print(f"Dry run: would write road nodes to {road_nodes_path}")
        print(f"Dry run: would write centroid nodes to {centroid_path}")
        print(f"Dry run: OD source is {args.od_source}")
        if args.od_source == "faf5_county_experimental":
            print(f"Dry run: would read county experimental OD from {args.county_od_path}")
        elif use_freight_od:
            print("Dry run: would build freight OD via nird.freight_od_disaggregation")
            print(f"Dry run: would write freight assignment OD to {freight_od_path}")
        else:
            print(f"Dry run: would write synthetic OD to {od_path}")
        if script1_od_path is not None:
            print(f"Dry run: would also write Script 1 OD to {script1_od_path}")
        print(f"Road links after clipping: {len(nird_links):,}")
        print(f"Road nodes after clipping: {len(road_nodes):,}")
        print(f"Virginia centroids: {len(va_centroids):,}")
        return 0

    save_gdf(nird_links, road_links_path, layer="links")
    save_gdf(road_nodes, road_nodes_path, layer="nodes")
    save_gdf(va_centroids, centroid_path, layer="centroids")

    print(f"Using OD source: {args.od_source}")
    if args.od_source == "faf5_county_experimental":
        county_df = read_od_table(args.county_od_path)
        tons_total = pd.to_numeric(county_df.get("tons", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()
        daily_total = pd.to_numeric(
            county_df.get("daily_truck_trips", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0.0).sum()
        print(
            "Loaded BTS experimental county OD: "
            f"rows={len(county_df):,}, tons={tons_total:,.3f}, daily_truck_trips={daily_total:,.3f}"
        )
        od_df = assignment_od_from_county_od(county_df, county_node_map_path=args.county_node_map)
        print(f"Converted county OD to assignment OD rows: {len(od_df):,}, Car21={od_df['Car21'].sum():,.3f}")
    elif use_freight_od:
        inputs = freight_od.load_input_tables(
            faf_flow_path=args.freight_flow_table,
            crosswalk_path=args.freight_crosswalk,
            weights_path=args.freight_weights,
            centroids_path=args.freight_centroids,
            payload_factors_path=args.freight_payloads,
            distance_matrix_path=args.freight_distance_matrix,
        )
        subarea_node_map = subarea_node_map_from_centroids(
            inputs.centroids,
            road_nodes=road_nodes,
            crs=DEFAULT_TARGET_CRS,
        )
        mode_filter = None if str(args.freight_mode_filter).lower() == "all" else args.freight_mode_filter
        freight_result = freight_od.run_freight_disaggregation(
            inputs,
            year=args.freight_year,
            output_dir=va_root,
            subarea_node_map=subarea_node_map,
            tons_unit=args.freight_tons_unit,
            mode_filter=mode_filter,
            prefix=f"faf5_freight_{args.state.upper()}_{args.freight_year}",
        )
        od_df = freight_result["assignment_od"]
        if od_df is None:
            raise RuntimeError("Freight disaggregation did not produce an assignment OD table")
        od_df.to_parquet(freight_od_path, index=False)
        print(f"Wrote freight assignment OD matrix to {freight_od_path}")
        preservation = freight_result["diagnostics"]["faf_total_preservation"]
        failed = int((~preservation["within_tolerance"]).sum())
        print(f"Freight OD preservation checks outside tolerance: {failed:,}")
    else:
        # Build a synthetic OD matrix with inverse-distance decay.
        # Use ALL 195 centroid nodes for assignment, not just FAF aggregates.
        od_df = build_inverse_distance_od(
            centroid_nodes=va_centroids,
            road_nodes=road_nodes,
            total_trips=args.total_trips,
            decay_power=args.decay_power,
        )
        od_df.to_parquet(od_path, index=False)
        print(f"Wrote synthetic OD matrix to {od_path}")
    if script1_od_path is not None:
        script1_od_path.parent.mkdir(parents=True, exist_ok=True)
        od_df.to_parquet(script1_od_path, index=False)
        print(f"Wrote Script 1 OD matrix to {script1_od_path}")
    print(f"OD rows: {len(od_df):,}")
    print(f"Total trips: {od_df['Car21'].sum():,.2f}")

    print("Virginia FAF5 → NIRD workflow complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""
Run a lightweight VA-focused workflow to prepare inputs for scripts 1-4.

This script attempts to locate FAF5 network link files and centroid/node files
under the configured `soge_clusters` path (from `config.json`). It can filter
links by state code (default 'VA') or by a provided boundary file and writes
filtered outputs to `results/va_workflow/` for downstream scripts 1-4 to consume.

This is a safe, idempotent helper: if required input files are missing it will
print clear instructions and exit (no destructive changes).
"""
from pathlib import Path
import sys
import json
import argparse
import geopandas as gpd


def load_config(repo_root: Path):
    cfg_path = repo_root / "config.json"
    if not cfg_path.exists():
        return {}
    return json.loads(cfg_path.read_text())


def find_faf5_links(base: Path):
    # Look for common FAF5 link filenames under the soge_clusters folder
    patterns = ["**/*faf5*links*.gpkg", "**/*faf5*links*.*", "**/*faf5*links*.gpq"]
    for p in patterns:
        matches = list(base.glob(p))
        if matches:
            return matches[0]
    return None


def find_centroid_nodes(base: Path):
    patterns = ["**/*centroid_nodes*.*", "**/*centroid*nodes*.*"]
    for p in patterns:
        matches = list(base.glob(p))
        if matches:
            return matches[0]
    return None


def filter_links_by_state(links_gdf: gpd.GeoDataFrame, state_code: str):
    if "STATE" in links_gdf.columns:
        result = links_gdf[links_gdf["STATE"].astype(str).str.upper() == state_code.upper()].copy()
        return result
    else:
        print("  Warning: 'STATE' column not present on links; cannot filter by state.")
        return links_gdf.iloc[0:0].copy()


def filter_links_by_boundary(links_gdf: gpd.GeoDataFrame, boundary_gdf: gpd.GeoDataFrame):
    if links_gdf.crs != boundary_gdf.crs:
        boundary_gdf = boundary_gdf.to_crs(links_gdf.crs)
    boundary_union = boundary_gdf.unary_union
    return links_gdf[links_gdf.intersects(boundary_union)].copy()


def main():
    parser = argparse.ArgumentParser(description="Prepare VA workflow inputs (scripts 1-4)")
    parser.add_argument("--state", default="VA", help="Two-letter state code to filter (default: VA)")
    parser.add_argument("--boundary", help="Optional boundary file (GeoJSON/GPKG/SHAPE) to clip to")
    parser.add_argument("--dry-run", action="store_true", help="Only print actions; do not write outputs")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(repo_root)
    # support both top-level 'soge_clusters' and nested under 'paths'
    soge_val = cfg.get("soge_clusters") or cfg.get("paths", {}).get("soge_clusters")
    soge_root = Path(soge_val or "").expanduser()
    if not soge_root or not soge_root.exists():
        print("Could not find soge_clusters path from config.json. Please update 'soge_clusters' in config.json to point to your data folder (e.g., fairfax_soge_clusters_toy or a VA dataset).")
        return 1

    print(f"Using soge_clusters base: {soge_root}")

    faf5_links_path = find_faf5_links(soge_root)
    centroid_nodes_path = find_centroid_nodes(soge_root)

    print(f"Found FAF5 links: {faf5_links_path}")
    print(f"Found centroid nodes: {centroid_nodes_path}")

    if faf5_links_path is None:
        print("No FAF5 links file found under soge_clusters; please provide FAF5 link data (see data/README.md). Exiting.")
        return 1

    # Support nonstandard '.gpq' parquet-like files by trying read_parquet first
    try:
        if faf5_links_path.suffix.lower() in {'.gpq', '.parquet', '.pq'}:
            links = gpd.read_parquet(faf5_links_path)
        else:
            links = gpd.read_file(faf5_links_path)
    except Exception:
        # Fallback: try read_parquet then read_file to give better diagnostics
        try:
            links = gpd.read_parquet(faf5_links_path)
        except Exception as e_parq:
            print(f"Failed to read {faf5_links_path} as parquet: {e_parq}")
            links = gpd.read_file(faf5_links_path)

    print(f"Loaded {len(links)} links (CRS: {links.crs})")

    # Determine output base. Prefer configured output_path only if it exists and is a directory.
    configured_out = Path(cfg.get("paths", {}).get("output_path", "results"))
    configured_out = (repo_root / configured_out)
    if configured_out.exists() and configured_out.is_dir():
        out_dir = configured_out / "va_workflow"
    else:
        alt_base = repo_root / "results_va_workflow"
        out_dir = alt_base / "va_workflow"
        if configured_out.exists() and configured_out.is_file():
            print(f"Warning: configured output path '{configured_out}' exists but is not a directory. Using '{alt_base}' instead.")
    out_dir.mkdir(parents=True, exist_ok=True)

    filtered = links.iloc[0:0].copy()
    if args.boundary:
        bpath = Path(args.boundary)
        if not bpath.exists():
            print(f"Boundary file {bpath} not found. Exiting.")
            return 1
        boundary = gpd.read_file(bpath)
        print(f"Loaded boundary with {len(boundary)} polygon(s) (CRS: {boundary.crs})")
        filtered = filter_links_by_boundary(links, boundary)
    else:
        filtered = filter_links_by_state(links, args.state)

    print(f"Filtered links count: {len(filtered)}")

    if args.dry_run:
        print("Dry run requested; no outputs written.")
        return 0

    out_links_file = out_dir / "faf5_road_links_VA.gpkg"
    if len(filtered):
        filtered.to_file(out_links_file, driver="GPKG", layer="links")
        print(f"Wrote filtered links to {out_links_file}")
    else:
        print("No links after filtering; no link file written.")

    if centroid_nodes_path and centroid_nodes_path.exists():
        centroids = gpd.read_file(centroid_nodes_path)
        if args.boundary:
            centroids = centroids[centroids.intersects(boundary.unary_union)].copy()
        else:
            if "STATE" in centroids.columns:
                centroids = centroids[centroids["STATE"].astype(str).str.upper() == args.state.upper()].copy()
            else:
                print("Centroid nodes do not have a 'STATE' column; writing whole centroid file for manual inspection.")
        out_centroids_file = out_dir / "faf5_centroid_nodes_VA.gpkg"
        centroids.to_file(out_centroids_file, driver="GPKG", layer="centroids")
        print(f"Wrote centroid nodes subset to {out_centroids_file}")
    else:
        print("No centroid nodes file found; centroid/OD creation skipped.")

    print("VA workflow preparation complete. Next: run scripts 1-4 using outputs in results/va_workflow/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
