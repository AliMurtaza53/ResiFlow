"""
Convert FAF5 Network Data to NIRD Format

This script converts FAF5 (Freight Analysis Framework) geodatabase format
to NIRD-compatible GeoParquet format based on actual FAF5 schema.

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
import fiona


# Road classification mapping: FAF5 Class -> NIRD coarse road_classification
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
# These are preserved separately from the coarse NIRD categories above.
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
    'lanes': 2,
    'average_toll_cost': 0.0,
    'road_bridge': 'no',
    'meters_per_lane': 3.5,
}


def list_gdb_layers(gdb_path):
    """List all available layers in a geodatabase."""
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


def convert_faf5_links_to_nird(faf5_links, target_crs='EPSG:2163', filter_centroids=True, 
                                states=None, boundary_gdf=None):
    """
    Convert FAF5 link GeoDataFrame to NIRD format.
    
    Args:
        faf5_links: GeoDataFrame with FAF5 link data
        target_crs: Target coordinate reference system (default: US Albers Equal Area)
                   Use 'EPSG:27700' for UK, 'EPSG:2163' for continental US
        filter_centroids: If True, remove Class==50 centroid connector links
        states: Optional string or list of state abbreviations to filter to (e.g., 'VA' or ['VA', 'MD'])
        boundary_gdf: Optional GeoDataFrame with polygon boundary to clip to
    
    Returns:
        GeoDataFrame in NIRD format
    """
    # Apply geographic filters first
    if states is not None:
        faf5_links = filter_by_states(faf5_links, states)
    
    if boundary_gdf is not None:
        faf5_links = filter_by_geography(faf5_links, boundary_gdf)
    
    # Filter centroid connectors
    if filter_centroids:
        faf5_links = filter_centroid_connectors(faf5_links)
    
    print(f"\nConverting {len(faf5_links)} FAF5 links to NIRD format...")
    
    nird_links = gpd.GeoDataFrame()
    
    # 1. Edge ID
    nird_links['e_id'] = faf5_links['ID'].astype(str)
    print(f"  ✓ e_id: {len(nird_links['e_id'].unique())} unique links")
    
    # 2. Extract node connectivity
    from_ids, to_ids, nodes = extract_node_connectivity(faf5_links, 'ID')
    nird_links['from_id'] = from_ids
    nird_links['to_id'] = to_ids
    print(f"  ✓ from_id/to_id: {len(nodes)} nodes")
    
    # 3. Geometry - reproject if needed
    nird_links['geometry'] = faf5_links.geometry
    if faf5_links.crs != target_crs:
        print(f"  Reprojecting from {faf5_links.crs} to {target_crs}...")
        nird_links = nird_links.set_crs(faf5_links.crs, allow_override=True)
        nird_links = nird_links.to_crs(target_crs)
    else:
        nird_links = nird_links.set_crs(target_crs)
    
    # 4. Length - convert miles to meters
    if 'LENGTH' in faf5_links.columns:
        nird_links['length'] = faf5_links['LENGTH'] * 1609.34
    else:
        # Calculate from geometry
        nird_links['length'] = nird_links.geometry.length
    print(f"  ✓ length: {nird_links['length'].min():.1f} to {nird_links['length'].max():.1f} meters")
    
    # 5. Road classification - preserve both coarse and detailed labels
    if 'Class' in faf5_links.columns:
        nird_links['road_classification_coarse'] = faf5_links['Class'].map(CLASS_MAPPING)
        nird_links['road_classification_coarse'] = nird_links['road_classification_coarse'].fillna('unclassified')

        detailed_from_desc = None
        if 'Class_Description' in faf5_links.columns:
            detailed_from_desc = faf5_links['Class_Description'].map(_clean_label)

        detailed_from_class = faf5_links['Class'].map(DETAIL_CLASS_MAPPING)
        detailed = detailed_from_desc if detailed_from_desc is not None else detailed_from_class
        if detailed_from_desc is not None:
            detailed = detailed.fillna(detailed_from_class)

        nird_links['road_classification_detail'] = detailed.fillna(nird_links['road_classification_coarse'])
    else:
        nird_links['road_classification_coarse'] = 'unclassified'
        nird_links['road_classification_detail'] = 'unclassified'

    # Keep the historical column name for downstream compatibility.
    nird_links['road_classification'] = nird_links['road_classification_coarse']

    print(f"  ✓ road_classification_coarse: {nird_links['road_classification_coarse'].nunique()} types")
    print(f"  ✓ road_classification_detail: {nird_links['road_classification_detail'].nunique()} types")
    
    # 6. Lanes - take maximum of both directions
    if 'AB_Lanes' in faf5_links.columns and 'BA_Lanes' in faf5_links.columns:
        nird_links['lanes'] = faf5_links[['AB_Lanes', 'BA_Lanes']].max(axis=1)
    elif 'AB_Lanes' in faf5_links.columns:
        nird_links['lanes'] = faf5_links['AB_Lanes']
    else:
        nird_links['lanes'] = DEFAULTS['lanes']
    
    # Fill missing lanes with default
    nird_links['lanes'] = nird_links['lanes'].fillna(DEFAULTS['lanes']).astype(int)
    print(f"  ✓ lanes: {nird_links['lanes'].min()} to {nird_links['lanes'].max()}")
    
    # 7. Urban classification - based on Urban_Code
    if 'Urban_Code' in faf5_links.columns:
        # 99999 typically indicates rural areas in FAF5
        nird_links['urban'] = (faf5_links['Urban_Code'] != 99999).astype(int)
    else:
        nird_links['urban'] = 0  # Default to rural
    print(f"  ✓ urban: {nird_links['urban'].sum()} urban, {(~nird_links['urban'].astype(bool)).sum()} rural")
    
    # 8. Average width - estimated from lanes
    nird_links['averageWidth'] = nird_links['lanes'] * DEFAULTS['meters_per_lane']
    
    # 9. Toll cost - check toll fields
    if 'Toll_Type' in faf5_links.columns:
        # If Toll_Type is not null, we could estimate cost, but default to 0
        nird_links['average_toll_cost'] = DEFAULTS['average_toll_cost']
    else:
        nird_links['average_toll_cost'] = DEFAULTS['average_toll_cost']
    
    # 10. Bridge indicator - default to 'no'
    nird_links['road_bridge'] = DEFAULTS['road_bridge']
    
    # 11. Optional: Copy useful attributes
    optional_columns = ['Road_Name', 'STATE', 'County_Name', 'FAFZONE', 
                       'Speed_Limit', 'AB_FinalSpeed', 'BA_FinalSpeed']
    for col in optional_columns:
        if col in faf5_links.columns:
            nird_links[col] = faf5_links[col]
    
    # Report summary
    print(f"\n✓ Conversion complete: {len(nird_links)} links")
    print(f"  Road types: {dict(nird_links['road_classification'].value_counts())}")
    
    return nird_links


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


def validate_nird_network(links_gdf):
    """Validate that the converted network has all required NIRD columns."""
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


def main():
    """Main conversion workflow."""
    
    # Configuration
    FAF5_GDB_PATH = r"C:\Users\alimu\Desktop\Github\FAF5_Model_Highway_Network\Networks\Geodatabase Format\FAF5Network.gdb"
    OUTPUT_DIR = Path(r"C:\Users\alimu\NIRD_Data\soge_clusters\networks\faf5")
    TARGET_CRS = 'EPSG:2163'  # US Albers Equal Area projection
    
    # Geographic filtering options (optional)
    FILTER_STATES = None  # e.g., 'VA' or ['VA', 'MD', 'DC'] or None for all states
    BOUNDARY_FILE = None  # e.g., r"C:\Path\To\study_area.shp" or None for no clipping
    
    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Step 1: List available layers
    print("=" * 80)
    print("FAF5 to NIRD Network Conversion")
    print("=" * 80)
    
    layers = list_gdb_layers(FAF5_GDB_PATH)
    
    # Step 2: Read FAF5 links (adjust layer name as needed)
    link_layer = "FAF5_Links"  # FAF5 layer name
    node_layer = "FAF5_Nodes"  # Node layer
    
    print(f"\nReading layer: {link_layer}")
    faf5_links = gpd.read_file(FAF5_GDB_PATH, layer=link_layer)
    
    print(f"  Read {len(faf5_links)} links")
    print(f"  CRS: {faf5_links.crs}")
    print(f"  Columns: {list(faf5_links.columns)}")
    
    # Also read nodes to identify centroids
    print(f"\nReading layer: {node_layer}")
    try:
        faf5_nodes = gpd.read_file(FAF5_GDB_PATH, layer=node_layer)
        print(f"  Read {len(faf5_nodes)} nodes")
        
        # Check for centroid information
        if 'Centroid' in faf5_nodes.columns:
            centroid_count = (faf5_nodes['Centroid'] == 1).sum()
            print(f"  Found {centroid_count} centroid nodes (FAF zone centroids)")
            print(f"  Found {len(faf5_nodes) - centroid_count} real network nodes")
        
        # Save centroid nodes for zone mapping
        centroid_nodes_path = OUTPUT_DIR / "faf5_centroid_nodes.gpq"
        if 'Centroid' in faf5_nodes.columns:
            centroids = faf5_nodes[faf5_nodes['Centroid'] == 1].copy()
            centroids.to_parquet(centroid_nodes_path)
            print(f"  ✓ Saved {len(centroids)} centroid nodes to: {centroid_nodes_path}")
    except Exception as e:
        print(f"  Warning: Could not read nodes layer: {e}")
        faf5_nodes = None
    
    # Step 3: Load optional boundary for clipping
    boundary_gdf = None
    if BOUNDARY_FILE is not None:
        print(f"\nLoading boundary file: {BOUNDARY_FILE}")
        boundary_gdf = gpd.read_file(BOUNDARY_FILE)
        print(f"  Loaded boundary with {len(boundary_gdf)} polygon(s)")
        print(f"  Boundary CRS: {boundary_gdf.crs}")
    
    # Step 4: Convert to NIRD format (with optional filters)
    nird_links = convert_faf5_links_to_nird(
        faf5_links, 
        target_crs=TARGET_CRS,
        states=FILTER_STATES,
        boundary_gdf=boundary_gdf
    )
    
    # Step 5: Validate
    validate_nird_network(nird_links)
    
    # Step 6: Save to GeoParquet
    # Create descriptive filename based on filters
    if FILTER_STATES is not None:
        states_str = '_'.join(FILTER_STATES) if isinstance(FILTER_STATES, list) else FILTER_STATES
        output_filename = f"faf5_road_links_{states_str}.gpq"
    elif BOUNDARY_FILE is not None:
        output_filename = "faf5_road_links_clipped.gpq"
    else:
        output_filename = "faf5_road_links.gpq"
    
    output_path = OUTPUT_DIR / output_filename
    print(f"\nSaving to: {output_path}")
    nird_links.to_parquet(output_path)
    print(f"✓ Saved {len(nird_links)} links")
    
    # Optional: Save nodes as well
    # Note: Extract from original links to get correct connectivity
    # (after filtering, some nodes may be disconnected)
    nodes_output_filename = output_filename.replace('_links', '_nodes')
    nodes_output_path = OUTPUT_DIR / nodes_output_filename
    
    # Create nodes from the filtered network
    from shapely.geometry import Point
    node_coords = set()
    for geom in nird_links.geometry:
        # Handle both LineString and MultiLineString
        if geom.geom_type == 'MultiLineString':
            for line in geom.geoms:
                coords = list(line.coords)
                if len(coords) > 0:
                    node_coords.add((round(coords[0][0], 6), round(coords[0][1], 6)))
                    node_coords.add((round(coords[-1][0], 6), round(coords[-1][1], 6)))
        else:
            coords = list(geom.coords)
            if len(coords) > 0:
                node_coords.add((round(coords[0][0], 6), round(coords[0][1], 6)))
                node_coords.add((round(coords[-1][0], 6), round(coords[-1][1], 6)))
    
    nodes_data = [{'node_id': i, 'geometry': Point(x, y)} for i, (x, y) in enumerate(node_coords)]
    nodes_gdf = gpd.GeoDataFrame(nodes_data, crs=TARGET_CRS)
    nodes_gdf.to_parquet(nodes_output_path)
    print(f"✓ Saved {len(nodes_gdf)} nodes to: {nodes_output_path}")
    
    print("\n" + "=" * 80)
    print("Conversion complete!")
    print("=" * 80)
    
    return nird_links


if __name__ == "__main__":
    main()
