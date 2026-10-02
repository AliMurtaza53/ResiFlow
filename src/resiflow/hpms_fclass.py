"""HPMS functional-class (F_Class) harmonization.

Shared bucketings consumed by T08 (assignment tier), T20 (damage-level
threshold major/minor AND the sophisticated/simple/ordinary scheme), and
T22 (C1-C6 damage-curve family) wiring -- one canonical source for each
bucketing so the three tables don't silently diverge on where a given
link lands. Matches docs/FLOOD_TABLE_REVIEW.md Section 1's "Proposed FAF
harmonization" table.

Source for field codes: FAF5 Network Data Dictionary (FHWA), F_Class item:
1=Interstate, 2=Principal Arterial-Other Freeways/Expressways,
3=Principal Arterial-Other, 4=Minor Arterial, 5=Major Collector,
6=Minor Collector, 7=Local. Confirmed against the real downloaded
geodatabase's own descriptive stats (Desktop/data/faf5_data/
FAF5_network_attribute_descriptive_stats.csv): F_Class is 95.5%
non-missing (4.5% null, matching the harmonization doc's own figure),
range 1-10 -- codes 8/9/10 are NOT in the FHWA-documented 1-7 range and
are treated the same as null (see docs/FLOOD_TABLE_REVIEW.md Section 1:
"Where F_Class is null... or 10, fall back by faf5_class").
"""

from __future__ import annotations

import pandas as pd

_VALID_FCLASS = frozenset({1, 2, 3, 4, 5, 6, 7})

# Fallback hpms_fclass by FAF5's own Class code, used ONLY when the real
# F_Class is null or out-of-range (~4.5% of links). FAF5 Class and HPMS
# F_Class are both "functional class"-flavored schemes but not identical;
# this crosswalk is a documented approximation, not a second authoritative
# source -- flagged per-row, not silent:
#   11/13/33 (Interstate / non-freeway-interstate AK / express lane) -> F1
#   12 (other controlled-access)                                     -> F2
#   21/22 (system ramp / ramp), 23 (collector/distributor lane)      -> F2
#     (interchange ramps and freeway C/D lanes are freeway-adjacent)
#   14 (FAF's own "arterial OR major collector" merge)               -> F3
#     (the "Principal Arterial - Other" case; FAF5 doesn't record which
#     sub-case a given Class-14 link actually is, so this likely skews
#     true major-collector links slightly toward F3 instead of F5 --
#     documented approximation, not resolvable without re-deriving from
#     the sparse HPMS LRS transfer, ~20% coverage)
#   15 (local road), 16/17/18/19/36 (frontage/circle/turn-lane/access/admin) -> F7
#   41 (ferry) -> no meaningful HPMS functional class; left null (not mapped)
_FALLBACK_BY_FAF_CLASS: dict[int, int] = {
    11: 1, 13: 1, 33: 1,
    12: 2, 21: 2, 22: 2, 23: 2,
    14: 3,
    15: 7, 16: 7, 17: 7, 18: 7, 19: 7, 36: 7,
}

_TIER_BY_FCLASS: dict[int, str] = {
    1: "freeway", 2: "freeway",
    3: "arterial", 4: "arterial",
    5: "collector", 6: "collector",
    7: "local_access",
}


def derive_hpms_fclass(raw_f_class: pd.Series, faf5_class: pd.Series) -> pd.Series:
    """hpms_fclass (nullable Int64, 1-7): real F_Class where valid (1-7),
    else the documented FAF5-Class-based fallback above (~4.5% of links).
    NaN when neither source classifies the link (e.g. ferries)."""
    f = pd.to_numeric(raw_f_class, errors="coerce")
    valid = f.isin(_VALID_FCLASS)
    out = f.where(valid)
    cls = pd.to_numeric(faf5_class, errors="coerce")
    fallback = cls.map(_FALLBACK_BY_FAF_CLASS)
    out = out.fillna(fallback)
    return out.astype("Int64")


def assignment_tier_from_fclass(hpms_fclass: pd.Series) -> pd.Series:
    """T08/T08b facility tier: F1,F2->freeway; F3,F4->arterial;
    F5,F6->collector; F7->local_access. NA where hpms_fclass is NA."""
    return hpms_fclass.map(_TIER_BY_FCLASS)


def damage_threshold_major_from_fclass(hpms_fclass: pd.Series) -> "pd.Series[bool]":
    """T20's 2-way major/minor split: major = F1-F3, minor = F4-F7.

    Replaces the prior name-string classifier (motorway/trunk/primary/
    secondary vs. tertiary/local) with the real HPMS functional class --
    see docs/FLOOD_TABLE_REVIEW.md Section 1. Nullable boolean: NA
    propagates where hpms_fclass itself is NA (caller must supply a
    fallback for links with no hpms_fclass at all, e.g. non-FAF5 test
    fixtures).
    """
    return hpms_fclass.le(3)


def flood_road_class_sophistication(
    nhs_designation: pd.Series, road_label: pd.Series | None = None
) -> pd.Series:
    """van Ginkel/Li et al. 3-class scheme for T20 (US candidate) and T22
    (C1-C6 family): sophisticated = on NHS + tunnel; simple = on NHS, no
    tunnel; ordinary = not on NHS.

    Uses FAF5's own real ``NHS`` field (any non-null code -- 1/3/4/7/8/9/
    10/11/12 per the FAF5 Network Data Dictionary all mean "on NHS in some
    capacity"; null/absent means not on NHS), not a proxy -- the T20
    US-candidate table's own header notes this project previously had no
    attribute to split sophisticated from simple within NHS roads and
    resolved them identically; real tunnel presence (NTI-matched, carried
    as this project's existing ``road_label`` column -- "tunnel" vs.
    "bridge"/"road", NOT the separate yes/no ``road_tunnel`` column) now
    does that split for real.
    """
    on_nhs = nhs_designation.notna()
    out = pd.Series("ordinary", index=nhs_designation.index, dtype=object)
    out.loc[on_nhs] = "simple"
    if road_label is not None:
        tunnel = road_label.astype(str).str.strip().str.lower().eq("tunnel")
        out.loc[on_nhs & tunnel] = "sophisticated"
    return out


__all__ = [
    "derive_hpms_fclass",
    "assignment_tier_from_fclass",
    "damage_threshold_major_from_fclass",
    "flood_road_class_sophistication",
]
