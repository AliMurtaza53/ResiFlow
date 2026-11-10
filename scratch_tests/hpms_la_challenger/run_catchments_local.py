"""Local Voronoi catchments using Desktop county shp + Hopper-fetched LA blocks."""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import MultiPoint, Point, box
from shapely.ops import transform as shp_transform
from shapely.ops import voronoi_diagram

ART = Path(__file__).resolve().parent / "artifacts"
LA_FIPS = "06037"
COUNTY = Path(r"C:/Users/akothaw/Desktop/data/faf5_data/county_shp/tl_2022_us_county.shp")


def assign(blocks: pd.DataFrame, cents: pd.DataFrame) -> pd.Series:
    sub_lon = cents["lon"].to_numpy(float)
    sub_lat = cents["lat"].to_numpy(float)
    ranks = cents["subarea_rank"].to_numpy(int)
    d2 = (blocks["lon"].to_numpy(float)[:, None] - sub_lon[None, :]) ** 2 + (
        blocks["lat"].to_numpy(float)[:, None] - sub_lat[None, :]
    ) ** 2
    return pd.Series(ranks[d2.argmin(1)], index=blocks.index)


def voronoi_cells(cents: pd.DataFrame, county_poly):
    lat0 = float(cents["lat"].mean())
    m_lat = 111_320.0
    m_lon = 111_320.0 * np.cos(np.radians(lat0))

    def to_xy(lon, lat):
        return (lon * m_lon, lat * m_lat)

    def to_ll(x, y):
        return (x / m_lon, y / m_lat)

    pts = MultiPoint([Point(*to_xy(r.lon, r.lat)) for r in cents.itertuples()])
    minx, miny, maxx, maxy = county_poly.bounds
    env = box(*to_xy(minx, miny), *to_xy(maxx, maxy)).buffer(5000)
    vd = voronoi_diagram(pts, envelope=env, edges=False)
    rank_by_xy = {to_xy(r.lon, r.lat): int(r.subarea_rank) for r in cents.itertuples()}
    county_xy = shp_transform(lambda x, y, z=None: to_xy(x, y), county_poly)
    cells = {}
    for geom in vd.geoms:
        if geom.is_empty:
            continue
        c = geom.centroid
        best_rank, best_d = None, 1e99
        for (sx, sy), rank in rank_by_xy.items():
            d = (c.x - sx) ** 2 + (c.y - sy) ** 2
            if d < best_d:
                best_d, best_rank = d, rank
        clipped = geom.intersection(county_xy)
        if clipped.is_empty or best_rank is None:
            continue
        cells[best_rank] = shp_transform(lambda x, y, z=None: to_ll(x, y), clipped)
    return cells, lat0


def ring(poly):
    if poly is None or poly.is_empty:
        return None
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    if poly.geom_type != "Polygon":
        return None
    simp = poly.simplify(0.001, preserve_topology=True)
    coords = list(simp.exterior.coords)
    if len(coords) > 80:
        step = max(1, len(coords) // 60)
        coords = coords[::step]
        if coords[0] != coords[-1]:
            coords.append(coords[0])
    return [[float(x), float(y)] for x, y in coords]


def area_km2(poly, lat0):
    if poly is None or poly.is_empty:
        return 0.0
    m_lat = 111_320.0
    m_lon = 111_320.0 * np.cos(np.radians(lat0))
    xy = shp_transform(lambda x, y, z=None: (x * m_lon, y * m_lat), poly)
    return float(xy.area) / 1e6


def main() -> int:
    blocks = pd.read_parquet(ART / "la_blocks.parquet")
    if "lon" not in blocks.columns:
        blocks = blocks.rename(columns={"blklondd": "lon", "blklatdd": "lat"})
    county = gpd.read_file(COUNTY)
    county_poly = county[county.GEOID.astype(str) == LA_FIPS].to_crs(4326).geometry.unary_union

    out = {
        "_note": (
            "Catchment polygons = Voronoi cells of the 6 subarea centroids, clipped to "
            "LA County. Non-overlapping. n_blocks = LODES block centroids assigned by "
            "the same nearest-centroid rule. weight = demand share from passenger crosswalk."
        ),
        "home": [],
        "work": [],
    }
    for endpoint in ("home", "work"):
        cw = pd.read_csv(ART / f"passenger_{endpoint}_crosswalk.csv")
        cw = cw[cw.county_fips == 6037].copy()
        cw["subarea_rank"] = cw.subarea_rank.astype(int)
        n_by = assign(blocks, cw).value_counts().to_dict()
        cells, lat0 = voronoi_cells(cw, county_poly)
        for _, c in cw.sort_values("subarea_rank").iterrows():
            rank = int(c.subarea_rank)
            poly = cells.get(rank)
            out[endpoint].append(
                {
                    "endpoint": endpoint,
                    "subarea_rank": rank,
                    "faf5_node_id": int(c.node_id),
                    "lon": float(c.lon),
                    "lat": float(c.lat),
                    "weight": float(c.weight),
                    "n_blocks": int(n_by.get(rank, 0)),
                    "area_km2": round(area_km2(poly, lat0), 2),
                    "hull_ring": ring(poly),
                }
            )
        print(endpoint)
        for r in out[endpoint]:
            print(
                f"  r{r['subarea_rank']} weight={r['weight']:.3f} "
                f"blocks={r['n_blocks']} km2={r['area_km2']}"
            )
    path = ART / "la_subarea_catchments.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
