"""
Convert FAF5 network geodatabase layers to ResiFlow assignment GeoParquet.

This module converts FAF5 (Freight Analysis Framework) geodatabase format
to the ResiFlow-compatible link schema used by Scripts 1–4.

FAF5 Link Schema (as of V2021.05):
- ID: Link identifier
- LENGTH: Link length in miles
- DIR: Direction (0=bidirectional, 1=one-way)
- Class: Road classification code (1-19)
- Class_Description: Text description of road class
- AB_Lanes, BA_Lanes: Lanes in each direction
- Speed_Limit: Posted speed limit (mph)
- Urban_Code: Urban area code (99999 = rural)
- FAFZONE: FAF zone identifier
- Various toll and state attributes
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path
from resiflow.parameters import get_parameter

# Road classification mapping: FAF5 Class -> coarse road_classification
CLASS_MAPPING = {
    # Legacy/simple FAF class codes seen in early test files.
    1: 'motorway',           # Interstate
    2: 'trunk',              # Principal Arterial - Freeways
    3: 'primary',            # Principal Arterial - Other
    4: 'primary',            # Minor Arterial
    5: 'secondary',          # Major Collector
    6: 'tertiary',           # Minor Collector
    7: 'unclassified',       # Local
    8: 'motorway_link',      # Ramp
    9: 'service',            # Service/Frontage Road
    # FAF5 V2021.05 network class codes.
    11: 'motorway',          # Interstate Highway
    12: 'trunk',             # Other Controlled Access Highway
    13: 'motorway',          # Non-Freeway Interstate (Alaska)
    14: 'primary',           # Arterial or Major Collector
    15: 'tertiary',          # Local Road
    16: 'service',           # Frontage/Service Road
    17: 'service',           # Traffic Circle
    18: 'service',           # Turn Lane
    19: 'service',           # Facility Access/Circulator
    21: 'motorway_link',     # System Ramp
    22: 'motorway_link',     # Ramp
    23: 'primary',           # Collector/Distributor Lane
    33: 'motorway',          # Express Lane (Truck)
    36: 'service',           # Administrative/Service Road
    41: 'service',           # Ferry
    50: 'centroid_connector' # Centroid connector (will be filtered)
}

# Detailed FAF5 road-class labels for reporting / plotting.
# These are preserved separately from the coarse assignment categories above.
DETAIL_CLASS_MAPPING = {
    1: 'Interstate',
    2: 'Principal Arterial - Freeways and Expressways',
    3: 'Principal Arterial - Other',
    4: 'Minor Arterial',
    5: 'Major Collector',
    6: 'Minor Collector',
    7: 'Local',
    8: 'Ramp',
    9: 'Service/Frontage Road',
    19: 'Facility Access/Circulator',
    11: 'Interstate Highway',
    12: 'Other Controlled Access Highway',
    13: 'Non-Freeway Interstate (Alaska)',
    14: 'Arterial or Major Collector',
    15: 'Local Road',
    16: 'Frontage/Service Road',
    17: 'Traffic Circle',
    18: 'Turn Lane',
    21: 'System Ramp',
    22: 'Ramp',
    23: 'Collector/Distributor Lane',
    33: 'Express Lane (Truck)',
    36: 'Administrative/Service Road',
    41: 'Ferry',
    50: 'Centroid Connector',
}


def _clean_label(value):
    if value is None:
        return None
    text = str(value).strip()
    if text == '' or text.lower() in {'nan', 'none', 'null'}:
        return None
    return text

# Default parameters if missing in FAF5 data
DEFAULTS = {
    'lanes': get_parameter("preprocess", "faf5_default_lanes", 2),
    'average_toll_cost': get_parameter("preprocess", "faf5_default_avg_toll_cost", 0.0),
    'road_bridge': 'no',
    'meters_per_lane': get_parameter("preprocess", "faf5_default_meters_per_lane", 3.5),
}


def list_gdb_layers(gdb_path):
    """List all available layers in a geodatabase."""
    import fiona  # lazy import: geodatabase-only dependency, not needed to import this module

    layers = fiona.listlayers(gdb_path)
    print(f"Available layers in {gdb_path}:")
    for i, layer in enumerate(layers, 1):
        print(f"  {i}. {layer}")
    return layers


def extract_node_connectivity(faf5_links, link_id_col='ID', faf5_nodes=None):
    """
    Extract node connectivity from link geometry.
    
    If FAF5 has explicit node IDs (ANODE/BNODE columns), use those.
    Otherwise, extract from geometry endpoints.
    
    Args:
        faf5_links: GeoDataFrame with link data
        link_id_col: Column name for link ID
        faf5_nodes: Optional GeoDataFrame with node data (for filtering centroids)
    
    Returns:
        from_ids, to_ids, nodes dictionary
    """
    # Check if FAF5 has explicit node columns
    if 'ANODE' in faf5_links.columns and 'BNODE' in faf5_links.columns:
        print("Using explicit ANODE/BNODE from FAF5 data...")
        from_ids = faf5_links['ANODE'].tolist()
        to_ids = faf5_links['BNODE'].tolist()
        
        # Create nodes dictionary from unique node IDs
        all_nodes = set(from_ids + to_ids)
        nodes = {node_id: node_id for node_id in all_nodes}
        
        print(f"  Found {len(nodes)} unique nodes from ANODE/BNODE")
        return from_ids, to_ids, nodes
    
    # Otherwise extract from geometry
    print("Extracting node connectivity from link geometry...")
    
    nodes = {}
    node_id = 0
    
    def get_or_create_node(coord):
        nonlocal node_id
        # Round coordinates to avoid floating point issues
        key = (round(coord[0], 6), round(coord[1], 6))
        if key not in nodes:
            nodes[key] = node_id
            node_id += 1
        return nodes[key]
    
    from_ids = []
    to_ids = []
    
    for geom in faf5_links.geometry:
        # Handle both LineString and MultiLineString
        if geom.geom_type == 'MultiLineString':
            # For MultiLineString, use first and last coordinates from all parts
            coords = []
            for line in geom.geoms:
                coords.extend(list(line.coords))
        else:
            coords = list(geom.coords)
        
        if len(coords) > 0:
            from_ids.append(get_or_create_node(coords[0]))
            to_ids.append(get_or_create_node(coords[-1]))
    
    print(f"  Created {len(nodes)} unique nodes from geometry")
    return from_ids, to_ids, nodes


def filter_by_states(faf5_links, states):
    """
    Filter links to specific state(s).
    
    Args:
        faf5_links: GeoDataFrame with FAF5 link data
        states: String (single state) or list of state abbreviations (e.g., 'VA' or ['VA', 'MD', 'DC'])
    
    Returns:
        Filtered GeoDataFrame with only links in specified states
    """
    if states is None:
        return faf5_links
    
    original_count = len(faf5_links)
    
    if 'STATE' not in faf5_links.columns:
        print("  Warning: 'STATE' column not found, cannot filter by state")
        return faf5_links
    
    # Convert single state to list
    if isinstance(states, str):
        states = [states]
    
    # Filter to specified states
    filtered = faf5_links[faf5_links['STATE'].isin(states)].copy()
    removed = original_count - len(filtered)
    
    print(f"\nFiltering to state(s): {', '.join(states)}")
    print(f"  Kept {len(filtered)} links in specified state(s)")
    print(f"  Removed {removed} links in other states")
    
    return filtered


def filter_by_geography(faf5_links, boundary_gdf):
    """
    Clip links to a user-defined geographic boundary.
    
    Args:
        faf5_links: GeoDataFrame with FAF5 link data
        boundary_gdf: GeoDataFrame with polygon boundary to clip to
    
    Returns:
        Filtered GeoDataFrame with only links intersecting the boundary
    """
    if boundary_gdf is None:
        return faf5_links
    
    original_count = len(faf5_links)
    
    # Ensure same CRS
    if faf5_links.crs != boundary_gdf.crs:
        print(f"  Reprojecting boundary from {boundary_gdf.crs} to {faf5_links.crs}")
        boundary_gdf = boundary_gdf.to_crs(faf5_links.crs)
    
    # Get union of all boundary polygons
    boundary_union = boundary_gdf.unary_union
    
    # Spatial filter - keep links that intersect boundary
    filtered = faf5_links[faf5_links.intersects(boundary_union)].copy()
    removed = original_count - len(filtered)
    
    print(f"\nClipping to user-defined geography:")
    print(f"  Kept {len(filtered)} links intersecting boundary")
    print(f"  Removed {removed} links outside boundary")
    
    return filtered


def filter_centroid_connectors(faf5_links):
    """
    Filter out centroid connector links (Class==50).
    
    Centroid connectors are artificial links connecting FAF zone centroids
    to the actual road network. They should be excluded from routing analysis.
    
    Args:
        faf5_links: GeoDataFrame with FAF5 link data
    
    Returns:
        Filtered GeoDataFrame without centroid connectors
    """
    original_count = len(faf5_links)
    
    if 'Class' in faf5_links.columns:
        centroid_connectors = faf5_links['Class'] == 50
        filtered = faf5_links[~centroid_connectors].copy()
        removed = centroid_connectors.sum()
        
        if removed > 0:
            print(f"\nFiltering centroid connectors:")
            print(f"  Removed {removed} Class==50 centroid connector links")
            print(f"  Remaining: {len(filtered)} real road links")
        
        return filtered
    else:
        print("  Warning: 'Class' column not found, cannot filter centroid connectors")
        return faf5_links


def convert_faf5_links(
    faf5_links,
    target_crs="EPSG:9311",
    filter_centroids=True,
    states=None,
    boundary_gdf=None,
):
    """Convert FAF5 link GeoDataFrame to the ResiFlow assignment link schema."""
    # Apply geographic filters first
    if states is not None:
        faf5_links = filter_by_states(faf5_links, states)
    
    if boundary_gdf is not None:
        faf5_links = filter_by_geography(faf5_links, boundary_gdf)
    
    # Filter centroid connectors
    if filter_centroids:
        faf5_links = filter_centroid_connectors(faf5_links)
    
    print(f"\nConverting {len(faf5_links)} FAF5 links to ResiFlow assignment format...")

    assignment_links = gpd.GeoDataFrame()

    # 1. Edge ID
    assignment_links["e_id"] = faf5_links["ID"].astype(str)
    print(f"  ✓ e_id: {len(assignment_links['e_id'].unique())} unique links")

    # 2. Extract node connectivity
    from_ids, to_ids, nodes = extract_node_connectivity(faf5_links, "ID")
    assignment_links["from_id"] = from_ids
    assignment_links["to_id"] = to_ids
    print(f"  ✓ from_id/to_id: {len(nodes)} nodes")
    
    # 3. Geometry - reproject if needed
    assignment_links['geometry'] = faf5_links.geometry
    if faf5_links.crs != target_crs:
        print(f"  Reprojecting from {faf5_links.crs} to {target_crs}...")
        assignment_links = assignment_links.set_crs(faf5_links.crs, allow_override=True)
        assignment_links = assignment_links.to_crs(target_crs)
    else:
        assignment_links = assignment_links.set_crs(target_crs)
    
    # 4. Length - convert miles to meters
    if 'LENGTH' in faf5_links.columns:
        assignment_links['length'] = faf5_links['LENGTH'] * 1609.34
    else:
        # Calculate from geometry
        assignment_links['length'] = assignment_links.geometry.length
    print(f"  ✓ length: {assignment_links['length'].min():.1f} to {assignment_links['length'].max():.1f} meters")
    
    # 5. Road classification - preserve both coarse and detailed labels
    if 'Class' in faf5_links.columns:
        assignment_links['road_classification_coarse'] = faf5_links['Class'].map(CLASS_MAPPING)
        assignment_links['road_classification_coarse'] = assignment_links['road_classification_coarse'].fillna('unclassified')

        detailed_from_desc = None
        if 'Class_Description' in faf5_links.columns:
            detailed_from_desc = faf5_links['Class_Description'].map(_clean_label)

        detailed_from_class = faf5_links['Class'].map(DETAIL_CLASS_MAPPING)
        detailed = detailed_from_desc if detailed_from_desc is not None else detailed_from_class
        if detailed_from_desc is not None:
            detailed = detailed.fillna(detailed_from_class)

        assignment_links['road_classification_detail'] = detailed.fillna(assignment_links['road_classification_coarse'])
    else:
        assignment_links['road_classification_coarse'] = 'unclassified'
        assignment_links['road_classification_detail'] = 'unclassified'

    # Keep the historical column name for downstream compatibility.
    assignment_links['road_classification'] = assignment_links['road_classification_coarse']
    assignment_links['network_source'] = 'faf5'

    print(f"  ✓ road_classification_coarse: {assignment_links['road_classification_coarse'].nunique()} types")
    print(f"  ✓ road_classification_detail: {assignment_links['road_classification_detail'].nunique()} types")
    
    # 6. Lanes - take maximum of both directions
    if 'AB_Lanes' in faf5_links.columns and 'BA_Lanes' in faf5_links.columns:
        assignment_links['lanes'] = faf5_links[['AB_Lanes', 'BA_Lanes']].max(axis=1)
    elif 'AB_Lanes' in faf5_links.columns:
        assignment_links['lanes'] = faf5_links['AB_Lanes']
    else:
        assignment_links['lanes'] = DEFAULTS['lanes']
    
    # Fill missing lanes with default
    assignment_links['lanes'] = assignment_links['lanes'].fillna(DEFAULTS['lanes']).astype(int)
    print(f"  ✓ lanes: {assignment_links['lanes'].min()} to {assignment_links['lanes'].max()}")
    
    # 7. Urban classification - based on Urban_Code
    if 'Urban_Code' in faf5_links.columns:
        # 99999 typically indicates rural areas in FAF5
        assignment_links['urban'] = (faf5_links['Urban_Code'] != 99999).astype(int)
    else:
        assignment_links['urban'] = 0  # Default to rural
    print(f"  ✓ urban: {assignment_links['urban'].sum()} urban, {(~assignment_links['urban'].astype(bool)).sum()} rural")
    
    # 8. Average width - estimated from lanes
    assignment_links['averageWidth'] = assignment_links['lanes'] * DEFAULTS['meters_per_lane']
    
    # 9. Toll cost - check toll fields
    if 'Toll_Type' in faf5_links.columns:
        # If Toll_Type is not null, we could estimate cost, but default to 0
        assignment_links['average_toll_cost'] = DEFAULTS['average_toll_cost']
    else:
        assignment_links['average_toll_cost'] = DEFAULTS['average_toll_cost']
    
    # 10. Bridge indicator - default to 'no'
    assignment_links['road_bridge'] = DEFAULTS['road_bridge']
    
    # 11. Optional: Copy useful attributes
    optional_columns = ['Road_Name', 'STATE', 'County_Name', 'FAFZONE', 
                       'Speed_Limit', 'AB_FinalSpeed', 'BA_FinalSpeed']
    for col in optional_columns:
        if col in faf5_links.columns:
            assignment_links[col] = faf5_links[col]
    
    # Report summary
    print(f"\n✓ Conversion complete: {len(assignment_links)} links")
    print(f"  Road types: {dict(assignment_links['road_classification'].value_counts())}")
    
    return assignment_links


def create_node_geodataframe(nodes_dict, crs='EPSG:2163'):
    """
    Create a GeoDataFrame of nodes from the connectivity dictionary.
    
    Args:
        nodes_dict: Dictionary mapping (lon, lat) -> node_id
        crs: Coordinate reference system
    
    Returns:
        GeoDataFrame with node geometries
    """
    from shapely.geometry import Point
    
    node_data = []
    for (lon, lat), node_id in nodes_dict.items():
        node_data.append({
            'node_id': node_id,
            'geometry': Point(lon, lat)
        })
    
    nodes_gdf = gpd.GeoDataFrame(node_data, crs=crs)
    print(f"\nCreated node GeoDataFrame: {len(nodes_gdf)} nodes")
    
    return nodes_gdf


def validate_assignment_network(links_gdf):
    """Validate that converted links have required assignment columns."""
    required_cols = ['from_id', 'to_id', 'e_id', 'geometry', 'length', 
                     'lanes', 'road_classification', 'average_toll_cost', 
                     'urban', 'averageWidth', 'road_bridge']
    
    missing = [col for col in required_cols if col not in links_gdf.columns]
    
    if missing:
        print(f"\n⚠ Warning: Missing required columns: {missing}")
        return False
    else:
        print(f"\n✓ Validation passed: All required columns present")
        return True


def main(argv: list[str] | None = None) -> int:
    """CLI entry: convert FAF5 GDB links to assignment GeoParquet."""
    import argparse

    from resiflow.config import get_env
    from resiflow.geo_runtime import CONUS_TARGET_CRS
    from resiflow.utils import load_config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gdb", required=True, help="Path to FAF5Network.gdb")
    parser.add_argument(
        "--output-dir",
        help="Output directory for faf5_road_links.gpq (default: <soge_clusters>/networks/faf5)",
    )
    parser.add_argument("--target-crs", default=CONUS_TARGET_CRS)
    parser.add_argument("--states", help="Comma-separated state abbreviations to filter")
    parser.add_argument("--boundary", help="Optional boundary vector for clipping")
    parser.add_argument("--keep-centroids", action="store_true", help="Keep Class==50 connectors")
    parser.add_argument("--link-layer", default="FAF5_Links")
    parser.add_argument("--node-layer", default="FAF5_Nodes")
    args = parser.parse_args(argv)

    config = load_config()
    base_path = Path(config["paths"]["soge_clusters"])
    output_dir = Path(args.output_dir) if args.output_dir else base_path / "networks" / "faf5"
    output_dir.mkdir(parents=True, exist_ok=True)

    gdb_path = Path(args.gdb)
    if not gdb_path.exists():
        raise FileNotFoundError(gdb_path)

    print("=" * 80)
    print("FAF5 to ResiFlow network conversion")
    print("=" * 80)
    list_gdb_layers(str(gdb_path))

    faf5_links = gpd.read_file(gdb_path, layer=args.link_layer)
    boundary_gdf = gpd.read_file(args.boundary) if args.boundary else None
    states = [part.strip() for part in args.states.split(",") if part.strip()] if args.states else None

    try:
        faf5_nodes = gpd.read_file(gdb_path, layer=args.node_layer)
        centroid_nodes_path = output_dir / "faf5_centroid_nodes.gpq"
        if "Centroid" in faf5_nodes.columns:
            centroids = faf5_nodes[faf5_nodes["Centroid"] == 1].copy()
            centroids.to_parquet(centroid_nodes_path)
            print(f"Saved {len(centroids)} centroid nodes to {centroid_nodes_path}")
    except Exception as exc:
        print(f"Warning: could not read/write centroid nodes: {exc}")

    assignment_links = convert_faf5_links(
        faf5_links,
        target_crs=args.target_crs,
        filter_centroids=not args.keep_centroids,
        states=states,
        boundary_gdf=boundary_gdf,
    )
    validate_assignment_network(assignment_links)

    if states:
        states_str = "_".join(states)
        output_filename = f"faf5_road_links_{states_str}.gpq"
    elif args.boundary:
        output_filename = "faf5_road_links_clipped.gpq"
    else:
        output_filename = "faf5_road_links.gpq"

    output_path = output_dir / output_filename
    assignment_links.to_parquet(output_path)
    print(f"Saved {len(assignment_links)} links to {output_path}")

    from shapely.geometry import Point

    node_coords: set[tuple[float, float]] = set()
    for geom in assignment_links.geometry:
        lines = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
        for line in lines:
            coords = list(line.coords)
            if coords:
                node_coords.add((round(coords[0][0], 6), round(coords[0][1], 6)))
                node_coords.add((round(coords[-1][0], 6), round(coords[-1][1], 6)))

    nodes_gdf = gpd.GeoDataFrame(
        [{"node_id": i, "geometry": Point(x, y)} for i, (x, y) in enumerate(node_coords)],
        crs=args.target_crs,
    )
    nodes_output_path = output_dir / output_filename.replace("_links", "_nodes")
    nodes_gdf.to_parquet(nodes_output_path)
    print(f"Saved {len(nodes_gdf)} nodes to {nodes_output_path}")
    return 0


# Backward-compatible aliases for legacy imports.
convert_faf5_links_to_nird = convert_faf5_links
validate_nird_network = validate_assignment_network


if __name__ == "__main__":
    raise SystemExit(main())
