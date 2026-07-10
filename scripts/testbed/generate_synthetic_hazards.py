#!/usr/bin/env python3
"""Generate synthetic hazard rasters for the Sioux Falls multihazard testbed.

All fields are built in the network CRS (EPSG:9311) using generators from
``resiflow.hazards.synthetic``. See ``scripts/testbed/README.md`` for event
definitions and peak values.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import geopandas as gpd

from resiflow.hazards.synthetic import (
    SyntheticRaster,
    bridge_interior,
    gaussian_hotspot,
    linear_corridor,
    snow_band,
)
from resiflow.networks.tntp import build_node_geometries, read_tntp_links, read_tntp_nodes
from resiflow.testbeds import load_testbed

MULTIHAZARD_VARIANT = "toy_sioux_falls_multihazard"
OUTPUT_CRS = load_testbed("sioux_falls").output_crs
FLOODED_PAIR = ("10", "15")
# PLACEHOLDER — confirm with advisor: disconnect corridor endpoints (nodes 6–8 area).
DISCONNECT_CORRIDOR = (("sf_6", "y"), ("sf_8", "y"))  # filled after load

# Event keys used across hazard types.
EVENT_MISS = "0"
EVENT_BRIDGE = "1"
EVENT_DISCONNECT = "3"

FLOOD_PEAK_M = 0.50  # meters; above 30 cm closure threshold
COASTAL_PEAK_M = 0.55
RIVER_PEAK_M = 0.48
PGA_PEAK_G = 0.45  # PLACEHOLDER — confirm with advisor
LANDSLIDE_PEAK_MM = 180.0
WINTER_STORM_PEAK_MM = 120.0
WINTER_STORM_MODERATE_MM = 60.0


def _load_sioux_links() -> gpd.GeoDataFrame:
    tb = load_testbed("sioux_falls")
    nodes = read_tntp_nodes(tb.node_path())
    links = read_tntp_links(tb.net_path())
    geoms = build_node_geometries(nodes)
    rows = []
    for idx, row in enumerate(links.itertuples(index=False)):
        start, end = str(row.init_node), str(row.term_node)
        e_id = f"sf_{start}_{end}_{idx}"
        rows.append(
            {
                "e_id": e_id,
                "from_id": f"sf_{start}",
                "to_id": f"sf_{end}",
                "geometry": __import__("shapely").geometry.LineString([geoms[start], geoms[end]]),
            }
        )
    gdf = gpd.GeoDataFrame(rows, crs=tb.source_crs).to_crs(OUTPUT_CRS)
    return gdf


def _flooded_edge_ids(links: gpd.GeoDataFrame) -> list[str]:
    out = []
    for idx, row in enumerate(links.itertuples(index=False)):
        a = row.from_id.replace("sf_", "")
        b = row.to_id.replace("sf_", "")
        pair = tuple(sorted((a, b)))
        if pair == FLOODED_PAIR:
            out.append(row.e_id)
    return out


def _node_coord(links: gpd.GeoDataFrame, node_num: str) -> tuple[float, float]:
    node_id = f"sf_{node_num}"
    sub = links.loc[links["from_id"] == node_id]
    if sub.empty:
        sub = links.loc[links["to_id"] == node_id]
    if sub.empty:
        raise ValueError(f"Node {node_num} not found on network")
    geom = sub.iloc[0].geometry
    if sub.iloc[0].from_id == node_id:
        return (geom.coords[0][0], geom.coords[0][1])
    return (geom.coords[-1][0], geom.coords[-1][1])


def _write_raster(raster: SyntheticRaster, path: Path) -> None:
    raster.write_geotiff(path)


def _miss_field(links: gpd.GeoDataFrame, *, peak: float, unit: str) -> SyntheticRaster:
    minx, miny, maxx, maxy = links.total_bounds
    # Hotspot 50 km outside the network (guaranteed zero link intersection).
    center = (maxx + 50_000.0, maxy + 50_000.0)
    return gaussian_hotspot(
        links,
        center,
        sigma_m=500.0,
        peak_intensity=peak,
        resolution_m=10.0,
        crs=OUTPUT_CRS,
    )


def build_event_catalog(links: gpd.GeoDataFrame) -> dict:
    flooded_ids = _flooded_edge_ids(links)
    minx, miny, maxx, maxy = links.total_bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2

    n6 = _node_coord(links, "6")
    n8 = _node_coord(links, "8")
    n10 = _node_coord(links, "10")
    n1 = _node_coord(links, "1")
    n13 = _node_coord(links, "13")
    n20 = _node_coord(links, "20")

    catalog: dict = {
        "variant": MULTIHAZARD_VARIANT,
        "crs": OUTPUT_CRS,
        "written_files": [],
        "events": {
            EVENT_MISS: {
                "purpose": "zero intersection sanity check",
                "generator": "gaussian_hotspot (offset 50km outside extent)",
            },
            EVENT_BRIDGE: {
                "purpose": "bridge 10-15 bottleneck on many shortest paths",
                "generator": "bridge_interior on flooded edge ids",
                "flooded_edge_ids": flooded_ids,
            },
            EVENT_DISCONNECT: {
                "purpose": "severe corridor crossing north part of network",
                "generator": "linear_corridor between nodes 6 and 8, 80m width",
            },
        },
        "hazards": {},
    }

    def flood_surface_events() -> dict[str, SyntheticRaster]:
        return {
            EVENT_MISS: _miss_field(links, peak=FLOOD_PEAK_M, unit="m"),
            EVENT_BRIDGE: bridge_interior(
                links, flooded_ids, peak_intensity=FLOOD_PEAK_M, crs=OUTPUT_CRS
            ),
            EVENT_DISCONNECT: linear_corridor(
                links, n6, n8, peak_intensity=FLOOD_PEAK_M, corridor_width_m=80.0, crs=OUTPUT_CRS
            ),
        }

    def flood_river_events() -> dict[str, SyntheticRaster]:
        return {
            EVENT_MISS: _miss_field(links, peak=RIVER_PEAK_M, unit="m"),
            EVENT_BRIDGE: gaussian_hotspot(
                links, n10, sigma_m=120.0, peak_intensity=RIVER_PEAK_M, crs=OUTPUT_CRS
            ),
            EVENT_DISCONNECT: linear_corridor(
                links, n1, n13, peak_intensity=RIVER_PEAK_M, corridor_width_m=100.0, crs=OUTPUT_CRS
            ),
        }

    def flood_coastal_events() -> dict[str, SyntheticRaster]:
        return {
            EVENT_MISS: _miss_field(links, peak=COASTAL_PEAK_M, unit="m"),
            EVENT_BRIDGE: bridge_interior(
                links, flooded_ids, peak_intensity=COASTAL_PEAK_M, crs=OUTPUT_CRS
            ),
            EVENT_DISCONNECT: linear_corridor(
                links, n6, n20, peak_intensity=COASTAL_PEAK_M, corridor_width_m=90.0, crs=OUTPUT_CRS
            ),
        }

    def earthquake_events() -> dict[str, SyntheticRaster]:
        return {
            EVENT_MISS: _miss_field(links, peak=PGA_PEAK_G, unit="g"),
            EVENT_BRIDGE: gaussian_hotspot(
                links, n10, sigma_m=200.0, peak_intensity=PGA_PEAK_G, crs=OUTPUT_CRS
            ),
            EVENT_DISCONNECT: gaussian_hotspot(
                links,
                ((n6[0] + n8[0]) / 2, (n6[1] + n8[1]) / 2),
                sigma_m=400.0,
                peak_intensity=PGA_PEAK_G * 1.2,
                crs=OUTPUT_CRS,
            ),
        }

    def landslide_events() -> dict[str, SyntheticRaster]:
        return {
            EVENT_MISS: _miss_field(links, peak=LANDSLIDE_PEAK_MM, unit="mm"),
            EVENT_BRIDGE: bridge_interior(
                links,
                flooded_ids,
                peak_intensity=LANDSLIDE_PEAK_MM,
                crs=OUTPUT_CRS,
            ),
            EVENT_DISCONNECT: linear_corridor(
                links,
                n6,
                n8,
                peak_intensity=LANDSLIDE_PEAK_MM,
                corridor_width_m=25.0,
                crs=OUTPUT_CRS,
            ),
        }

    def winter_storm_events() -> dict[str, SyntheticRaster]:
        band_y = cy
        return {
            EVENT_MISS: _miss_field(links, peak=WINTER_STORM_PEAK_MM, unit="mm"),
            EVENT_BRIDGE: bridge_interior(
                links,
                flooded_ids,
                peak_intensity=WINTER_STORM_PEAK_MM,
                crs=OUTPUT_CRS,
            ),
            EVENT_DISCONNECT: snow_band(
                links,
                center_y=band_y,
                band_width_m=(maxy - miny) * 0.95,
                peak_intensity_mm=WINTER_STORM_MODERATE_MM,
                crs=OUTPUT_CRS,
            ),
        }

    hazard_builders = {
        "flood_surface": (flood_surface_events, "m_depth", FLOOD_PEAK_M),
        "flood_river": (flood_river_events, "m_depth", RIVER_PEAK_M),
        "flood_coastal": (flood_coastal_events, "m_depth", COASTAL_PEAK_M),
        "earthquake": (earthquake_events, "g_pga", PGA_PEAK_G),
        "landslide": (landslide_events, "mm_displacement", LANDSLIDE_PEAK_MM),
        "winter_storm": (winter_storm_events, "mm_ice", WINTER_STORM_PEAK_MM),
    }

    for hazard_name, (builder, unit, peak) in hazard_builders.items():
        catalog["hazards"][hazard_name] = {
            "intensity_unit": unit,
            "peak_design_value": peak,
            "events": list(builder().keys()),
        }

    return catalog, hazard_builders


def generate_all(output_dir: Path) -> Path:
    links = _load_sioux_links()
    catalog, builders = build_event_catalog(links)
    root = output_dir / "inputs" / "sioux_falls_multihazard"
    root.mkdir(parents=True, exist_ok=True)

    for hazard_name, (builder, unit, _peak) in builders.items():
        hazard_dir = root / hazard_name
        hazard_dir.mkdir(parents=True, exist_ok=True)
        for event_key, raster in builder().items():
            out_path = hazard_dir / f"event_{event_key}.tif"
            if raster.intensity_unit == "m_depth":
                raster = SyntheticRaster(
                    data=raster.data,
                    transform=raster.transform,
                    crs=raster.crs,
                    nodata=raster.nodata,
                    intensity_unit=unit,
                )
            _write_raster(raster, out_path)
            catalog["written_files"].append(
                str(out_path.relative_to(output_dir)).replace("\\", "/")
            )

    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Toy data root (will create inputs/sioux_falls_multihazard/)",
    )
    args = parser.parse_args()
    manifest = generate_all(args.output_dir)
    print(f"Wrote multihazard rasters and {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
