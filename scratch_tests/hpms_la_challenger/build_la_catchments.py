"""LA home/work subarea catchments: nearest-centroid Voronoi clipped to county.

Also reports n_blocks from LODES xwalk assignment (same nearest rule).
area_km2 = Voronoi cell area inside LA County (non-overlapping partition).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import MultiPoint, Point, box
from shapely.ops import unary_union, voronoi_diagram

LA_FIPS = "06037"
COUNTY_SHP = None  # set via --county-shp; on Hopper may be absent — fall back to bbox


def _assign_ranks(blocks: pd.DataFrame, cents: pd.DataFrame) -> pd.Series:
    sub_lon = cents["lon"].to_numpy(float)
    sub_lat = cents["lat"].to_numpy(float)
    ranks = cents["subarea_rank"].to_numpy(int)
    blk_lon = blocks["lon"].to_numpy(float)
    blk_lat = blocks["lat"].to_numpy(float)
    d2 = (blk_lon[:, None] - sub_lon[None, :]) ** 2 + (blk_lat[:, None] - sub_lat[None, :]) ** 2
    return pd.Series(ranks[d2.argmin(axis=1)], index=blocks.index)


def _voronoi_cells_wgs84(cents: pd.DataFrame, county_poly) -> dict[int, object]:
    """Return {subarea_rank: polygon in lon/lat} clipped to county."""
    # Work in local meters for a sane Voronoi, then unproject
    lat0 = float(cents["lat"].mean())
    m_lat = 111_320.0
    m_lon = 111_320.0 * np.cos(np.radians(lat0))

    def to_xy(lon, lat):
        return (lon * m_lon, lat * m_lat)

    def to_ll(x, y):
        return (x / m_lon, y / m_lat)

    pts = MultiPoint([Point(*to_xy(r.lon, r.lat)) for r in cents.itertuples()])
    # envelope large enough to cover county
    minx, miny, maxx, maxy = county_poly.bounds
    env = box(*to_xy(minx, miny), *to_xy(maxx, maxy)).buffer(5000)
    vd = voronoi_diagram(pts, envelope=env, edges=False)

    # Map each voronoi polygon to nearest centroid rank
    rank_by_xy = {
        to_xy(r.lon, r.lat): int(r.subarea_rank) for r in cents.itertuples()
    }
    cells: dict[int, object] = {}
    # county in xy
    from shapely.ops import transform as shp_transform

    county_xy = shp_transform(lambda x, y, z=None: to_xy(x, y), county_poly)
    for geom in vd.geoms:
        if geom.is_empty:
            continue
        c = geom.centroid
        # nearest seed
        best_rank, best_d = None, float("inf")
        for (sx, sy), rank in rank_by_xy.items():
            d = (c.x - sx) ** 2 + (c.y - sy) ** 2
            if d < best_d:
                best_d, best_rank = d, rank
        clipped = geom.intersection(county_xy)
        if clipped.is_empty or best_rank is None:
            continue
        # back to lon/lat
        poly_ll = shp_transform(lambda x, y, z=None: to_ll(x, y), clipped)
        cells[best_rank] = poly_ll
    return cells


def _ring(poly) -> list | None:
    if poly is None or poly.is_empty:
        return None
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    if poly.geom_type != "Polygon":
        return None
    # simplify in degrees (~100m)
    simp = poly.simplify(0.001, preserve_topology=True)
    coords = list(simp.exterior.coords)
    if len(coords) > 80:
        step = max(1, len(coords) // 60)
        coords = coords[::step]
        if coords[0] != coords[-1]:
            coords.append(coords[0])
    return [[float(x), float(y)] for x, y in coords]


def _area_km2(poly, lat0: float) -> float:
    if poly is None or poly.is_empty:
        return 0.0
    m_lat = 111_320.0
    m_lon = 111_320.0 * np.cos(np.radians(lat0))
    from shapely.ops import transform as shp_transform

    xy = shp_transform(lambda x, y, z=None: (x * m_lon, y * m_lat), poly)
    return float(xy.area) / 1e6


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--xwalk",
        default="/scratch/akothaw/multimodal_hazard_data/lodes_data/ca/ca_xwalk.csv.gz",
    )
    ap.add_argument(
        "--home-crosswalk",
        default="/scratch/akothaw/multimodal_hazard_data/scratch_tests/county_connector_remedy/v3_vehicle_trips/passenger_home_crosswalk.csv",
    )
    ap.add_argument(
        "--work-crosswalk",
        default="/scratch/akothaw/multimodal_hazard_data/scratch_tests/county_connector_remedy/v3_vehicle_trips/passenger_work_crosswalk.csv",
    )
    ap.add_argument(
        "--county-shp",
        default="/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/tl_2022_us_county.shp",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/artifacts"),
    )
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    import geopandas as gpd

    # County polygon: try shp, else download-free bbox fallback from block extent
    county_path = Path(args.county_shp)
    if county_path.exists():
        counties = gpd.read_file(county_path)
        # GEOID or STATEFP+COUNTYFP
        if "GEOID" in counties.columns:
            la = counties[counties["GEOID"].astype(str) == LA_FIPS]
        else:
            la = counties[
                (counties["STATEFP"].astype(str) == "06")
                & (counties["COUNTYFP"].astype(str) == "037")
            ]
        if la.empty:
            raise ValueError("LA County not found in county shapefile")
        county_poly = la.to_crs(4326).geometry.unary_union
    else:
        # try Windows Desktop path when run locally
        local = Path(r"C:/Users/akothaw/Desktop/data/faf5_data/county_shp/tl_2022_us_county.shp")
        if local.exists():
            counties = gpd.read_file(local)
            la = counties[counties["GEOID"].astype(str) == LA_FIPS]
            county_poly = la.to_crs(4326).geometry.unary_union
        else:
            raise FileNotFoundError(
                f"county shapefile missing at {county_path} and {local}; "
                "copy tl_2022_us_county.shp or pass --county-shp"
            )

    print("Reading CA xwalk (LA County)...", flush=True)
    xw = pd.read_csv(args.xwalk, dtype={"cty": str, "tabblk2020": str}, low_memory=False)
    blocks = xw[xw["cty"] == LA_FIPS][["tabblk2020", "blklondd", "blklatdd"]].copy()
    blocks = blocks.rename(columns={"blklondd": "lon", "blklatdd": "lat"}).dropna()
    print(f"  LA blocks: {len(blocks)}", flush=True)

    out = {
        "_note": (
            "Catchment polygons = Voronoi cells of the 6 subarea centroids, "
            "clipped to LA County (FIPS 06037). Non-overlapping; area_km2 is "
            "cell area. n_blocks = LODES block centroids assigned by the same "
            "nearest-centroid rule. weight = demand share from passenger crosswalk."
        ),
        "home": [],
        "work": [],
    }

    for endpoint, path in (("home", args.home_crosswalk), ("work", args.work_crosswalk)):
        cw = pd.read_csv(path)
        cw = cw[cw["county_fips"] == 6037].copy()
        cw["subarea_rank"] = cw["subarea_rank"].astype(int)
        assigned = _assign_ranks(blocks, cw)
        n_by_rank = assigned.value_counts().to_dict()
        cells = _voronoi_cells_wgs84(cw, county_poly)
        lat0 = float(cw["lat"].mean())
        rows = []
        for _, c in cw.sort_values("subarea_rank").iterrows():
            rank = int(c["subarea_rank"])
            poly = cells.get(rank)
            rows.append(
                {
                    "endpoint": endpoint,
                    "subarea_rank": rank,
                    "faf5_node_id": int(c["node_id"]),
                    "lon": float(c["lon"]),
                    "lat": float(c["lat"]),
                    "weight": float(c["weight"]),
                    "n_blocks": int(n_by_rank.get(rank, 0)),
                    "area_km2": round(_area_km2(poly, lat0), 2),
                    "hull_ring": _ring(poly),
                }
            )
        out[endpoint] = rows
        print(f"{endpoint}:")
        for r in rows:
            print(
                f"  r{r['subarea_rank']} node={r['faf5_node_id']} "
                f"weight={r['weight']:.3f} blocks={r['n_blocks']} area_km2={r['area_km2']}"
            )

    out_path = args.out_dir / "la_subarea_catchments.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
