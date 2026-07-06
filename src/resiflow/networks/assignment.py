"""Map per-link profile columns using assignment tiers."""

from __future__ import annotations

import pandas as pd

from resiflow.networks.base import LEGACY_COMBINED_TO_TIER
from resiflow.networks.profiles import coerce_profile_dict


def tier_series(frame: pd.DataFrame) -> pd.Series:
    """Return canonical assignment_tier series from a link table."""
    if "assignment_tier" in frame.columns:
        return frame["assignment_tier"].astype(str)
    if "combined_label" in frame.columns:
        return (
            frame["combined_label"]
            .astype(str)
            .map(lambda label: LEGACY_COMBINED_TO_TIER.get(label, "arterial"))
        )
    raise ValueError("Link table missing assignment_tier and combined_label columns")


def map_tier_profile(frame: pd.DataFrame, profile_dict: dict[str, float]) -> pd.Series:
    """Map a tier-keyed (or legacy-keyed) profile dict onto link rows."""
    normalized = coerce_profile_dict(profile_dict)
    tiers = tier_series(frame)
    mapped = tiers.map(normalized)
    if mapped.isna().any():
        fallback = normalized.get("arterial")
        if fallback is not None:
            mapped = mapped.fillna(fallback)
    return mapped
