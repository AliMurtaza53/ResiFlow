#!/usr/bin/env python3
"""Download the FHWA National Bridge Inventory (NBI) and build one national
structures table with parsed coordinates.

Fixes the faf5_network.py bug where every link's ``road_bridge`` defaults to
``'no'`` unconditionally (no real attribute exists in FAF5's own schema to
check) -- confirmed via parameter_diff_final.xlsx's audit (item 36) and by
reading DAFNI-NIRD's original road_revised.py (the downstream bridge-costing
code has always expected a real ``road_bridge``/``road_label`` attribute;
DAFNI-NIRD's GB source got it for free from OS MasterMap, FAF5 has no
equivalent field, so the NBI join this script feeds was never implemented).

NBI is distributed per-state as fixed-schema delimited text files. FHWA's own
download page (bridge/nbi/ascii2024.cfm) gates each file behind a
JavaScript disclaimer click-through with no scriptable form action, but the
underlying files are directly fetchable once you know the URL pattern
(confirmed 2026-08-17 against the live site):

    https://www.fhwa.dot.gov/bridge/nbi/2024/delimited/{STATE}24.txt

State/territory codes (52 total: 50 states + DC + GU + PR + VI) were read
directly off that same page's disclaimer links, not guessed.

Coordinate encoding (NBI Recording and Coding Guide, verified against a real
downloaded record -- Wilmington, DE STRUCTURE_NUMBER 1001 279 decodes to
39.7693N/-75.5767W, a real Wilmington-area location):
    LAT_016:  8 digits DDMMSSss  (degrees, minutes, seconds.hundredths)
    LONG_017: 9 digits DDDMMSSss (same, one extra degree digit; always west
              for the US, so negated)

Usage::

    python scripts/download_nbi_bridges.py --output /path/to/nbi_bridges_2024.parquet
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

NBI_URL_TEMPLATE = "https://www.fhwa.dot.gov/bridge/nbi/2024/delimited/{state}24.txt"

# All 52 codes FHWA's own ascii2024.cfm disclaimer page lists -- read off the
# live page (2026-08-17), not assumed from a generic US-state list, so
# territories (GU/PR/VI) aren't silently dropped.
NBI_STATE_CODES = [
    "AK", "AL", "AR", "AZ", "CA", "CO", "CT", "DC", "DE", "FL", "GA", "GU",
    "HI", "IA", "ID", "IL", "IN", "KS", "KY", "LA", "MA", "MD", "ME", "MI",
    "MN", "MO", "MS", "MT", "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY",
    "OH", "OK", "OR", "PA", "PR", "RI", "SC", "SD", "TN", "TX", "UT", "VA",
    "VI", "VT", "WA", "WI", "WV", "WY",
]

# Columns kept from NBI's ~120-column schema -- everything the FAF5 spatial
# join and the bridge damage-cost formula (width x length x unit_cost) need,
# plus identifying/QA fields. See the NBI Recording and Coding Guide for the
# full schema; column names here match the delimited file's own header row.
KEEP_COLUMNS = [
    "STATE_CODE_001",
    "STRUCTURE_NUMBER_008",
    "FACILITY_CARRIED_007",
    "LOCATION_009",
    "LAT_016",
    "LONG_017",
    "ROUTE_PREFIX_005B",
    "SERVICE_LEVEL_005C",
    "ROUTE_NUMBER_005D",
    "DECK_WIDTH_MT_052",
    "STRUCTURE_LEN_MT_049",
    "MAIN_UNIT_SPANS_045",
    "MAX_SPAN_LEN_MT_048",
    "DEGREES_SKEW_034",
    "STRUCTURE_KIND_043A",
    "STRUCTURE_TYPE_043B",
    "YEAR_BUILT_027",
    "FUNCTIONAL_CLASS_026",
    "OWNER_022",
    "MAINTENANCE_021",
    "HIGHWAY_SYSTEM_104",
    "TOLL_020",
]

# All three label mappings below are sourced from the official "Recording
# and Coding Guide for the Structure Inventory and Appraisal of the Nation's
# Bridges" (FHWA), reached via the data dictionary DOI the user supplied
# (https://doi.org/10.21949/1519105 -> https://www.fhwa.dot.gov/bridge/
# mtguide.pdf) -- confirmed 2026-08-18, page numbers below are from that PDF.
# An EARLIER version of this file guessed these three mappings from memory
# instead of consulting the guide; SERVICE_LEVEL_005C's guess was
# demonstrably wrong (see the git history of this comment block) -- these
# are the corrected, citable values, not guesses.

# ROUTE_PREFIX_005B (Item 5B, guide p.14). Confirmed my earlier memory-based
# guess was already correct for codes 1-8; there is no code 9 in the actual
# guide (an earlier version of this dict invented one).
ROUTE_PREFIX_LABELS = {
    "1": "Interstate highway",
    "2": "U.S. numbered highway",
    "3": "State highway",
    "4": "County highway",
    "5": "City street",
    "6": "Federal lands road",
    "7": "State lands road",
    "8": "Other (incl. toll roads not otherwise identified)",
}

# SERVICE_LEVEL_005C (Item 5C, guide p.14) -- what kind of facility the
# bridge's own route is (independent of what road class it belongs to).
# Code 7 is the real ramp/connector code -- confirmed by both the guide
# text and, independently, by real data (structures with "RAMP" in their
# facility-carried name overwhelmingly carry code 7, not the code an
# earlier guess here had assumed). No code 5 exists in the real scheme.
SERVICE_LEVEL_LABELS = {
    "0": "None of the below",
    "1": "Mainline",
    "2": "Alternate",
    "3": "Bypass",
    "4": "Spur",
    "6": "Business",
    "7": "Ramp, Wye, Connector, etc.",
    "8": "Service and/or unclassified frontage road",
}

# FUNCTIONAL_CLASS_026 (Item 26, guide p.24) -- tens digit 0=rural/1=urban.
# One real correction from an earlier version of this dict: rural code "02"
# is "Principal Arterial - Other" generally, NOT specifically "freeway/
# expressway" -- that freeway/expressway distinction only exists in the
# urban scheme (code 12). Ramps are not their own functional class here
# (that's SERVICE_LEVEL_005C's job); this field describes the road system
# the bridge belongs to.
FUNCTIONAL_CLASS_LABELS = {
    "01": "Rural - Principal Arterial - Interstate",
    "02": "Rural - Principal Arterial - Other",
    "06": "Rural - Minor Arterial",
    "07": "Rural - Major Collector",
    "08": "Rural - Minor Collector",
    "09": "Rural - Local",
    "11": "Urban - Principal Arterial - Interstate",
    "12": "Urban - Principal Arterial - Other Freeway/Expressway",
    "14": "Urban - Other Principal Arterial",
    "16": "Urban - Minor Arterial",
    "17": "Urban - Collector",
    "19": "Urban - Local",
}


def _nbi_dms_to_decimal(raw: str, *, digits_before_seconds: int) -> float | None:
    """Decode an NBI DDMMSSss / DDDMMSSss packed coordinate to decimal degrees.

    ``digits_before_seconds`` is 4 for latitude (DDMM) and 5 for longitude
    (DDDMM); the remaining 4 digits are SSss (seconds, hundredths implied).
    Returns None for blank/zero (unrecorded) coordinates OR for a
    structurally invalid field (minutes/seconds out of range) -- real NBI
    submissions do contain some malformed records (confirmed: DE structure
    1266B347's LAT_016='03943500' decodes to minutes=94, which cannot be a
    real minutes value). Silently accepting these would produce a coordinate
    that's technically parseable but geographically nonsense.
    """
    text = (raw or "").strip()
    if not text or set(text) == {"0"}:
        return None
    text = text.zfill(digits_before_seconds + 4)
    deg = int(text[: digits_before_seconds - 2])
    minutes = int(text[digits_before_seconds - 2 : digits_before_seconds])
    seconds = int(text[digits_before_seconds : digits_before_seconds + 4]) / 100.0
    if not (0 <= minutes < 60 and 0 <= seconds < 60):
        return None
    return deg + minutes / 60.0 + seconds / 3600.0


def _clean_deck_width(raw: pd.Series) -> pd.Series:
    """Parse DECK_WIDTH_MT_052, treating 0 as NBI's "not recorded" convention.

    0 is not a real zero-width bridge (confirmed against real national data,
    2026-08-18: 88,668 of 621,533 structures, 14.3%, carry exactly 0 -- far
    too common to be genuine). Mapping it to NaN lets
    apply_bridge_index()'s fillna-based fallback to the lanes-based width
    estimate actually fire for these, instead of silently zeroing out that
    link's bridge damage cost entirely (width x length x unit_cost = 0),
    which would be worse than the original missing-road_bridge bug this
    whole fix targets.
    """
    return pd.to_numeric(raw, errors="coerce").replace(0.0, pd.NA)


# Loose bounding box covering CONUS + AK + HI + territories (GU/PR/VI), used
# as a second validation pass after DMS decoding -- catches malformed records
# that happen to decode to structurally valid but geographically impossible
# minutes/seconds (e.g. a swapped digit that still lands under 60).
US_LAT_RANGE = (13.0, 72.0)  # Guam south to northern Alaska
US_LON_RANGE = (-180.0, -64.0)  # western hemisphere only -- Guam handled separately below

# LONG_017 stores an unsigned degrees value with no sign bit; every NBI
# state/territory except Guam is in the western hemisphere, so the sign is
# inferred from state, not read from the field. Verified against real data
# (2026-08-17): Guam structure 66180000000G042's LONG_017='144453839' decodes
# unsigned to +144.7607, matching Guam's real location (~144.8E) -- negating
# it would silently place Guam's bridges in the Pacific at -144.76 (nowhere
# near any US territory). Every other state's raw value must be negated.
EASTERN_HEMISPHERE_STATES = {"GU"}


def _fetch_state(state: str, *, retries: int = 3, timeout: float = 30.0) -> pd.DataFrame:
    url = NBI_URL_TEMPLATE.format(state=state)
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                raw = resp.read().decode("latin-1")
            break
        except Exception as exc:  # noqa: BLE001 -- retry any transient failure
            last_exc = exc
            if attempt < retries:
                time.sleep(2.0 * attempt)
    else:
        raise RuntimeError(f"Failed to fetch NBI data for {state} from {url}") from last_exc

    reader = csv.DictReader(io.StringIO(raw))
    rows = []
    for row in reader:
        rows.append({col: row.get(col, "") for col in KEEP_COLUMNS})
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    is_eastern = state in EASTERN_HEMISPHERE_STATES
    lon_sign = 1.0 if is_eastern else -1.0
    lat_range = US_LAT_RANGE
    lon_range = (140.0, 150.0) if is_eastern else US_LON_RANGE

    df["latitude"] = df["LAT_016"].apply(
        lambda v: _nbi_dms_to_decimal(v, digits_before_seconds=4)
    )
    df["longitude"] = df["LONG_017"].apply(
        lambda v: lon_sign * _nbi_dms_to_decimal(v, digits_before_seconds=5)
        if _nbi_dms_to_decimal(v, digits_before_seconds=5) is not None
        else None
    )
    out_of_range = (
        ~df["latitude"].between(*lat_range) | ~df["longitude"].between(*lon_range)
    )
    n_flagged = int((out_of_range & df["latitude"].notna()).sum())
    if n_flagged:
        print(f"  WARNING: {n_flagged} {state} structures decoded to coordinates outside "
              f"the expected range {lat_range}/{lon_range} -- dropping (likely malformed source records).")
    df.loc[out_of_range, ["latitude", "longitude"]] = None
    df["structure_number"] = df["STRUCTURE_NUMBER_008"].str.strip()
    df["facility_carried"] = df["FACILITY_CARRIED_007"].str.strip().str.strip("'")
    df["location"] = df["LOCATION_009"].str.strip().str.strip("'")
    df["deck_width_m"] = _clean_deck_width(df["DECK_WIDTH_MT_052"])
    df["structure_length_m"] = pd.to_numeric(df["STRUCTURE_LEN_MT_049"], errors="coerce")
    df["year_built"] = pd.to_numeric(df["YEAR_BUILT_027"], errors="coerce")
    # Added 2026-08-20 for HAZUS Hazus 6.1 bridge classification (Table 7-1) --
    # main_unit_spans, max_span_length_m, skew_degrees, structure_kind,
    # structure_type. skew_degrees==99 is NBI's own "major variation across
    # substructure units" convention (guide p.30, confirmed earlier this
    # project), not a literal 99-degree skew -- treated as unusable/unknown
    # by src/resiflow/hazards/hazus_bridge.py, not coerced to a number here.
    df["main_unit_spans"] = pd.to_numeric(df["MAIN_UNIT_SPANS_045"], errors="coerce")
    df["max_span_length_m"] = pd.to_numeric(df["MAX_SPAN_LEN_MT_048"], errors="coerce")
    df["skew_degrees"] = pd.to_numeric(df["DEGREES_SKEW_034"], errors="coerce")
    df["structure_kind_code"] = df["STRUCTURE_KIND_043A"].str.strip()
    df["structure_type_code"] = df["STRUCTURE_TYPE_043B"].str.strip().str.zfill(2)
    df["state"] = state
    df["route_prefix"] = df["ROUTE_PREFIX_005B"].str.strip().map(ROUTE_PREFIX_LABELS)
    df["service_level_raw_code"] = df["SERVICE_LEVEL_005C"].str.strip()
    df["service_level"] = df["service_level_raw_code"].map(SERVICE_LEVEL_LABELS)
    df["functional_class"] = df["FUNCTIONAL_CLASS_026"].str.strip().str.zfill(2).map(FUNCTIONAL_CLASS_LABELS)
    # Authoritative ramp flag (guide-confirmed code), plus the original
    # text-match kept alongside as an independent cross-check -- the two
    # agreeing is itself useful evidence neither is spuriously wrong.
    df["is_ramp"] = df["service_level_raw_code"] == "7"
    df["is_ramp_by_name"] = df["FACILITY_CARRIED_007"].str.contains("RAMP", case=False, na=False)
    df["owner"] = df["OWNER_022"].str.strip()
    df["maintenance"] = df["MAINTENANCE_021"].str.strip()
    df["on_nhs"] = df["HIGHWAY_SYSTEM_104"].str.strip()
    return df[
        [
            "state",
            "structure_number",
            "facility_carried",
            "location",
            "latitude",
            "longitude",
            "deck_width_m",
            "structure_length_m",
            "main_unit_spans",
            "max_span_length_m",
            "skew_degrees",
            "structure_kind_code",
            "structure_type_code",
            "year_built",
            "route_prefix",
            "service_level_raw_code",
            "service_level",
            "functional_class",
            "owner",
            "maintenance",
            "on_nhs",
            "is_ramp",
            "is_ramp_by_name",
        ]
    ]


def download_all(states: list[str] | None = None) -> pd.DataFrame:
    states = states or NBI_STATE_CODES
    frames = []
    for i, state in enumerate(states, 1):
        print(f"[{i}/{len(states)}] Fetching {state}...", flush=True)
        df = _fetch_state(state)
        n_coords = int(df["latitude"].notna().sum()) if not df.empty else 0
        print(f"  {len(df)} structures, {n_coords} with valid coordinates")
        frames.append(df)
    combined = pd.concat(frames, ignore_index=True)
    before = len(combined)
    combined = combined.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)
    dropped = before - len(combined)
    if dropped:
        print(f"Dropped {dropped} structures with unrecorded coordinates (LAT_016/LONG_017 = 0).")
    return combined


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True, help="Output national bridges parquet path")
    parser.add_argument(
        "--states",
        nargs="+",
        default=None,
        help="Subset of state codes to fetch (default: all 52). Useful for a fast local test.",
    )
    args = parser.parse_args()

    combined = download_all(args.states)
    print(f"Total: {len(combined)} bridges across {combined['state'].nunique()} states/territories.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(args.output, index=False)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
