"""Physical-hazard eligibility of explicitly identified centroid access links."""
from __future__ import annotations

import pandas as pd


def centroid_connector_mask(links: pd.DataFrame) -> pd.Series:
    """Recognize native FAF Class 50 and explicit generated-connector tags.

    Missing road classes remain physical. IDs, geometry and proximity never
    determine eligibility; generated connectors may lack a FAF class.
    """
    mask = pd.Series(False, index=links.index)
    if "faf5_class" in links:
        mask |= pd.to_numeric(links["faf5_class"], errors="coerce").eq(50).fillna(False)
    for col in ("assignment_tier", "network_class", "road_classification"):
        if col in links:
            mask |= links[col].astype("string").str.strip().str.lower().eq("centroid_connector").fillna(False)
    return mask


def assert_physical_exposure(links: pd.DataFrame, exposure: pd.DataFrame) -> None:
    """Reject stale virtual-link intersections rather than silently pricing them."""
    ids = set(links.loc[centroid_connector_mask(links), "e_id"].astype(str))
    found = sorted(ids & set(exposure["e_id"].astype(str)))
    if found:
        raise ValueError(
            f"Centroid connectors in physical hazard exposure: {found[:10]}. "
            "Rerun stage 2 with the centroid-connector hazard exemption."
        )


def assert_centroid_flood_state(links: pd.DataFrame) -> None:
    """Require clean stage-2 state before recovery can use a legacy artifact."""
    virtual = links.loc[centroid_connector_mask(links)]
    if virtual.empty:
        return
    bad = pd.Series(False, index=virtual.index)
    for col in ("flood_depth_max", "intensity_primary"):
        if col in virtual:
            bad |= pd.to_numeric(virtual[col], errors="coerce").fillna(float("inf")).ne(0)
    if "damage_level_max" in virtual:
        bad |= virtual.damage_level_max.fillna("invalid").ne("no")
    for col in ("max_speed", "max_speed_truck"):
        if col in virtual:
            expected = pd.to_numeric(virtual["free_flow_speeds"], errors="coerce")
            actual = pd.to_numeric(virtual[col], errors="coerce")
            bad |= actual.isna() | expected.isna() | (actual - expected).abs().gt(1e-12)
    if bad.any():
        raise ValueError(
            "Hazard-restricted centroid connectors in recovery input: "
            f"{virtual.loc[bad, 'e_id'].astype(str).head(10).tolist()}. "
            "Rerun stages 2 and 3; do not reuse contaminated flood artifacts."
        )
