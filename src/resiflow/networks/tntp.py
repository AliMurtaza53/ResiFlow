"""TNTP (Transportation Networks Test Problem) format parsers and link builders."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

NodeIdFormatter = Callable[[str | int], str]

DEFAULT_BPR_ALPHA = 0.15
DEFAULT_BPR_BETA = 4.0


def read_metadata(lines: list[str]) -> dict[str, Any]:
    """Parse TNTP metadata tags from file lines."""
    metadata: dict[str, Any] = {}
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        comment_pos = stripped.find("~")
        if comment_pos >= 0:
            stripped = stripped[:comment_pos].strip()
        if not stripped:
            continue
        start = stripped.find("<")
        end = stripped.find(">")
        if start < 0 or end < 0 or start >= end:
            continue
        tag = stripped[start + 1 : end]
        value = stripped[end + 1 :].strip()
        if tag == "END OF METADATA":
            metadata["END OF METADATA"] = line_number
            return metadata
        metadata[tag] = value
    return metadata


def _iter_data_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def read_tntp_nodes(path: str | Path) -> pd.DataFrame:
    """Parse a TNTP node coordinate file."""
    rows: list[dict[str, Any]] = []
    for line in _iter_data_lines(Path(path)):
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("node"):
            continue
        parts = stripped.replace(";", "").split()
        if len(parts) >= 3:
            rows.append({"node": parts[0], "x": float(parts[1]), "y": float(parts[2])})
    if not rows:
        raise ValueError(f"No nodes parsed from {path}")
    return pd.DataFrame(rows)


def read_tntp_links(path: str | Path) -> pd.DataFrame:
    """Parse a TNTP network file including BPR parameters."""
    rows: list[dict[str, Any]] = []
    for line in _iter_data_lines(Path(path)):
        stripped = line.strip()
        if not stripped or stripped.startswith("<") or stripped.startswith("~"):
            continue
        parts = stripped.replace(";", "").split()
        if len(parts) < 10:
            continue
        rows.append(
            {
                "init_node": parts[0],
                "term_node": parts[1],
                "capacity": float(parts[2]),
                "length": float(parts[3]),
                "free_flow_time": float(parts[4]),
                "b": float(parts[5]),
                "power": float(parts[6]),
                "speed_limit": float(parts[7]),
                "toll": float(parts[8]),
                "link_type": parts[9],
            }
        )
    if not rows:
        raise ValueError(f"No links parsed from {path}")
    return pd.DataFrame(rows)


def read_tntp_trips(
    path: str | Path,
    *,
    node_id_formatter: NodeIdFormatter | None = None,
) -> pd.DataFrame:
    """Parse a TNTP trips file into assignment OD rows."""
    fmt = node_id_formatter or (lambda raw: str(raw))
    rows: list[dict[str, float | str]] = []
    origin: str | None = None
    pair_re = re.compile(r"(\d+)\s*:\s*([0-9.]+)")
    for line in _iter_data_lines(Path(path)):
        stripped = line.strip()
        if not stripped or stripped.startswith("<"):
            continue
        if stripped.lower().startswith("origin"):
            origin = stripped.split()[1]
            continue
        if origin is None:
            continue
        for destination, flow_raw in pair_re.findall(stripped):
            flow = float(flow_raw)
            if flow > 0.0 and destination != origin:
                rows.append(
                    {
                        "origin_node": fmt(origin),
                        "destination_node": fmt(destination),
                        "Car21": flow,
                    }
                )
    if not rows:
        raise ValueError(f"No OD rows parsed from {path}")
    out = pd.DataFrame(rows)
    return out.groupby(["origin_node", "destination_node"], as_index=False)["Car21"].sum()


def build_node_geometries(
    nodes: pd.DataFrame,
    *,
    node_id_formatter: NodeIdFormatter | None = None,
) -> dict[str, Point]:
    """Build shapely Points from TNTP node X/Y (treated as WGS84 lon/lat)."""
    fmt = node_id_formatter or (lambda raw: str(raw))
    geometries: dict[str, Point] = {}
    for row in nodes.itertuples(index=False):
        geometries[fmt(row.node)] = Point(float(row.x), float(row.y))
    return geometries


def tntp_capacity_to_lanes(capacity_vph: float) -> int:
    if capacity_vph >= 20_000:
        return 3
    if capacity_vph >= 10_000:
        return 2
    return 1


def tntp_capacity_to_road_class(capacity_vph: float) -> str:
    """Heuristic coarse class for TNTP links (testbed-friendly)."""
    if capacity_vph >= 20_000:
        return "freeway"
    if capacity_vph >= 15_000:
        return "arterial"
    if capacity_vph >= 8_000:
        return "collector"
    return "local"


def flow_cap_plph_from_tntp(capacity_vph: float, lanes: int) -> float:
    return float(capacity_vph) / max(int(lanes), 1)


def links_to_geodataframe(
    nodes: pd.DataFrame,
    links: pd.DataFrame,
    *,
    node_id_formatter: NodeIdFormatter | None = None,
    edge_id_formatter: Callable[[str, str, int], str] | None = None,
    source_crs: str = "EPSG:4326",
    output_crs: str | None = None,
    road_class_fn: Callable[[float], str] | None = None,
    urban: int = 1,
) -> gpd.GeoDataFrame:
    """Convert TNTP nodes/links to a ResiFlow-compatible link GeoDataFrame."""
    fmt = node_id_formatter or (lambda raw: str(raw))
    class_fn = road_class_fn or tntp_capacity_to_road_class
    node_geoms = build_node_geometries(nodes, node_id_formatter=fmt)
    rows: list[dict[str, Any]] = []

    for idx, row in enumerate(links.itertuples(index=False)):
        start = str(row.init_node)
        end = str(row.term_node)
        from_id = fmt(start)
        to_id = fmt(end)
        if edge_id_formatter is not None:
            e_id = edge_id_formatter(start, end, idx)
        else:
            e_id = f"{from_id}_{to_id}_{idx}"

        capacity_vph = float(row.capacity)
        lanes = tntp_capacity_to_lanes(capacity_vph)
        fft = float(row.free_flow_time)
        speed_mph = (float(row.length) / (fft / 60.0)) if fft > 0.0 else 35.0

        rows.append(
            {
                "e_id": e_id,
                "from_id": from_id,
                "to_id": to_id,
                "road_classification": class_fn(capacity_vph),
                "lanes": lanes,
                "tntp_capacity_vph": capacity_vph,
                "tntp_free_flow_time": fft,
                "tntp_b": float(row.b),
                "tntp_power": float(row.power),
                "flow_cap_plph": flow_cap_plph_from_tntp(capacity_vph, lanes),
                "urban": urban,
                "average_toll_cost": float(row.toll),
                "free_flow_speeds": min(speed_mph, 45.0),
                "network_source": "tntp",
                "geometry": LineString([node_geoms[from_id], node_geoms[to_id]]),
            }
        )

    gdf = gpd.GeoDataFrame(rows, crs=source_crs)
    if output_crs is not None:
        gdf = gdf.to_crs(output_crs)
    return gdf
