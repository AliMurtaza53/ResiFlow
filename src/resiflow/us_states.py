"""US state/territory identity crosswalk: FIPS code, USPS abbreviation, name.

Standard, stable public reference data (U.S. Census Bureau FIPS 5-2 state
codes and USPS Publication 28 abbreviations) -- not a modeling assumption,
so it's a plain module constant rather than a sourced parameter table.
Covers the 50 states + DC + Puerto Rico, matching
T30_bridge_replacement_unit_costs_US.csv's own state coverage.
"""

from __future__ import annotations

import pandas as pd

# (FIPS 2-digit code, USPS abbreviation, full name as T30's own "state" column spells it)
_STATES = [
    ("01", "AL", "Alabama"), ("02", "AK", "Alaska"), ("04", "AZ", "Arizona"),
    ("05", "AR", "Arkansas"), ("06", "CA", "California"), ("08", "CO", "Colorado"),
    ("09", "CT", "Connecticut"), ("10", "DE", "Delaware"),
    ("11", "DC", "District Of Columbia"), ("12", "FL", "Florida"),
    ("13", "GA", "Georgia"), ("15", "HI", "Hawaii"), ("16", "ID", "Idaho"),
    ("17", "IL", "Illinois"), ("18", "IN", "Indiana"), ("19", "IA", "Iowa"),
    ("20", "KS", "Kansas"), ("21", "KY", "Kentucky"), ("22", "LA", "Louisiana"),
    ("23", "ME", "Maine"), ("24", "MD", "Maryland"), ("25", "MA", "Massachusetts"),
    ("26", "MI", "Michigan"), ("27", "MN", "Minnesota"), ("28", "MS", "Mississippi"),
    ("29", "MO", "Missouri"), ("30", "MT", "Montana"), ("31", "NE", "Nebraska"),
    ("32", "NV", "Nevada"), ("33", "NH", "New Hampshire"), ("34", "NJ", "New Jersey"),
    ("35", "NM", "New Mexico"), ("36", "NY", "New York"),
    ("37", "NC", "North Carolina"), ("38", "ND", "North Dakota"), ("39", "OH", "Ohio"),
    ("40", "OK", "Oklahoma"), ("41", "OR", "Oregon"), ("42", "PA", "Pennsylvania"),
    ("44", "RI", "Rhode Island"), ("45", "SC", "South Carolina"),
    ("46", "SD", "South Dakota"), ("47", "TN", "Tennessee"), ("48", "TX", "Texas"),
    ("49", "UT", "Utah"), ("50", "VT", "Vermont"), ("51", "VA", "Virginia"),
    ("53", "WA", "Washington"), ("54", "WV", "West Virginia"),
    ("55", "WI", "Wisconsin"), ("56", "WY", "Wyoming"),
    ("72", "PR", "Puerto Rico"),
]

FIPS_TO_NAME: dict[str, str] = {fips: name for fips, _usps, name in _STATES}
USPS_TO_NAME: dict[str, str] = {usps: name for _fips, usps, name in _STATES}


def state_name_from_fips_or_usps(fips: pd.Series, usps: pd.Series) -> pd.Series:
    """Resolve a full state name, preferring a FIPS code (e.g. NBI's own
    per-bridge survey state) and falling back to a USPS abbreviation (e.g.
    FAF5's own STATE field) when FIPS is absent. Unresolvable values (e.g.
    Canadian provinces in FAF5's STATE on a cross-border link) come back as
    missing, never a guessed name."""
    fips_clean = fips.astype(str).str.strip().str.zfill(2)
    name_from_fips = fips_clean.map(FIPS_TO_NAME)
    usps_clean = usps.astype(str).str.strip().str.upper()
    name_from_usps = usps_clean.map(USPS_TO_NAME)
    return name_from_fips.where(name_from_fips.notna(), name_from_usps)
