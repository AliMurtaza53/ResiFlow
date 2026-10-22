"""Read LODES Workplace Area Characteristics (WAC) employment by census block.

Used to locate freight-relevant employment clusters (manufacturing, wholesale,
transportation/warehousing, mining) within a county for the multi-subarea
county-connector disaggregation (see docs/FAF5_Caliper_Methodology_and_Proposed_Assignment.md
Section 4A). WAC gives job counts by workplace block (``w_geocode``); the
LODES geography crosswalk supplies each block's county FIPS and internal-point
lon/lat, both needed to cluster and place subareas.

LODES NAICS sector columns relevant to freight (CNS02 mining, CNS05
manufacturing, CNS06 wholesale trade, CNS08 transportation/warehousing) are
summed into a single ``freight_jobs`` weight; retail (CNS07) is included at a
discount since most retail trip generation is non-freight. Falls back to
total jobs (``C000``) when sector columns are absent (older LODES vintages).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from resiflow.lodes_county_od import normalize_county_fips
from resiflow.lodes_paths import (
    DEFAULT_LODES8_BASE_URL,
    crosswalk_file_path,
    effective_lodes_year,
    resolve_lodes_read_path,
    wac_file_path,
)

LOGGER = logging.getLogger(__name__)

# NAICS sector job columns in LODES WAC. CNS07 (retail) counted at a discount:
# most retail footfall isn't freight-generating, but distribution-heavy retail
# (big-box, grocery DCs) still matters at reduced weight.
_FREIGHT_SECTOR_WEIGHTS: dict[str, float] = {
    "CNS02": 1.0,  # Mining, quarrying, oil & gas extraction
    "CNS05": 1.0,  # Manufacturing
    "CNS06": 1.0,  # Wholesale trade
    "CNS07": 0.3,  # Retail trade
    "CNS08": 1.0,  # Transportation & warehousing
}

CROSSWALK_GEO_COLUMNS = ["tabblk2020", "cty", "blklatdd", "blklondd"]


def read_lodes_wac(
    state: str,
    *,
    job_type: str = "JT00",
    year: int = 2022,
    base: str | Path | None = None,
) -> pd.DataFrame:
    """Read one LODES WAC file for a state (block-level workplace job counts)."""
    read_year = effective_lodes_year(state, year)
    if read_year != year:
        LOGGER.info("Using LODES year=%s for state=%s (requested year=%s)", read_year, state, year)
    local_path = wac_file_path(state, job_type=job_type, year=read_year, base=base)
    remote_url = wac_file_path(state, job_type=job_type, year=read_year, base=DEFAULT_LODES8_BASE_URL)
    path = resolve_lodes_read_path(local_path, remote_url)
    LOGGER.info("Reading LODES WAC: %s", path)
    wac = pd.read_csv(path, dtype={"w_geocode": str}, low_memory=False)
    present_sectors = [c for c in _FREIGHT_SECTOR_WEIGHTS if c in wac.columns]
    if present_sectors:
        wac = wac.assign(
            freight_jobs=sum(
                pd.to_numeric(wac[c], errors="coerce").fillna(0.0) * _FREIGHT_SECTOR_WEIGHTS[c]
                for c in present_sectors
            )
        )
    else:
        LOGGER.warning("No NAICS sector columns in WAC for state=%s; falling back to C000 total jobs.", state)
        wac = wac.assign(freight_jobs=pd.to_numeric(wac.get("C000", 0.0), errors="coerce").fillna(0.0))
    return wac[["w_geocode", "freight_jobs"]]


def read_lodes_block_geo(state: str, *, base: str | Path | None = None) -> pd.DataFrame:
    """Read block -> county FIPS + internal-point lon/lat from the LODES crosswalk."""
    local_path = crosswalk_file_path(state, base=base)
    remote_url = crosswalk_file_path(state, base=DEFAULT_LODES8_BASE_URL)
    path = resolve_lodes_read_path(local_path, remote_url)
    LOGGER.info("Reading LODES block geography: %s", path)
    xwalk = pd.read_csv(path, dtype=str, low_memory=False)
    missing_geo = [c for c in ("blklatdd", "blklondd") if c not in xwalk.columns]
    if missing_geo:
        raise ValueError(
            f"LODES crosswalk for state={state} is missing block-centroid columns {missing_geo}; "
            "cannot place employment subareas without block lon/lat."
        )
    out = xwalk[["tabblk2020", "cty", "blklatdd", "blklondd"]].copy()
    out["cty"] = out["cty"].map(normalize_county_fips)
    out["blklatdd"] = pd.to_numeric(out["blklatdd"], errors="coerce")
    out["blklondd"] = pd.to_numeric(out["blklondd"], errors="coerce")
    return out.drop_duplicates("tabblk2020")


def build_county_block_employment(
    states: list[str],
    target_county_fips: set[str],
    *,
    job_type: str = "JT00",
    year: int = 2022,
    base: str | Path | None = None,
) -> pd.DataFrame:
    """Build block-level freight employment, restricted to target counties.

    Returns columns: county_fips, tabblk2020, lon, lat, freight_jobs.
    """
    frames: list[pd.DataFrame] = []
    for state in states:
        try:
            wac = read_lodes_wac(state, job_type=job_type, year=year, base=base)
        except FileNotFoundError:
            LOGGER.warning("Missing LODES WAC for state=%s; skipping.", state)
            continue
        geo = read_lodes_block_geo(state, base=base)
        geo = geo[geo["cty"].isin(target_county_fips)]
        if geo.empty:
            continue
        merged = wac.merge(
            geo.rename(columns={"tabblk2020": "w_geocode"}),
            on="w_geocode",
            how="inner",
        )
        merged = merged[merged["freight_jobs"] > 0]
        frames.append(
            merged.rename(
                columns={"cty": "county_fips", "w_geocode": "tabblk2020", "blklondd": "lon", "blklatdd": "lat"}
            )[["county_fips", "tabblk2020", "lon", "lat", "freight_jobs"]]
        )
    if not frames:
        return pd.DataFrame(columns=["county_fips", "tabblk2020", "lon", "lat", "freight_jobs"])
    return pd.concat(frames, ignore_index=True)


__all__ = [
    "read_lodes_wac",
    "read_lodes_block_geo",
    "build_county_block_employment",
]
