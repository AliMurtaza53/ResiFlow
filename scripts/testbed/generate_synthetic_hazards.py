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
import numpy as np

from resiflow.hazards.synthetic import (
    SyntheticRaster,
    bridge_interior,
    gaussian_hotspot,
    linear_corridor,
    snow_band,
)
from resiflow.networks.tntp import build_node_geometries, read_tntp_links, read_tntp_nodes
from resiflow.parameters import get_parameter
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

FLOOD_PEAK_M = get_parameter("testbed_synthetic_hazards", "flood_peak_m", 0.50)  # meters; above 30 cm closure threshold
COASTAL_PEAK_M = get_parameter("testbed_synthetic_hazards", "coastal_peak_m", 0.55)
RIVER_PEAK_M = get_parameter("testbed_synthetic_hazards", "river_peak_m", 0.48)
PGA_PEAK_G = get_parameter("testbed_synthetic_hazards", "pga_peak_g", 0.45)  # PLACEHOLDER — confirm with advisor
LANDSLIDE_PEAK_MM = get_parameter("testbed_synthetic_hazards", "landslide_peak_mm", 180.0)
WINTER_STORM_PEAK_MM = get_parameter("testbed_synthetic_hazards", "winter_storm_peak_mm", 120.0)
WINTER_STORM_MODERATE_MM = get_parameter("testbed_synthetic_hazards", "winter_storm_moderate_mm", 60.0)

# Intensity ladder (events 4 low, 5 high, 6 extreme) so every hazard has a case below, at and well above its closure point.
# Peaks live in parameters/unified_parameters.json (testbed_synthetic_hazards.intensity_ladder); all PLACEHOLDER test inputs.
EVENT_LOW = "4"
EVENT_HIGH = "5"
EVENT_EXTREME = "6"
_LADDER_DEFAULT = {
    "flood_m": {"4": 0.20, "5": 1.00, "6": 2.50},
    "river_m": {"4": 0.20, "5": 1.00, "6": 2.50},
    "coastal_m": {"4": 0.20, "5": 1.00, "6": 2.50},
    "pga_g": {"4": 0.20, "5": 0.80, "6": 1.20},
    "landslide_mm": {"4": 60.0, "5": 500.0, "6": 1500.0},
    "winter_mm": {"4": 30.0, "5": 260.0, "6": 450.0},
}
LADDER = get_parameter("testbed_synthetic_hazards", "intensity_ladder", _LADDER_DEFAULT)


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


def _ladder_events(links, key, builder_for_peak, n6, n8, n10, centre):
    """Events 4/5/6 for one hazard: low (below closure), high (closes the bridge pair and the 6-8 corridor), extreme (network-wide)."""
    out = {}
    peaks = LADDER[key]
    out[EVENT_LOW] = builder_for_peak(float(peaks[EVENT_LOW]), "local")
    out[EVENT_HIGH] = builder_for_peak(float(peaks[EVENT_HIGH]), "corridor")
    out[EVENT_EXTREME] = builder_for_peak(float(peaks[EVENT_EXTREME]), "broad")
    return out


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
            EVENT_LOW: {"purpose": "intensity ladder: below the closure point (slowdown only)", "generator": "ladder, bridge pair"},
            EVENT_HIGH: {"purpose": "intensity ladder: above closure (bridge pair or 6-8 corridor)", "generator": "ladder, corridor or bridge pair"},
            EVENT_EXTREME: {"purpose": "intensity ladder: extreme, network-wide hotspot or band", "generator": "ladder, broad hotspot"},
        },
        "intensity_ladder": LADDER,
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

    span_x, span_y = maxx - minx, maxy - miny

    def _shape(kind, peak, *, hotspot_sigma, corridor_a, corridor_b, corridor_w, broad_sigma):
        """local = bridge pair, corridor = line between two nodes, broad = hotspot covering most of the network."""
        if kind == "local":
            return bridge_interior(links, flooded_ids, peak_intensity=peak, crs=OUTPUT_CRS)
        if kind == "corridor":
            return linear_corridor(links, corridor_a, corridor_b, peak_intensity=peak, corridor_width_m=corridor_w, crs=OUTPUT_CRS)
        return gaussian_hotspot(links, (cx, cy), sigma_m=broad_sigma, peak_intensity=peak, crs=OUTPUT_CRS)

    def with_ladder(base_fn, key, **shape):
        def run():
            events = base_fn()
            events.update(_ladder_events(links, key, lambda peak, kind: _shape(kind, peak, **shape), n6, n8, n10, (cx, cy)))
            return events
        return run

    broad = max(span_x, span_y) * 0.45
    flood_shape = dict(hotspot_sigma=None, corridor_a=n6, corridor_b=n8, corridor_w=80.0, broad_sigma=broad)
    quake_shape = dict(hotspot_sigma=None, corridor_a=n6, corridor_b=n8, corridor_w=800.0, broad_sigma=broad)
    slide_shape = dict(hotspot_sigma=None, corridor_a=n6, corridor_b=n8, corridor_w=60.0, broad_sigma=broad)

    def winter_ladder():
        events = winter_storm_events()
        peaks = LADDER["winter_mm"]
        events[EVENT_LOW] = snow_band(links, center_y=cy, band_width_m=span_y * 0.95, peak_intensity_mm=float(peaks[EVENT_LOW]), crs=OUTPUT_CRS)
        events[EVENT_HIGH] = bridge_interior(links, flooded_ids, peak_intensity=float(peaks[EVENT_HIGH]), crs=OUTPUT_CRS)
        events[EVENT_EXTREME] = snow_band(links, center_y=cy, band_width_m=span_y * 0.95, peak_intensity_mm=float(peaks[EVENT_EXTREME]), crs=OUTPUT_CRS)
        return events

    hazard_builders = {
        "flood_surface": (with_ladder(flood_surface_events, "flood_m", **flood_shape), "m_depth", FLOOD_PEAK_M),
        "flood_river": (with_ladder(flood_river_events, "river_m", **flood_shape), "m_depth", RIVER_PEAK_M),
        "flood_coastal": (with_ladder(flood_coastal_events, "coastal_m", **flood_shape), "m_depth", COASTAL_PEAK_M),
        "earthquake": (with_ladder(earthquake_events, "pga_g", **quake_shape), "g_pga", PGA_PEAK_G),
        "landslide": (with_ladder(landslide_events, "landslide_mm", **slide_shape), "mm_displacement", LANDSLIDE_PEAK_MM),
        "winter_storm": (winter_ladder, "mm_ice", WINTER_STORM_PEAK_MM),
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

    # Sa(1.0 s) companion for the earthquake field: HAZUS bridge shaking cost reads Sa(1.0 s), not PGA, and is $0 without it.
    ratio = float(get_parameter("testbed_synthetic_hazards", "sa1p0_to_pga_ratio", 0.67))  # PLACEHOLDER, see parameters
    sa_dir = root / "earthquake_sa1p0"
    sa_dir.mkdir(parents=True, exist_ok=True)
    for event_key, raster in builders["earthquake"][0]().items():
        valid = raster.data != raster.nodata
        scaled = SyntheticRaster(
            data=np.where(valid, raster.data * ratio, raster.data).astype(raster.data.dtype),
            transform=raster.transform,
            crs=raster.crs,
            nodata=raster.nodata,
            intensity_unit="g_sa1p0",
        )
        sa_path = sa_dir / f"event_{event_key}.tif"
        _write_raster(scaled, sa_path)
        catalog["written_files"].append(str(sa_path.relative_to(output_dir)).replace("\\", "/"))
    catalog["hazards"]["earthquake"]["sa1p0_companion"] = {"folder": "earthquake_sa1p0", "ratio_to_pga": ratio}

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
