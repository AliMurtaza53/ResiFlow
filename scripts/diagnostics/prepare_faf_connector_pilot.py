"""Prepare isolated Harvey-15 inputs with native FAF5 Class 50 connectors."""

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Geod
from scipy.spatial import cKDTree
from shapely import get_parts
from shapely.geometry import LineString, MultiLineString, Point


def coordinates(points):
    return np.column_stack((points.x, points.y))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("network", type=Path, help="Directory with the Hopper road links and nodes")
    parser.add_argument("subset", type=Path, help="Harvey-15 OD and its county crosswalk")
    parser.add_argument("corrected_crosswalk", type=Path)
    parser.add_argument("review_gpkg", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    links = gpd.read_parquet(args.network / "faf5_road_links.gpq")
    nodes = gpd.read_parquet(args.network / "faf5_road_nodes.gpq").to_crs(links.crs)
    assert links.crs.is_projected and links.crs.axis_info[0].unit_name == "metre"
    assert not links.faf5_class.eq(50).any()
    connected = set(links.from_id) | set(links.to_id)
    road_nodes = nodes[nodes.node_id.isin(connected)]
    assert road_nodes.node_id.is_unique and len(road_nodes) == len(connected)

    native = gpd.read_file(args.review_gpkg, layer="faf5_native_connectors_2022").to_crs(links.crs)
    centroids = gpd.read_file(args.review_gpkg, layer="faf5_centroids_2022").to_crs(links.crs)
    exits = gpd.read_file(args.review_gpkg, layer="faf5_road_end_attachments").to_crs(links.crs)
    assert len(native) == len(exits) == 3795 and native.link_id.is_unique and exits.link_id.is_unique
    exits = exits.set_index("link_id").loc[native.link_id]
    distance, position = cKDTree(coordinates(road_nodes.geometry)).query(coordinates(exits.geometry))
    if distance.max() >= 300:
        raise ValueError(f"Official road end is {distance.max():.1f} m from the connected graph")
    first_new_id = int(nodes.node_id.astype(int).max()) + 1
    centroids["node_id"] = first_new_id + centroids.centroid_id.astype(int)
    assert centroids.node_id.is_unique
    centroid_node = centroids.set_index("centroid_id").node_id
    centroid_point = centroids.set_index("centroid_id").geometry

    # Preserve official shape and close any geometric gap to the selected graph node.
    geometries = []
    for geom, cid, road in zip(native.geometry, native.centroid_id, road_nodes.geometry.iloc[position]):
        parts = list(get_parts(geom))
        start = parts[0].coords[0]
        end = parts[-1].coords[-1]
        point = centroid_point.loc[cid]
        if point.distance(Point(start)) < point.distance(Point(end)):
            parts[-1] = LineString([*parts[-1].coords, road.coords[0]])
        else:
            parts[0] = LineString([road.coords[0], *parts[0].coords])
        geometries.append(MultiLineString(parts))
    connectors = gpd.GeoDataFrame(geometry=geometries, crs=links.crs)
    connectors["e_id"] = native.link_id.astype(str)
    assert not set(connectors.e_id) & set(links.e_id)
    connectors["from_id"] = native.centroid_id.map(centroid_node).astype(links.from_id.dtype)
    connectors["to_id"] = road_nodes.node_id.iloc[position].to_numpy().astype(links.to_id.dtype)
    connectors["length"] = connectors.geometry.length
    connectors["faf5_class"] = 50
    connectors["assignment_tier"] = "centroid_connector"
    connectors["road_classification"] = "centroid_connector"
    connectors["road_label"] = "road"
    connectors["road_bridge"] = "no"
    connectors["road_tunnel"] = "no"
    connectors["average_toll_cost"] = 0.0
    connectors["urban"] = 0
    connectors["lanes"] = 10  # Existing 10,000 veh/lane-hour tier yields 2.4M vehicles/day.
    for col in ("AB_FinalSpeed", "BA_FinalSpeed", "Speed_Limit"):
        connectors[col] = 25.0
    connectors["STATE"] = native.STATE
    connectors["County_Name"] = native.County_Name
    connectors["FAFZONE"] = native.FAFZONE

    crosswalk = pd.read_csv(args.subset / "county_node_crosswalk_subset.csv")
    corrected = pd.read_csv(args.corrected_crosswalk)
    check = crosswalk.merge(corrected, on="county_fips", suffixes=("", "_corrected"), validate="one_to_one")
    assert len(check) == len(crosswalk) and check.node_id.eq(check.node_id_corrected).all()
    crosswalk["centroid_node"] = crosswalk.county_fips.map(centroid_node)
    if crosswalk.centroid_node.isna().any():
        missing = crosswalk.loc[crosswalk.centroid_node.isna(), "county_fips"].tolist()
        raise ValueError(f"Pilot counties without an official centroid: {missing}")
    mapping = crosswalk.set_index("node_id", verify_integrity=True).centroid_node
    od = pd.read_parquet(args.subset / "faf5_od_matrix_subset.pq")
    arm = od.copy()
    for col in ("origin_node", "destination_node"):
        arm[col] = od[col].astype(int).map(mapping)
        assert arm[col].notna().all()
        arm[col] = arm[col].astype(od[col].dtype)
    pd.testing.assert_frame_equal(od.drop(columns=["origin_node", "destination_node"]),
                                  arm.drop(columns=["origin_node", "destination_node"]))
    geod = Geod(ellps="WGS84")
    for name, frame, points in (("control", od, nodes), ("connector", arm, centroids)):
        geometry = points.assign(node_id=points.node_id.astype(int)).to_crs(4326).set_index("node_id").geometry
        origin = geometry.loc[frame.origin_node.astype(int)]
        destination = geometry.loc[frame.destination_node.astype(int)]
        _, _, metres = geod.inv(origin.x.to_numpy(), origin.y.to_numpy(),
                               destination.x.to_numpy(), destination.y.to_numpy())
        assert np.isfinite(metres).all()
        print(f"{name}: flow-weighted straight-line haul {np.average(metres, weights=frame.Car21)/1609.344:.2f} mi")
    args.output.mkdir(parents=True, exist_ok=False)
    gpd.GeoDataFrame(pd.concat([links, connectors.reindex(columns=links.columns.union(connectors.columns))],
                               ignore_index=True), geometry="geometry", crs=links.crs).to_parquet(
        args.output / "faf5_road_links.gpq"
    )
    arm.to_parquet(args.output / "faf5_od_matrix_subset.pq", index=False)
    crosswalk.to_csv(args.output / "county_node_crosswalk.csv", index=False)
    pd.DataFrame({"e_id": connectors.e_id, "centroid_node": connectors.from_id,
                  "road_node": connectors.to_id, "centroid_id": native.centroid_id,
                  "road_snap_m": distance}).to_csv(args.output / "connector_crosswalk.csv", index=False)
    print(f"Restored {len(connectors)} connectors. Road snaps max {distance.max():.2f} m.")
    print(f"Preserved {len(od)} OD rows and {od.Car21.sum():.6f} trips/day.")


if __name__ == "__main__":
    main()
