"""
Convert FAF5 regional OD CSV to ResiFlow assignment OD matrix (origin_node, destination_node, Car21).

FAF5 OD Flow Structure:
- Origin FAF Zone (dms_orig)
- Destination FAF Zone (dms_dest) 
- Commodity type (sctg2)
- Mode (dms_mode)
- Tonnage values by year
- Value in dollars

ResiFlow assignment OD format:
- origin_node: Network node ID
- destination_node: Network node ID
- Car21: Flow volume (vehicles or freight units)
"""

import pandas as pd
import geopandas as gpd
from pathlib import Path
import numpy as np


def load_faf5_od_data(faf5_od_path):
    """
    Load FAF5 OD flow data from CSV.
    
    FAF5.7.1 CSV Structure:
    - dms_orig: Origin domestic zone (3-digit code)
    - dms_dest: Destination domestic zone (3-digit code)
    - dms_mode: Transportation mode code (1=Truck, 2=Rail, etc.)
    - sctg2: SCTG commodity code (01-43)
    - trade_type: Domestic, import, export
    - tons_YYYY: Tonnage for year YYYY (2017-2050)
    - value_YYYY: Value in million dollars
    - tmiles_YYYY: Ton-miles
    
    Args:
        faf5_od_path: Path to FAF5 OD CSV file
        
    Returns:
        DataFrame with FAF zone-to-zone flows
    """
    print(f"Loading FAF5 OD data from: {faf5_od_path}")
    
    df = pd.read_csv(faf5_od_path)
    
    print(f"  Loaded {len(df)} OD records")
    print(f"  Columns: {list(df.columns[:15])}...")  # First 15 columns
    
    # Summary statistics
    if 'dms_orig' in df.columns:
        unique_origins = df['dms_orig'].nunique()
        unique_dests = df['dms_dest'].nunique()
        print(f"  Unique origin zones: {unique_origins}")
        print(f"  Unique destination zones: {unique_dests}")
    
    if 'dms_mode' in df.columns:
        mode_counts = df['dms_mode'].value_counts()
        print(f"  Records by mode: {dict(mode_counts)}")
    
    return df


def load_faf_zone_centroids(faf_zones_path):
    """
    Load FAF zone boundaries and calculate centroids.
    
    Args:
        faf_zones_path: Path to FAF zone shapefile or GDB layer
        
    Returns:
        GeoDataFrame with FAF zone geometries and centroids
    """
    print(f"\nLoading FAF zones from: {faf_zones_path}")
    
    faf_zones = gpd.read_file(faf_zones_path)
    
    # Calculate centroids
    faf_zones['centroid'] = faf_zones.geometry.centroid
    
    print(f"  Loaded {len(faf_zones)} FAF zones")
    
    return faf_zones


def map_faf_zones_to_network_nodes(faf_zones=None, network_nodes=None, centroid_nodes_path=None):
    """
    Map each FAF zone to network nodes.
    
    Two methods:
    1. If centroid_nodes_path provided: Use FAF5's built-in centroid nodes
       with CentroidID to directly map zones to nodes
    2. If faf_zones provided: Map zone geometries to nearest network nodes
    
    Args:
        faf_zones: Optional GeoDataFrame with FAF zone geometries
        network_nodes: GeoDataFrame with network nodes
        centroid_nodes_path: Optional path to saved FAF5 centroid nodes
        
    Returns:
        Dictionary mapping FAF zone ID -> network node ID
    """
    print("\nMapping FAF zones to network nodes...")
    
    # Method 1: Use FAF5's centroid nodes directly
    if centroid_nodes_path and Path(centroid_nodes_path).exists():
        print("  Using FAF5 centroid nodes (Method 1: Spatial join to nearest nodes)")
        centroid_nodes = gpd.read_parquet(centroid_nodes_path)
        
        # Ensure both geodataframes have same CRS
        if centroid_nodes.crs != network_nodes.crs:
            print(f"  Reprojecting centroid nodes from {centroid_nodes.crs} to {network_nodes.crs}")
            centroid_nodes = centroid_nodes.to_crs(network_nodes.crs)
        
        # Use spatial join (nearest neighbor) for better performance
        try:
            nearest = gpd.sjoin_nearest(
                centroid_nodes[['FAFID', 'geometry']],
                network_nodes[['node_id', 'geometry']],
                how='left',
                distance_col='_dist'
            )
            zone_to_node = dict(zip(nearest['FAFID'].astype(int), nearest['node_id']))
        except Exception as e:
            print(f"  Spatial join failed ({e}), falling back to iterative nearest")
            zone_to_node = {}
            zone_col = 'FAFID' if 'FAFID' in centroid_nodes.columns else 'CentroidID'
            for idx, row in centroid_nodes.iterrows():
                zone_id = int(row[zone_col])
                distances = network_nodes.geometry.distance(row.geometry)
                nearest_node_idx = distances.idxmin()
                nearest_node_id = network_nodes.loc[nearest_node_idx, 'node_id']
                zone_to_node[zone_id] = nearest_node_id
        
        print(f"  Mapped {len(zone_to_node)} FAF zones via centroid nodes")
        return zone_to_node
    
    # Method 2: Use zone geometries
    if faf_zones is not None and network_nodes is not None:
        print("  Using FAF zone geometries (Method 2: Spatial proximity)")
        
        # Ensure same CRS
        if faf_zones.crs != network_nodes.crs:
            print(f"  Reprojecting FAF zones from {faf_zones.crs} to {network_nodes.crs}")
            faf_zones = faf_zones.to_crs(network_nodes.crs)
        
        zone_to_node = {}
        
        for idx, zone in faf_zones.iterrows():
            zone_id = zone['FAFZONE'] if 'FAFZONE' in zone else zone.name
            zone_centroid = zone.geometry.centroid
            
            # Find nearest network node
            distances = network_nodes.geometry.distance(zone_centroid)
            nearest_node_idx = distances.idxmin()
            nearest_node_id = network_nodes.loc[nearest_node_idx, 'node_id']
            
            zone_to_node[zone_id] = nearest_node_id
        
        print(f"  Mapped {len(zone_to_node)} FAF zones to network nodes")
        return zone_to_node
    
    raise ValueError("Must provide either centroid_nodes_path or (faf_zones + network_nodes)")


def convert_tonnage_to_vehicles(tonnage_ktons, commodity_type='all', year=2021):
    """
    Convert freight tonnage to equivalent number of vehicles.
    
    Args:
        tonnage_ktons: Freight weight in thousand tons (FAF5 units)
        commodity_type: SCTG commodity code (optional for refinement)
        year: Data year
        
    Returns:
        Estimated number of vehicles
        
    Assumptions:
        - FAF5 tonnage is in THOUSAND TONS
        - Average truck payload: 15-25 tons depending on commodity
        - Annual flows converted to daily vehicle counts (divide by 365)
    """
    # Average truck payload in tons
    AVG_PAYLOAD = {
        'default': 20.0,
        'bulk': 25.0,      # Coal, minerals (SCTG 10-15)
        'container': 20.0,  # Manufactured goods (SCTG 24-39)
        'food': 18.0,      # Perishables (SCTG 01-08)
        'fuel': 22.0,      # Petroleum products (SCTG 16-19)
    }
    
    payload = AVG_PAYLOAD.get(commodity_type, AVG_PAYLOAD['default'])
    
    # Convert thousand tons to tons
    tonnage_tons = tonnage_ktons * 1000
    
    # Calculate annual vehicle trips needed
    annual_vehicles = tonnage_tons / payload
    
    # Convert to average daily vehicles (more meaningful for routing)
    daily_vehicles = annual_vehicles / 365 # refine to account for peak factor/seasonality if needed
    
    return max(1, round(daily_vehicles))  # At least 1 vehicle


def aggregate_faf5_flows(faf5_od, year='2021', mode_filter='Truck', include_all_commodities=True, chunksize=250_000):
    """
    Aggregate FAF5 OD flows by origin-destination pairs.
    
    Args:
        faf5_od: DataFrame with FAF5 OD flows
        year: Year to extract data for (e.g., '2021', '2030', '2050')
        mode_filter: Transportation mode to filter:
                    'Truck' (1), 'Rail' (2), 'Water' (3), 'Air' (4), 'Multiple/Mail' (5), 'Pipeline' (6), 'Other/Unknown' (7)
                    or None for all modes
        include_all_commodities: If True, aggregate all SCTG commodities; if False, can filter specific ones
        
    Returns:
        Aggregated DataFrame with zone-to-zone flows
    """
    # Mode mapping
    MODE_CODES = {
        'Truck': 1,
        'Rail': 2,
        'Water': 3,
        'Air': 4,
        'Multiple': 5,
        'Pipeline': 6,
        'Other': 7
    }
    
    print(f"\nAggregating FAF5 flows for year: {year}, mode: {mode_filter}")
    
    # Construct year column name
    tonnage_col = f'tons_{year}'

    # Path-based, chunked processing to reduce memory
    if isinstance(faf5_od, (str, Path)):
        faf5_path = Path(faf5_od)
        header_cols = pd.read_csv(faf5_path, nrows=0).columns
        if tonnage_col not in header_cols:
            year_cols = [col for col in header_cols if col.startswith('tons_')]
            print(f"  Warning: Column {tonnage_col} not found.")
            print(f"  Available years: {[col.replace('tons_', '') for col in year_cols]}")
            if year_cols:
                tonnage_col = year_cols[0]
                print(f"  Using {tonnage_col} instead")
            else:
                raise ValueError("No tonnage columns found in data")

        usecols = ['dms_orig', 'dms_dest', tonnage_col]
        if mode_filter:
            usecols.append('dms_mode')

        mode_code = MODE_CODES.get(mode_filter, 1) if mode_filter else None
        agg = {}
        total_rows = 0
        for chunk in pd.read_csv(faf5_path, usecols=usecols, chunksize=chunksize, low_memory=False):
            total_rows += len(chunk)
            if mode_code is not None and 'dms_mode' in chunk.columns:
                chunk = chunk[chunk['dms_mode'] == mode_code]
            if chunk.empty:
                continue
            grouped = chunk.groupby(['dms_orig', 'dms_dest'])[tonnage_col].sum()
            for (orig, dest), value in grouped.items():
                agg[(orig, dest)] = agg.get((orig, dest), 0) + value

        print(f"  Processed {total_rows} rows in chunks")
        od_flows = pd.DataFrame(
            [(k[0], k[1], v) for k, v in agg.items()],
            columns=['origin_zone', 'destination_zone', 'tonnage']
        )
    else:
        # In-memory processing
        # Filter by mode if specified
        if mode_filter and 'dms_mode' in faf5_od.columns:
            mode_code = MODE_CODES.get(mode_filter, 1)
            faf5_od_filtered = faf5_od[faf5_od['dms_mode'] == mode_code].copy()
            print(f"  Filtered to {len(faf5_od_filtered)} records for mode {mode_filter} (code {mode_code})")
        else:
            faf5_od_filtered = faf5_od.copy()

        if tonnage_col not in faf5_od_filtered.columns:
            print(f"  Warning: Column {tonnage_col} not found.")
            year_cols = [col for col in faf5_od_filtered.columns if col.startswith('tons_')]
            print(f"  Available years: {[col.replace('tons_', '') for col in year_cols]}")
            if year_cols:
                tonnage_col = year_cols[0]
                print(f"  Using {tonnage_col} instead")
            else:
                raise ValueError("No tonnage columns found in data")

        agg_cols = ['dms_orig', 'dms_dest']
        od_flows = faf5_od_filtered.groupby(agg_cols)[tonnage_col].sum().reset_index()
        od_flows.columns = ['origin_zone', 'destination_zone', 'tonnage']

    # Remove zero flows
    od_flows = od_flows[od_flows['tonnage'] > 0]
    
    print(f"  Aggregated to {len(od_flows)} unique OD pairs")
    print(f"  Total tonnage: {od_flows['tonnage'].sum():,.0f} thousand tons")
    print(f"  Avg tonnage per OD: {od_flows['tonnage'].mean():,.1f} thousand tons")
    
    return od_flows


def convert_faf5_od_matrix(faf5_od_flows, zone_to_node_mapping):
    """Convert FAF5 zone-to-zone flows to assignment OD matrix rows."""
    print("\nConverting FAF5 OD to assignment format...")

    assignment_od = []
    skipped = 0
    
    for idx, row in faf5_od_flows.iterrows():
        origin_zone = int(row['origin_zone'])  # Convert to int for consistent type matching
        dest_zone = int(row['destination_zone'])
        tonnage = row['tonnage']
        
        # Map zones to nodes
        if origin_zone not in zone_to_node_mapping:
            skipped += 1
            continue
        if dest_zone not in zone_to_node_mapping:
            skipped += 1
            continue
        
        origin_node = zone_to_node_mapping[origin_zone]
        dest_node = zone_to_node_mapping[dest_zone]
        
        # Convert tonnage to vehicles
        vehicles = convert_tonnage_to_vehicles(tonnage)
        
        assignment_od.append({
            'origin_node': origin_node,
            'destination_node': dest_node,
            'Car21': vehicles,
            'tonnage': tonnage  # Keep original tonnage for reference
        })
    
    assignment_od_df = pd.DataFrame(assignment_od)
    
    print(f"  Converted {len(assignment_od_df)} OD pairs")
    if skipped > 0:
        print(f"  Skipped {skipped} pairs due to missing zone mappings")
    print(f"  Total vehicles: {assignment_od_df['Car21'].sum():,.0f}")
    
    return assignment_od_df


def validate_assignment_od(od_df, network_nodes):
    """Validate that OD matrix nodes exist in the network."""
    print("\nValidating assignment OD matrix...")
    
    node_ids = set(network_nodes['node_id'].values)
    origin_nodes = set(od_df['origin_node'].values)
    dest_nodes = set(od_df['destination_node'].values)
    
    all_od_nodes = origin_nodes.union(dest_nodes)
    missing_nodes = all_od_nodes - node_ids
    
    if missing_nodes:
        print(f"  ⚠ Warning: {len(missing_nodes)} OD nodes not found in network")
        print(f"    Examples: {list(missing_nodes)[:5]}")
        return False
    else:
        print(f"  ✓ All {len(all_od_nodes)} OD nodes exist in network")
        return True


def main(argv: list[str] | None = None) -> int:
    """CLI entry: convert FAF5 regional OD CSV to assignment OD parquet."""
    import argparse

    from resiflow.faf5_paths import resolve_faf5_data_root, resolve_regional_od_path
    from resiflow.utils import load_config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--faf5-od", help="Path to FAF5.7.1 CSV (default: resolve from FAF5 data root)")
    parser.add_argument("--network-nodes", help="Path to faf5_road_nodes.gpq")
    parser.add_argument("--centroid-nodes", help="Path to faf5_centroid_nodes.gpq")
    parser.add_argument("--faf-zones", help="Optional FAF zone geometries if centroids missing")
    parser.add_argument(
        "--output",
        help="Output parquet path (default: <soge_clusters>/census_datasets/faf5_od_matrix.pq)",
    )
    parser.add_argument("--year", default="2021")
    parser.add_argument("--mode", default="Truck")
    args = parser.parse_args(argv)

    config = load_config()
    base_path = Path(config["paths"]["soge_clusters"])
    faf5_root = resolve_faf5_data_root(base_path)
    faf5_od_path = Path(args.faf5_od) if args.faf5_od else resolve_regional_od_path(faf5_root) if faf5_root else None
    if faf5_od_path is None or not Path(faf5_od_path).exists():
        raise FileNotFoundError("Could not resolve FAF5 OD CSV; pass --faf5-od")

    network_nodes_path = Path(
        args.network_nodes or base_path / "networks" / "faf5" / "faf5_road_nodes.gpq"
    )
    centroid_nodes_path = Path(
        args.centroid_nodes or base_path / "networks" / "faf5" / "faf5_centroid_nodes.gpq"
    )
    output_path = Path(args.output or base_path / "census_datasets" / "faf5_od_matrix.pq")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("FAF5 OD to ResiFlow assignment matrix conversion")
    print("=" * 80)

    faf5_od_agg = aggregate_faf5_flows(str(faf5_od_path), year=args.year, mode_filter=args.mode)
    network_nodes = gpd.read_parquet(network_nodes_path)

    if centroid_nodes_path.exists():
        zone_to_node = map_faf_zones_to_network_nodes(
            network_nodes=network_nodes,
            centroid_nodes_path=str(centroid_nodes_path),
        )
    elif args.faf_zones:
        faf_zones = load_faf_zone_centroids(args.faf_zones)
        zone_to_node = map_faf_zones_to_network_nodes(faf_zones=faf_zones, network_nodes=network_nodes)
    else:
        raise ValueError("Provide --centroid-nodes or --faf-zones for zone mapping")

    assignment_od = convert_faf5_od_matrix(faf5_od_agg, zone_to_node)
    validate_assignment_od(assignment_od, network_nodes)
    assignment_od.to_parquet(output_path, index=False)
    print(f"Saved {len(assignment_od)} OD pairs to {output_path}")
    return 0


convert_faf5_od_to_nird = convert_faf5_od_matrix
validate_nird_od = validate_assignment_od


if __name__ == "__main__":
    raise SystemExit(main())
