"""HAZUS 6.1 highway bridge/road classification, fragility, and direct cost.

Replaces the flood-shim direct-damage pathway for earthquake and landslide
(see disruption/build.py's build_earthquake_link_disruption /
build_landslide_link_disruption for the shim this exists to replace, and
scripts/3_damage_analysis.py's calculate_damage() docstring for the
flood-only mechanism both hazards were silently routed through until
2026-08-20).

Source: FEMA Hazus Earthquake Model Technical Manual, Hazus 6.1, July 2024
(https://www.fema.gov/sites/default/files/documents/fema_hazus-earthquake-model-technical-manual-6-1.pdf),
Chapter 7 "Direct Physical Damage to Transportation Systems", and Hazus
Inventory Technical Manual, Hazus 6.1, August 2024
(https://www.fema.gov/sites/default/files/documents/fema_hazus-inventory-technical-manual-6.1.pdf),
Chapter 9. Every table/equation cited below was verified against the actual
FEMA PDF (page-image rendering, not just text-layer extraction -- an earlier
extraction pass had a one-row misalignment in Table 7-6 and dropped Table
7-7's embedded stacked-fraction equations entirely; both were re-verified
visually against rendered pages before being transcribed here). Confirmed
2026-08-20.

Damage-state vocabulary: HAZUS uses None/Slight/Moderate/Extensive/Complete
throughout; this project's fragility modules
(fragility/{earthquake,landslide,winter_storm}_categorical.py) already use
no/minor/moderate/extensive/severe identically across all three -- a clean
1:1 crosswalk, no ambiguity (HAZUS_DAMAGE_STATES below, in that order).

KNOWN LIMITATIONS (documented, not silent):
  - Kshape (the period-shape ground-shaking correction gated by Table 7-1's
    Ishape flag, part of the Technical Manual's 8-step modification
    procedure, Sec 7.1.6.2) is NOT implemented -- its exact formula wasn't
    captured from the source manual. Ground-shaking medians are used as
    published in Table 7-6 without this secondary correction. This affects
    only the ground-shaking axis's medians, not ground-failure/PGD (which
    uses the fully-implemented f1/f2 modifiers instead).
  - When both a ground-shaking (Sa) and ground-failure (PGD) intensity are
    available for the same bridge, this module computes each axis's damage
    state independently and takes the more severe (governing) result --
    a documented simplification, not HAZUS's possibly-more-nuanced combined
    treatment (the source manual's exact combination rule for simultaneous
    shaking+PGD damage wasn't independently re-verified here).
  - HWB28 (catch-all "all other bridges") has no class-specific fragility
    curve in Table 7-6 -- this module uses HWB1's curve (the least-refined
    "major bridge, non-seismic-era" case) as a conservative default for
    HWB28, not a HAZUS-published value for that class specifically.
  - Earthquake direct cost is bridges-only and ground-shaking-only (Sa(1.0s),
    wired 2026-08-20). Roads report $0 for earthquake -- correct per HAZUS
    (Table 7-5 road fragility is PGD/ground-failure-only, no shaking curve),
    not a gap, since this project has no liquefaction PGD computed for the
    earthquake hazard itself. Earthquake bridges also report $0 whenever no
    Sa(1.0s) raster exists for the active hazard_source (e.g.
    RealEarthquakeSource/earthquake_nshm has no Sa companion prepared).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

HAZUS_DAMAGE_STATES = ("none", "slight", "moderate", "extensive", "complete")

# Crosswalk to this project's existing 5-level vocabulary (already used
# identically in fragility/{earthquake,landslide,winter_storm}_categorical.py).
HAZUS_TO_RESIFLOW_DAMAGE_LEVEL = {
    "none": "no",
    "slight": "minor",
    "moderate": "moderate",
    "extensive": "extensive",
    "complete": "severe",
}

CA_SEISMIC_YEAR_CUTOFF = 1975
NON_CA_SEISMIC_YEAR_CUTOFF = 1990


def _safe_str(value) -> str:
    """Coerce a possibly-None/NaN/non-string value (as read from a pandas
    row -- missing NBI fields surface as float('nan'), not None) to a
    string, safely. ``(value or "")`` is NOT safe for this: NaN is truthy
    in Python, so ``float('nan') or ""`` evaluates to the NaN, not "" --
    confirmed the hard way (AttributeError: 'float' object has no attribute
    'strip') the first time this module ran against a real pandas row."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


def _safe_float(value) -> float | None:
    """Coerce a possibly-None/NaN value to float or None (never NaN)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


@dataclass(frozen=True)
class BridgeFragility:
    """One HWB class's fragility parameters (Table 7-6) and PGD modifiers (Table 7-7)."""

    hwb_class: str
    sa_medians_g: tuple[float, float, float, float]  # Slight, Moderate, Extensive, Complete
    sa_beta: float
    pgd_medians_in: tuple[float, float, float, float]
    pgd_beta: float
    k3d_equation: str
    f1_formula: str  # "1" or "geometry" (0.5L/(N*W*sin(skew)))
    f2_formula: str  # "1", "sin_skew", or "geometry"


# Table 7-6 (Technical Manual pp.7-6/7-7), verified via page-image rendering
# 2026-08-20 after an earlier text-extraction pass mis-aligned rows starting
# at HWB10. All PGD medians are the shared base value (3.9/3.9/3.9/13.8 in)
# before per-class f1/f2 modifiers (Table 7-7) are applied -- see
# apply_pgd_modifiers().
_TABLE_7_6: dict[str, tuple[tuple[float, float, float, float], str]] = {
    # hwb_class: (sa_medians_g, k3d_equation)
    "HWB1": ((0.40, 0.50, 0.70, 0.90), "EQ1"),
    "HWB2": ((0.60, 0.90, 1.10, 1.70), "EQ1"),
    "HWB3": ((0.80, 1.00, 1.20, 1.70), "EQ1"),
    "HWB4": ((0.80, 1.00, 1.20, 1.70), "EQ1"),
    "HWB5": ((0.25, 0.35, 0.45, 0.70), "EQ1"),
    "HWB6": ((0.30, 0.50, 0.60, 0.90), "EQ1"),
    "HWB7": ((0.50, 0.80, 1.10, 1.70), "EQ1"),
    "HWB8": ((0.35, 0.45, 0.55, 0.80), "EQ2"),
    "HWB9": ((0.60, 0.90, 1.30, 1.60), "EQ3"),
    "HWB10": ((0.60, 0.90, 1.10, 1.50), "EQ2"),
    "HWB11": ((0.90, 0.90, 1.10, 1.50), "EQ3"),
    "HWB12": ((0.25, 0.35, 0.45, 0.70), "EQ4"),
    "HWB13": ((0.30, 0.50, 0.60, 0.90), "EQ4"),
    "HWB14": ((0.50, 0.80, 1.10, 1.70), "EQ1"),
    "HWB15": ((0.75, 0.75, 0.75, 1.10), "EQ5"),
    "HWB16": ((0.90, 0.90, 1.10, 1.50), "EQ3"),
    "HWB17": ((0.25, 0.35, 0.45, 0.70), "EQ1"),
    "HWB18": ((0.30, 0.50, 0.60, 0.90), "EQ1"),
    "HWB19": ((0.50, 0.80, 1.10, 1.70), "EQ1"),
    "HWB20": ((0.35, 0.45, 0.55, 0.80), "EQ2"),
    "HWB21": ((0.60, 0.90, 1.30, 1.60), "EQ3"),
    "HWB22": ((0.60, 0.90, 1.10, 1.50), "EQ2"),
    "HWB23": ((0.90, 0.90, 1.10, 1.50), "EQ3"),
    "HWB24": ((0.25, 0.35, 0.45, 0.70), "EQ6"),
    "HWB25": ((0.30, 0.50, 0.60, 0.90), "EQ6"),
    "HWB26": ((0.75, 0.75, 0.75, 1.10), "EQ7"),
    "HWB27": ((0.75, 0.75, 0.75, 1.10), "EQ7"),
    "HWB28": ((0.80, 1.00, 1.20, 1.70), "EQ1"),  # no published class-specific curve; HWB1 used as documented default
}

_SHARED_PGD_MEDIANS_IN = (3.9, 3.9, 3.9, 13.8)
_SA_BETA = 0.6
_PGD_BETA = 0.2

# Table 7-7 (Technical Manual pp.7-9/7-10), verified via page-image
# rendering 2026-08-20 -- an earlier text-extraction pass returned these
# cells blank (stacked-fraction math objects the text layer couldn't
# linearize), not that they're undefined in the source.
# "1"/"sin_skew" classes: f1=1, f2=sin(skew). "geometry" classes:
# f1=f2=0.5*L/(N*W*sin(skew)) (identical formula for both).
_TABLE_7_7_F1_F2: dict[str, tuple[str, str]] = {
    "HWB1": ("1", "1"),
    "HWB2": ("1", "1"),
    "HWB3": ("1", "1"),
    "HWB4": ("1", "1"),
    "HWB5": ("geometry", "geometry"),
    "HWB6": ("geometry", "geometry"),
    "HWB7": ("geometry", "geometry"),
    "HWB8": ("1", "sin_skew"),
    "HWB9": ("1", "sin_skew"),
    "HWB10": ("1", "sin_skew"),
    "HWB11": ("1", "sin_skew"),
    "HWB12": ("geometry", "geometry"),
    "HWB13": ("geometry", "geometry"),
    "HWB14": ("geometry", "geometry"),
    "HWB15": ("1", "sin_skew"),
    "HWB16": ("1", "sin_skew"),
    "HWB17": ("geometry", "geometry"),
    "HWB18": ("geometry", "geometry"),
    "HWB19": ("geometry", "geometry"),
    "HWB20": ("1", "sin_skew"),
    "HWB21": ("1", "sin_skew"),
    "HWB22": ("geometry", "geometry"),
    "HWB23": ("geometry", "geometry"),
    "HWB24": ("geometry", "geometry"),
    "HWB25": ("geometry", "geometry"),
    "HWB26": ("1", "sin_skew"),
    "HWB27": ("1", "sin_skew"),
    "HWB28": ("1", "1"),
}

# Table 7-2 (Technical Manual p.7-0): K3D = 1 + A/(N-B).
_K3D_COEFFICIENTS: dict[str, tuple[float, float]] = {
    "EQ1": (0.25, 1.0),
    "EQ2": (0.33, 0.0),
    "EQ3": (0.33, 1.0),
    "EQ4": (0.09, 1.0),
    "EQ5": (0.05, 0.0),
    "EQ6": (0.20, 1.0),
    "EQ7": (0.10, 0.0),
}

# Table 11-10 (Technical Manual Sec 11.3.1.1) -- damage ratio (fraction of
# replacement value) per damage state, best-estimate values. Roadways only
# distinguish 4 tiers in the source (Extensive and Complete are combined at
# 0.70); mapped onto this project's 5-level "extensive"/"severe" split by
# using the same 0.70 ratio for both -- HAZUS's own table doesn't
# distinguish them for roadways, so neither does this crosswalk.
DAMAGE_RATIO_BY_ASSET_AND_STATE: dict[str, dict[str, float]] = {
    "road": {"none": 0.0, "slight": 0.05, "moderate": 0.20, "extensive": 0.70, "complete": 0.70},
    "bridge": {"none": 0.0, "slight": 0.03, "moderate": 0.08, "extensive": 0.25, "complete": 1.00},
    "tunnel": {"none": 0.0, "slight": 0.01, "moderate": 0.30, "extensive": 0.70, "complete": 1.00},
}


def bridge_complete_damage_ratio(num_spans: float | None) -> float:
    """Table 11-10 footnote: bridge Complete-state ratio is 2/spans when spans > 2, else 1.00."""
    if num_spans is not None and not math.isnan(num_spans) and num_spans > 2:
        return 2.0 / num_spans
    return 1.00


# Table 9-3 (Inventory Technical Manual, 2021$/sq ft), by HWB class.
BRIDGE_REPLACEMENT_COST_USD_PER_SQFT: dict[str, float] = {
    "HWB1": 636, "HWB2": 583, "HWB3": 424, "HWB4": 504, "HWB5": 398, "HWB6": 398,
    "HWB7": 504, "HWB8": 318, "HWB9": 424, "HWB10": 292, "HWB11": 318, "HWB12": 583,
    "HWB13": 583, "HWB14": 742, "HWB15": 583, "HWB16": 742, "HWB17": 398, "HWB18": 398,
    "HWB19": 504, "HWB20": 398, "HWB21": 504, "HWB22": 371, "HWB23": 424, "HWB24": 583,
    "HWB25": 636, "HWB26": 795, "HWB27": 795, "HWB28": 318,
}

# Table 9-2 (Inventory Technical Manual, 2019$/km).
ROAD_REPLACEMENT_COST_USD_PER_KM = {"major": 6_668_000.0, "urban": 3_334_000.0}


def classify_hwb(
    *,
    structure_kind_code: str | None,
    structure_type_code: str | None,
    state: str | None,
    year_built: float | None,
    num_spans: float | None,
    max_span_length_m: float | None,
) -> str:
    """Classify a bridge into HWB1-28 per Table 7-1 (Technical Manual pp.7-0-7-2).

    Reading order confirmed from the manual's surrounding text (Sec 7.1.3):
    max-span length > 150m overrides everything (HWB1/2, "major bridge"),
    then single-span overrides (HWB3/4), then NBI structure code selects the
    class family, then state+year_built selects conventional vs. seismic
    design within that family, then (steel families only) whether max span
    is under 20m selects between the HWB12-16 and HWB24-27 variants.
    Anything that doesn't match falls to HWB28 (catch-all).
    """
    year_built = _safe_float(year_built)
    num_spans = _safe_float(num_spans)
    max_span_length_m = _safe_float(max_span_length_m)

    is_ca = _safe_str(state).strip().upper() == "CA"
    cutoff = CA_SEISMIC_YEAR_CUTOFF if is_ca else NON_CA_SEISMIC_YEAR_CUTOFF
    is_seismic_era = year_built is not None and year_built >= cutoff

    if max_span_length_m is not None and max_span_length_m > 150.0:
        return "HWB2" if is_seismic_era else "HWB1"

    if num_spans is not None and num_spans == 1:
        return "HWB4" if is_seismic_era else "HWB3"

    nbi_code = f"{_safe_str(structure_kind_code).strip()}{_safe_str(structure_type_code).strip().zfill(2)}"
    try:
        nbi_code_int = int(nbi_code)
    except ValueError:
        return "HWB28"

    short_span = max_span_length_m is not None and max_span_length_m < 20.0

    if 101 <= nbi_code_int <= 106:
        return "HWB7" if is_seismic_era else ("HWB6" if is_ca else "HWB5")
    if nbi_code_int in (205, 206):
        return "HWB9" if is_seismic_era else "HWB8"
    if 201 <= nbi_code_int <= 206:
        return "HWB11" if is_seismic_era else "HWB10"
    if 301 <= nbi_code_int <= 306:
        if is_seismic_era:
            return "HWB19" if is_ca else "HWB14"
        if short_span:
            return "HWB25" if is_ca else "HWB24"
        return "HWB13" if is_ca else "HWB12"
    if 402 <= nbi_code_int <= 410:
        if is_seismic_era:
            return "HWB16" if is_ca else "HWB16"
        if short_span:
            return "HWB27" if is_ca else "HWB26"
        return "HWB15"
    if 501 <= nbi_code_int <= 506:
        return "HWB19" if is_seismic_era else ("HWB18" if is_ca else "HWB17")
    if nbi_code_int in (605, 606):
        return "HWB21" if is_seismic_era else "HWB20"
    if 601 <= nbi_code_int <= 607:
        return "HWB23" if is_seismic_era else "HWB22"

    return "HWB28"


def compute_k3d(hwb_class: str, num_spans: float | None) -> float:
    """Table 7-2: K3D = 1 + A/(N-B). Falls back to 1.0 (no correction) if spans unknown."""
    equation = _TABLE_7_6[hwb_class][1]
    a, b = _K3D_COEFFICIENTS[equation]
    if num_spans is None or math.isnan(num_spans) or (num_spans - b) == 0:
        return 1.0
    return 1.0 + a / (num_spans - b)


def get_fragility(hwb_class: str) -> BridgeFragility:
    sa_medians, k3d_eq = _TABLE_7_6[hwb_class]
    f1, f2 = _TABLE_7_7_F1_F2[hwb_class]
    return BridgeFragility(
        hwb_class=hwb_class,
        sa_medians_g=sa_medians,
        sa_beta=_SA_BETA,
        pgd_medians_in=_SHARED_PGD_MEDIANS_IN,
        pgd_beta=_PGD_BETA,
        k3d_equation=k3d_eq,
        f1_formula=f1,
        f2_formula=f2,
    )


def _pgd_modifier(formula: str, *, num_spans, span_width_m, bridge_length_m, skew_degrees) -> float:
    if formula == "1":
        return 1.0
    skew_rad = math.radians(skew_degrees) if skew_degrees is not None and not math.isnan(skew_degrees) else None
    if formula == "sin_skew":
        if skew_rad is None or math.isclose(math.sin(skew_rad), 0.0):
            return 1.0  # skew unknown or 0/99 (NBI "major variation") -- no correction, documented fallback
        return abs(math.sin(skew_rad))
    if formula == "geometry":
        if (
            num_spans is None or math.isnan(num_spans) or num_spans == 0
            or span_width_m is None or math.isnan(span_width_m) or span_width_m == 0
            or bridge_length_m is None or math.isnan(bridge_length_m)
            or skew_rad is None or math.isclose(math.sin(skew_rad), 0.0)
        ):
            return 1.0  # insufficient geometry -- no correction, documented fallback
        return (0.5 * bridge_length_m) / (num_spans * span_width_m * abs(math.sin(skew_rad)))
    raise ValueError(f"Unknown f1/f2 formula: {formula}")


def _lognormal_exceedance_prob(intensity: float, median: float, beta: float) -> float:
    """P(damage >= state | intensity) per HAZUS's standard lognormal fragility form."""
    if intensity <= 0 or median <= 0:
        return 0.0
    from scipy.stats import norm

    return float(norm.cdf(math.log(intensity / median) / beta))


def damage_state_probabilities(
    exceedance_probs: tuple[float, float, float, float],
) -> dict[str, float]:
    """Convert 4 exceedance probabilities (Slight..Complete) into discrete
    P(each of 5 states), per HAZUS's standard discrete-damage-state construction."""
    p_slight, p_moderate, p_extensive, p_complete = exceedance_probs
    return {
        "none": 1.0 - p_slight,
        "slight": p_slight - p_moderate,
        "moderate": p_moderate - p_extensive,
        "extensive": p_extensive - p_complete,
        "complete": p_complete,
    }


def expected_damage_ratio(
    state_probs: dict[str, float], *, asset_type: str, num_spans: float | None = None
) -> float:
    ratios = dict(DAMAGE_RATIO_BY_ASSET_AND_STATE[asset_type])
    if asset_type == "bridge":
        ratios["complete"] = bridge_complete_damage_ratio(num_spans)
    return sum(state_probs[state] * ratios[state] for state in HAZUS_DAMAGE_STATES)


def bridge_direct_cost_usd(
    *,
    hwb_class: str,
    sa_1p0_g: float | None,
    pgd_in: float | None,
    num_spans: float | None,
    span_width_m: float | None,
    bridge_length_m: float | None,
    skew_degrees: float | None,
    deck_area_sqft: float,
) -> tuple[float, str]:
    """HAZUS 6.1 bridge direct repair cost (USD) and governing damage level
    (in this project's own no/minor/moderate/extensive/severe vocabulary).

    Combines ground-shaking (Sa) and ground-failure (PGD) axes by computing
    each independently and taking the more severe (higher expected damage
    ratio) -- see module docstring's KNOWN LIMITATIONS for why this,
    specifically, was chosen over a probabilistically-combined treatment.
    """
    fragility = get_fragility(hwb_class)
    k3d = compute_k3d(hwb_class, num_spans)

    best_ratio = 0.0
    best_state = "none"

    if sa_1p0_g is not None and not math.isnan(sa_1p0_g):
        adjusted_medians = tuple(m * k3d for m in fragility.sa_medians_g)
        exceedance = tuple(
            _lognormal_exceedance_prob(sa_1p0_g, median, fragility.sa_beta) for median in adjusted_medians
        )
        probs = damage_state_probabilities(exceedance)
        ratio = expected_damage_ratio(probs, asset_type="bridge", num_spans=num_spans)
        if ratio > best_ratio:
            best_ratio = ratio
            best_state = max(HAZUS_DAMAGE_STATES, key=lambda s: probs[s])

    if pgd_in is not None and not math.isnan(pgd_in):
        f1_mult = _pgd_modifier(
            fragility.f1_formula,
            num_spans=num_spans, span_width_m=span_width_m,
            bridge_length_m=bridge_length_m, skew_degrees=skew_degrees,
        )
        f2_mult = _pgd_modifier(
            fragility.f2_formula,
            num_spans=num_spans, span_width_m=span_width_m,
            bridge_length_m=bridge_length_m, skew_degrees=skew_degrees,
        )
        m_slight, m_moderate, m_extensive, m_complete = fragility.pgd_medians_in
        adjusted_medians = (m_slight, m_moderate * f1_mult, m_extensive * f1_mult, m_complete * f2_mult)
        exceedance = tuple(
            _lognormal_exceedance_prob(pgd_in, median, fragility.pgd_beta) for median in adjusted_medians
        )
        probs = damage_state_probabilities(exceedance)
        ratio = expected_damage_ratio(probs, asset_type="bridge", num_spans=num_spans)
        if ratio > best_ratio:
            best_ratio = ratio
            best_state = max(HAZUS_DAMAGE_STATES, key=lambda s: probs[s])

    unit_cost = BRIDGE_REPLACEMENT_COST_USD_PER_SQFT.get(hwb_class, BRIDGE_REPLACEMENT_COST_USD_PER_SQFT["HWB28"])
    replacement_value = unit_cost * deck_area_sqft
    cost_usd = best_ratio * replacement_value
    return cost_usd, HAZUS_TO_RESIFLOW_DAMAGE_LEVEL[best_state]


# Table 7-5 (Technical Manual, Highway Transportation System section):
# roadway ground-failure (PGD-only -- HAZUS publishes no ground-shaking
# roadway fragility) medians in inches, beta=0.7 for both classes.
_ROAD_PGD_FRAGILITY: dict[str, tuple[tuple[float, float, float], float]] = {
    "major": ((12.0, 24.0, 60.0), 0.7),  # Slight, Moderate, Extensive/Complete combined
    "urban": ((6.0, 12.0, 24.0), 0.7),
}

# HAZUS's own roadway table doesn't distinguish rural/urban the way this
# project's road_classification does -- "major" (HRD1) is the Base Highway
# Network (interstates + principal/minor arterials, matching NBI Item 12's
# own definition already used elsewhere in this project -- see
# nbi_schema.md's HIGHWAY_DISTRICT/FUNCTIONAL_CLASS notes); everything else
# maps to "urban" (HRD2), regardless of actual rural/urban location -- a
# documented approximation, not a HAZUS-published crosswalk.
_MAJOR_ROAD_CLASSIFICATIONS = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"}


def road_direct_cost_usd(
    *, road_classification: str | None, pgd_in: float | None, length_km: float, lanes: float | None = None
) -> tuple[float, str]:
    """HAZUS 6.1 roadway direct repair cost (USD) and governing damage level.

    PGD-only (Table 7-5) -- HAZUS publishes no ground-shaking fragility for
    roadways, only for bridges/tunnels. Replacement value from Table 9-2
    ($6.668M/km major 4-lane, $3.334M/km urban 2-lane, 2019$) -- these are
    whole-segment figures already calibrated to a specific lane count, not
    a per-lane rate; --lanes is accepted but not currently used to scale
    cost (documented, not a bug: matching HAZUS's own table structure,
    which doesn't offer a per-lane figure to scale from).
    """
    tier = "major" if _safe_str(road_classification).strip().lower() in _MAJOR_ROAD_CLASSIFICATIONS else "urban"
    medians_in, beta = _ROAD_PGD_FRAGILITY[tier]

    if pgd_in is None or math.isnan(pgd_in) or pgd_in <= 0:
        return 0.0, "no"

    exceedance = tuple(_lognormal_exceedance_prob(pgd_in, m, beta) for m in medians_in)
    p_slight, p_moderate, p_ext_complete = exceedance
    # Table 7-5 only publishes 3 thresholds (Slight/Moderate/Extensive-
    # Complete combined) -- treat the combined tier as this project's
    # "extensive" for damage-level reporting (matches Table 11-10's own
    # roadway cost ratio, which likewise doesn't distinguish extensive from
    # complete for roads).
    probs = {
        "none": 1.0 - p_slight,
        "slight": p_slight - p_moderate,
        "moderate": p_moderate - p_ext_complete,
        "extensive": p_ext_complete,
        "complete": 0.0,
    }
    ratio = expected_damage_ratio(probs, asset_type="road")
    best_state = max(("none", "slight", "moderate", "extensive"), key=lambda s: probs[s])

    unit_cost_per_km = ROAD_REPLACEMENT_COST_USD_PER_KM[tier]
    cost_usd = ratio * unit_cost_per_km * length_km
    return cost_usd, HAZUS_TO_RESIFLOW_DAMAGE_LEVEL[best_state]


_SQM_PER_SQFT = 0.09290304
_MM_PER_INCH = 25.4


def compute_row_direct_damage_musd(row: pd.Series, *, hazard_type: str) -> float:
    """Per-row (Script 3's intersections_gp) HAZUS direct damage, million USD.

    Replaces the flood-shim path (calculate_damage() + damage_ratio_road_
    flood.xlsx/damage_cost_road_flood.xlsx) for earthquake and landslide.

    landslide: ground-failure (PGD) only, matching what compute_landslide_pgd.py
    actually produces for this project -- HAZUS's ground-shaking axis isn't
    applicable to landslide's own PGD-only intensity in this pipeline.

    earthquake: ground-shaking (Sa(1.0s)) only, bridges only. Sa(1.0s) is
    intersected as a second raster pass alongside PGA -- see
    hazards/sioux_falls_multihazard.py's sa1p0_companion flag,
    disruption/earthquake.py's intersections_with_earthquake source_field
    branch, and disruption/pipeline_intensity.py's source_field plumbing.
    "psa1p0_g" is 0.0 (not NaN) when no Sa(1.0s) raster exists for a given
    hazard_source, so this correctly falls through to $0 for those cases
    (e.g. RealEarthquakeSource, the NSHM source, has no Sa companion).
    Roads always get $0 for earthquake: HAZUS's road fragility (Table 7-5)
    is PGD-only (permanent ground deformation) with no ground-shaking curve
    -- this project has no liquefaction/ground-failure PGD computed for the
    earthquake hazard itself (only landslide's Newmark PGD exists), so this
    is a real HAZUS methodology fact, not a gap.
    """
    if hazard_type not in ("earthquake", "landslide"):
        return 0.0

    is_bridge = _safe_str(row.get("road_label")).strip().lower() == "bridge"
    length_m = _safe_float(row.get("length")) or 0.0

    if hazard_type == "earthquake":
        if not is_bridge:
            return 0.0
        sa_1p0_g = _safe_float(row.get("psa1p0_g"))
        if sa_1p0_g is None or sa_1p0_g <= 0:
            return 0.0
        hwb_class = classify_hwb(
            structure_kind_code=row.get("structure_kind_code"),
            structure_type_code=row.get("structure_type_code"),
            state=row.get("bridge_state"),
            year_built=row.get("year_built"),
            num_spans=row.get("main_unit_spans"),
            max_span_length_m=row.get("max_span_length_m"),
        )
        width_m = _safe_float(row.get("averageWidth")) or 3.65
        deck_area_sqft = (length_m * width_m) / _SQM_PER_SQFT
        cost_usd, _level = bridge_direct_cost_usd(
            hwb_class=hwb_class,
            sa_1p0_g=sa_1p0_g,
            pgd_in=None,
            num_spans=row.get("main_unit_spans"),
            span_width_m=width_m,
            bridge_length_m=length_m,
            skew_degrees=row.get("skew_degrees"),
            deck_area_sqft=deck_area_sqft,
        )
        return cost_usd / 1_000_000.0

    # hazard_type == "landslide"
    # "landslide_mm" is Script 2's raw per-segment column name
    # (disruption/landslide.py's intersections_with_landslide) --
    # format_intersections()'s groupby(...).max() keeps this name as-is
    # (it doesn't rename to landslide_max_mm; that name only appears in
    # disruption/build.py's separate link-level aggregation path).
    pgd_mm = _safe_float(row.get("landslide_mm"))
    if pgd_mm is None or pgd_mm <= 0:
        return 0.0
    pgd_in = pgd_mm / _MM_PER_INCH

    if is_bridge:
        hwb_class = classify_hwb(
            structure_kind_code=row.get("structure_kind_code"),
            structure_type_code=row.get("structure_type_code"),
            state=row.get("bridge_state"),
            year_built=row.get("year_built"),
            num_spans=row.get("main_unit_spans"),
            max_span_length_m=row.get("max_span_length_m"),
        )
        width_m = _safe_float(row.get("averageWidth")) or 3.65
        deck_area_sqft = (length_m * width_m) / _SQM_PER_SQFT
        cost_usd, _level = bridge_direct_cost_usd(
            hwb_class=hwb_class,
            sa_1p0_g=None,
            pgd_in=pgd_in,
            num_spans=row.get("main_unit_spans"),
            span_width_m=width_m,
            bridge_length_m=length_m,
            skew_degrees=row.get("skew_degrees"),
            deck_area_sqft=deck_area_sqft,
        )
    else:
        cost_usd, _level = road_direct_cost_usd(
            road_classification=row.get("road_classification"),
            pgd_in=pgd_in,
            length_km=length_m / 1000.0,
            lanes=row.get("lanes"),
        )

    return cost_usd / 1_000_000.0
