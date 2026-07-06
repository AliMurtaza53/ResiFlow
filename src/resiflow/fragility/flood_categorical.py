"""Flood categorical fragility: intensity to damage_level."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

def compute_damage_level_on_flooded_roads(
    fldType: str,
    road_classification: str,
    trunk_road: str,
    road_label: str,
    fldDepth: float,
) -> str:
    """
    Determines the damage level of roads based on flood type, road classification,
        and flood depth.

    Parameters:
        fldType (str): Type of flood ("surface" or "river").
        road_classification (str): Classification of road (e.g., "Motorway", "A Road").
        trunk_road (bool): Indicates if the road is a trunk road (True/False).
        road_label (str): Label of the road (e.g., "road", "tunnel", "bridge").
        fldDepth (float): Flood depth in meters.

    Returns:
        str: Damage level categorized as "no", "minor", "moderate", "extensive",
            or "severe"
    """

    if fldType == "flood":
        fldType = "river"
    depth = fldDepth * 100  # convert from m to cm
    rc = ("" if road_classification is None else str(road_classification)).strip()
    rc_lower = rc.lower()
    trunk_flag = bool(trunk_road) if trunk_road is not None else False
    road_label = "" if road_label is None else road_label

    # FAF/US classifications
    if rc_lower in {"motorway", "motorway_link", "trunk", "primary", "secondary", "tertiary", "service", "unclassified"}:
        major = rc_lower in {"motorway", "motorway_link", "trunk", "primary", "secondary"}
        if fldType == "surface":
            if major:
                if depth < 50:
                    return "no"
                elif 50 <= depth < 200:
                    return "no"
                elif 200 <= depth < 600:
                    return "minor"
                elif depth >= 600:
                    return "moderate"
            else:
                if depth < 50:
                    return "no"
                elif 50 <= depth < 200:
                    return "minor"
                elif 200 <= depth < 600:
                    return "minor"
                elif depth >= 600:
                    return "moderate"
        elif fldType == "river":
            if major:
                if depth < 50:
                    return "no"
                elif 50 <= depth < 100:
                    return "minor"
                elif 100 <= depth < 200:
                    return "moderate"
                elif 200 <= depth < 600:
                    return "extensive"
                elif depth >= 600:
                    return "severe"
            else:
                if depth <= 0:
                    return "no"
                elif 0 < depth < 50:
                    return "minor"
                elif 50 <= depth < 200:
                    return "moderate"
                elif 200 <= depth < 600:
                    return "extensive"
                elif depth >= 600:
                    return "severe"

        return np.nan

    # UK classifications (legacy)
    if fldType == "surface":
        if road_label == "tunnel" and (
            road_classification == "Motorway"
            or (road_classification == "A Road" and trunk_flag)
        ):
            if depth < 50:
                return "no"
            elif 50 <= depth < 100:
                return "minor"
            elif 100 <= depth < 200:
                return "moderate"
            elif 200 <= depth < 600:
                return "extensive"
            elif depth >= 600:
                return "severe"
            else:
                return np.nan
        elif road_label != "tunnel" and (
            road_classification == "Motorway"
            or (road_classification == "A Road" and trunk_flag)
        ):
            if depth < 50:
                return "no"
            elif 50 <= depth < 100:
                return "no"
            elif 100 <= depth < 200:
                return "no"
            elif 200 <= depth < 600:
                return "minor"
            elif depth >= 600:
                return "moderate"
            else:
                return np.nan
        else:
            if depth < 50:
                return "no"
            elif 50 <= depth < 100:
                return "no"
            elif 100 <= depth < 200:
                return "minor"
            elif 200 <= depth < 600:
                return "minor"
            elif depth >= 600:
                return "moderate"
            else:
                return np.nan

    elif fldType == "river":
        if road_label == "tunnel" and (
            road_classification == "Motorway"
            or (road_classification == "A Road" and trunk_flag)
        ):
            if depth < 50:
                return "no"
            elif 50 <= depth < 100:
                return "minor"
            elif 100 <= depth < 200:
                return "minor"
            elif 200 <= depth < 600:
                return "moderate"
            elif depth >= 600:
                return "extensive"
            else:
                return np.nan
        elif road_label != "tunnel" and (
            road_classification == "Motorway"
            or (road_classification == "A Road" and trunk_flag)
        ):
            if depth < 50:
                return "no"
            elif 50 <= depth < 100:
                return "minor"
            elif 100 <= depth < 200:
                return "moderate"
            elif 200 <= depth < 600:
                return "extensive"
            elif depth >= 600:
                return "severe"
            else:
                return np.nan
        else:
            if depth <= 0:
                return "no"
            elif 0 < depth < 50:
                return "minor"
            elif 50 <= depth < 100:
                return "moderate"
            elif 100 <= depth < 200:
                return "moderate"
            elif 200 <= depth < 600:
                return "extensive"
            elif depth >= 600:
                return "severe"
            else:
                return np.nan
    else:
        logging.info("Please enter the type of flood!")


def compute_damage_levels_on_flooded_roads_vectorized(
    fldType: str,
    road_classification: pd.Series,
    trunk_road: pd.Series,
    road_label: pd.Series,
    fldDepth: pd.Series,
) -> pd.Series:
    """Vectorized equivalent of compute_damage_level_on_flooded_roads()."""

    if fldType == "flood":
        fldType = "river"
    depth_cm = pd.to_numeric(fldDepth, errors="coerce") * 100.0
    rc_raw = road_classification.fillna("").astype(str).str.strip()
    rc_lower = rc_raw.str.lower()
    trunk_flag = (
        pd.Series(trunk_road, index=rc_raw.index)
        .fillna(False)
        .astype(str)
        .str.lower()
        .isin({"true", "1", "yes"})
    )
    road_label = pd.Series(road_label, index=rc_raw.index).fillna("").astype(str)

    faf_us_classes = {
        "motorway",
        "motorway_link",
        "trunk",
        "primary",
        "secondary",
        "tertiary",
        "service",
        "unclassified",
    }
    major_faf = rc_lower.isin({"motorway", "motorway_link", "trunk", "primary", "secondary"})
    faf_mask = rc_lower.isin(faf_us_classes)
    uk_major = rc_raw.eq("Motorway") | (rc_raw.eq("A Road") & trunk_flag)
    tunnel_mask = road_label.eq("tunnel")

    result = pd.Series(np.nan, index=rc_raw.index, dtype=object)

    if fldType == "surface":
        # FAF/US classifications
        faf_major_mask = faf_mask & major_faf
        faf_minor_mask = faf_mask & ~major_faf
        result.loc[faf_major_mask & (depth_cm < 200)] = "no"
        result.loc[faf_major_mask & (depth_cm >= 200) & (depth_cm < 600)] = "minor"
        result.loc[faf_major_mask & (depth_cm >= 600)] = "moderate"

        result.loc[faf_minor_mask & (depth_cm < 50)] = "no"
        result.loc[faf_minor_mask & (depth_cm >= 50) & (depth_cm < 600)] = "minor"
        result.loc[faf_minor_mask & (depth_cm >= 600)] = "moderate"

        # UK legacy classifications
        uk_tunnel = ~faf_mask & uk_major & tunnel_mask
        uk_major_notunnel = ~faf_mask & uk_major & ~tunnel_mask
        uk_other = ~faf_mask & ~uk_major

        result.loc[uk_tunnel & (depth_cm < 50)] = "no"
        result.loc[uk_tunnel & (depth_cm >= 50) & (depth_cm < 100)] = "minor"
        result.loc[uk_tunnel & (depth_cm >= 100) & (depth_cm < 200)] = "moderate"
        result.loc[uk_tunnel & (depth_cm >= 200) & (depth_cm < 600)] = "extensive"
        result.loc[uk_tunnel & (depth_cm >= 600)] = "severe"

        result.loc[uk_major_notunnel & (depth_cm < 50)] = "no"
        result.loc[uk_major_notunnel & (depth_cm >= 50) & (depth_cm < 100)] = "no"
        result.loc[uk_major_notunnel & (depth_cm >= 100) & (depth_cm < 200)] = "no"
        result.loc[uk_major_notunnel & (depth_cm >= 200) & (depth_cm < 600)] = "minor"
        result.loc[uk_major_notunnel & (depth_cm >= 600)] = "moderate"

        result.loc[uk_other & (depth_cm < 50)] = "no"
        result.loc[uk_other & (depth_cm >= 50) & (depth_cm < 100)] = "no"
        result.loc[uk_other & (depth_cm >= 100) & (depth_cm < 200)] = "minor"
        result.loc[uk_other & (depth_cm >= 200) & (depth_cm < 600)] = "minor"
        result.loc[uk_other & (depth_cm >= 600)] = "moderate"

    elif fldType == "river":
        faf_major_mask = faf_mask & major_faf
        faf_minor_mask = faf_mask & ~major_faf

        result.loc[faf_major_mask & (depth_cm < 50)] = "no"
        result.loc[faf_major_mask & (depth_cm >= 50) & (depth_cm < 100)] = "minor"
        result.loc[faf_major_mask & (depth_cm >= 100) & (depth_cm < 200)] = "moderate"
        result.loc[faf_major_mask & (depth_cm >= 200) & (depth_cm < 600)] = "extensive"
        result.loc[faf_major_mask & (depth_cm >= 600)] = "severe"

        result.loc[faf_minor_mask & (depth_cm <= 0)] = "no"
        result.loc[faf_minor_mask & (depth_cm > 0) & (depth_cm < 50)] = "minor"
        result.loc[faf_minor_mask & (depth_cm >= 50) & (depth_cm < 200)] = "moderate"
        result.loc[faf_minor_mask & (depth_cm >= 200) & (depth_cm < 600)] = "extensive"
        result.loc[faf_minor_mask & (depth_cm >= 600)] = "severe"

        uk_tunnel = ~faf_mask & uk_major & tunnel_mask
        uk_major_notunnel = ~faf_mask & uk_major & ~tunnel_mask
        uk_other = ~faf_mask & ~uk_major

        result.loc[uk_tunnel & (depth_cm < 50)] = "no"
        result.loc[uk_tunnel & (depth_cm >= 50) & (depth_cm < 100)] = "minor"
        result.loc[uk_tunnel & (depth_cm >= 100) & (depth_cm < 200)] = "minor"
        result.loc[uk_tunnel & (depth_cm >= 200) & (depth_cm < 600)] = "moderate"
        result.loc[uk_tunnel & (depth_cm >= 600)] = "extensive"

        result.loc[uk_major_notunnel & (depth_cm < 50)] = "no"
        result.loc[uk_major_notunnel & (depth_cm >= 50) & (depth_cm < 100)] = "minor"
        result.loc[uk_major_notunnel & (depth_cm >= 100) & (depth_cm < 200)] = "moderate"
        result.loc[uk_major_notunnel & (depth_cm >= 200) & (depth_cm < 600)] = "extensive"
        result.loc[uk_major_notunnel & (depth_cm >= 600)] = "severe"

        result.loc[uk_other & (depth_cm <= 0)] = "no"
        result.loc[uk_other & (depth_cm > 0) & (depth_cm < 50)] = "minor"
        result.loc[uk_other & (depth_cm >= 50) & (depth_cm < 200)] = "moderate"
        result.loc[uk_other & (depth_cm >= 200) & (depth_cm < 600)] = "extensive"
        result.loc[uk_other & (depth_cm >= 600)] = "severe"
    else:
        logging.info("Please enter the type of flood!")

    return result