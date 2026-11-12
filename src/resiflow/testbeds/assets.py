"""Synthetic FAF-like asset attributes for testbed links.

TNTP networks carry no asset data. The sourced flood cost path (T24 CP25 roads, T30 bridges, Rostami tunnels) needs
HPMS class, urban area, state, NHS status, structure geometry and tunnel geometry, so the testbeds assign them here.
Everything assigned is synthetic and labelled by the ``synthetic_assets`` column; existing values are never overwritten.

HPMS functional class rule (documented because it is a modelling choice, tested in tests/test_testbed_assets.py):
    motorway, freeway            -> 1 (Interstate)
    trunk                        -> 2 (other freeways and expressways)
    primary, arterial            -> 3 (other principal arterial)
    secondary                    -> 4 (minor arterial)
    tertiary, collector          -> 5 (major collector)
    unclassified                 -> 6 (minor collector)
    local, local_access, residential, service -> 7 (local)
NHS rule: classes 1-3 are on the National Highway System, others are not.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

HPMS_FCLASS_BY_ROAD_CLASS: dict[str, int] = {
    "motorway": 1,
    "freeway": 1,
    "trunk": 2,
    "primary": 3,
    "arterial": 3,
    "secondary": 4,
    "tertiary": 5,
    "collector": 5,
    "unclassified": 6,
    "local": 7,
    "local_access": 7,
    "residential": 7,
    "service": 7,
}
NHS_MAX_FCLASS = 3
LANE_WIDTH_M = 3.65
BRIDGE_SPAN_M = 30.0
TUNNEL_BORES = 2


def hpms_fclass_from_road_class(road_classification: pd.Series) -> pd.Series:
    """Map a road class name to HPMS F-class 1-7. Unknown names raise, so a new class cannot silently become 'local'."""
    key = road_classification.astype(str).str.strip().str.lower()
    mapped = key.map(HPMS_FCLASS_BY_ROAD_CLASS)
    unknown = sorted(set(key[mapped.isna()]))
    if unknown:
        raise ValueError(f"no HPMS F-class rule for road_classification values {unknown}; add them to HPMS_FCLASS_BY_ROAD_CLASS")
    return mapped.astype(int)


def _set_if_absent(out, column: str, values) -> None:
    """Assign ``values`` only where the column is missing or null (never overwrite supplied data)."""
    if column not in out.columns:
        out[column] = values
        return
    missing = out[column].isna()
    if missing.any():
        out.loc[missing, column] = pd.Series(values, index=out.index).loc[missing]


def apply_synthetic_asset_attributes(links, *, state_fips: str, state_usps: str, urban_code: str):
    """Return a copy of ``links`` with the attributes the sourced cost path reads (see docs/testbed_suite/SPEC.md, 3a).

    Expects ``road_classification``, ``road_label`` (road, bridge, tunnel), ``length`` (m) and ``lanes``.
    """
    required = {"road_classification", "road_label", "length", "lanes"}
    missing = sorted(required - set(links.columns))
    if missing:
        raise ValueError(f"links are missing columns needed to assign synthetic assets: {missing}")
    out = links.copy()
    label = out["road_label"].astype(str).str.lower()
    fclass = hpms_fclass_from_road_class(out["road_classification"])
    length = pd.to_numeric(out["length"], errors="coerce")
    lanes = pd.to_numeric(out["lanes"], errors="coerce").fillna(1)

    _set_if_absent(out, "hpms_fclass", fclass)
    _set_if_absent(out, "STATE", state_usps)
    _set_if_absent(out, "bridge_state", state_fips)
    _set_if_absent(out, "urban_code", str(urban_code))
    _set_if_absent(out, "nhs_designation", pd.Series(np.where(fclass <= NHS_MAX_FCLASS, "NHS", None), index=out.index, dtype=object))

    is_bridge = label.eq("bridge")
    _set_if_absent(out, "structure_length_m", length.where(is_bridge))
    _set_if_absent(out, "averageWidth", (LANE_WIDTH_M * lanes + 2.0).where(is_bridge, LANE_WIDTH_M * lanes))
    spans = np.ceil(length.where(is_bridge) / BRIDGE_SPAN_M).clip(lower=1)
    _set_if_absent(out, "main_unit_spans", spans)

    is_tunnel = label.eq("tunnel")
    if is_tunnel.any() or "tunnel_bores" in out.columns:
        _set_if_absent(out, "tunnel_bores", pd.Series(np.where(is_tunnel, TUNNEL_BORES, np.nan), index=out.index))
        _set_if_absent(out, "tunnel_length_m", length.where(is_tunnel))
        _set_if_absent(out, "tunnel_length_m_min", length.where(is_tunnel))
        _set_if_absent(out, "tunnel_lanes_total", (lanes * TUNNEL_BORES).where(is_tunnel))
        _set_if_absent(out, "tunnel_roadway_width_m", (LANE_WIDTH_M * lanes).where(is_tunnel))

    out["synthetic_assets"] = True
    return out


def required_columns_for_sourced_costs(road_labels) -> dict[str, list[str]]:
    """Columns the sourced cost path reads, per asset type present in ``road_labels``."""
    present = {str(x).lower() for x in road_labels}
    needed: dict[str, list[str]] = {
        "all": ["road_label", "length", "lanes", "urban", "flood_depth_surface", "flood_depth_river"],
    }
    if "road" in present:
        needed["road"] = ["hpms_fclass"]
    if "bridge" in present:
        needed["bridge"] = ["averageWidth", "structure_length_m"]
    if "tunnel" in present:
        needed["tunnel"] = ["tunnel_length_m", "tunnel_lanes_total", "tunnel_roadway_width_m"]
    return needed


__all__ = [
    "HPMS_FCLASS_BY_ROAD_CLASS",
    "apply_synthetic_asset_attributes",
    "hpms_fclass_from_road_class",
    "required_columns_for_sourced_costs",
]
