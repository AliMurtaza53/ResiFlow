"""Build county-to-county passenger OD from LODES block-level OD files.

Follows Census LEHD guidance:
  - OD files: w_geocode (workplace block), h_geocode (home block), S000 (jobs)
  - Geographic crosswalk: tabblk2020 -> cty (5-digit county FIPS)
  - For each state, combine od_main + od_aux, then aggregate nationally

Inner-county flows are retained in the county matrix for now; a later pass can
split or downscale within-county trips if needed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from resiflow.lodes_paths import (
    CONUS_STATE_ABBRS,
    DEFAULT_LODES8_BASE_URL,
    STATE_LODES_YEAR_OVERRIDES,
    crosswalk_file_path,
    effective_lodes_year,
    lodes_base_url,
    od_file_path,
    resolve_lodes_data_root,
    resolve_lodes_read_path,
)

LOGGER = logging.getLogger(__name__)

COUNTY_OD_COLUMNS = ["origin_county", "destination_county", "jobs", "year", "job_type"]
OD_READ_COLUMNS = ["w_geocode", "h_geocode", "S000"]
CROSSWALK_COLUMNS = ["tabblk2020", "cty"]


def normalize_county_fips(value) -> str:
    """Normalize LODES county codes to 5-digit FIPS strings."""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(5)[-5:]


def read_lodes_od(
    state: str,
    *,
    job_type: str = "JT00",
    year: int = 2022,
    part: str = "main",
    base: str | Path | None = None,
) -> pd.DataFrame:
    """Read one LODES OD file (main or aux) for a state."""
    read_year = effective_lodes_year(state, year)
    if read_year != year:
        LOGGER.info("Using LODES year=%s for state=%s (requested year=%s)", read_year, state, year)
    local_path = od_file_path(state, job_type=job_type, year=read_year, part=part, base=base)
    remote_url = od_file_path(
        state,
        job_type=job_type,
        year=read_year,
        part=part,
        base=DEFAULT_LODES8_BASE_URL,
    )
    path = resolve_lodes_read_path(local_path, remote_url)
    LOGGER.info("Reading LODES OD: %s", path)
    return pd.read_csv(path, dtype={"h_geocode": str, "w_geocode": str}, usecols=OD_READ_COLUMNS)


def read_lodes_crosswalk(state: str, *, base: str | Path | None = None) -> pd.DataFrame:
    """Read block-to-county crosswalk for one state."""
    local_path = crosswalk_file_path(state, base=base)
    remote_url = crosswalk_file_path(state, base=DEFAULT_LODES8_BASE_URL)
    path = resolve_lodes_read_path(local_path, remote_url)
    LOGGER.info("Reading LODES crosswalk: %s", path)
    xwalk = pd.read_csv(path, dtype=str, usecols=CROSSWALK_COLUMNS)
    xwalk["tabblk2020"] = xwalk["tabblk2020"].astype(str)
    xwalk["cty"] = xwalk["cty"].map(normalize_county_fips)
    return xwalk.drop_duplicates("tabblk2020")


def build_block_county_lookup(states: list[str], *, base: str | Path | None = None) -> pd.DataFrame:
    """Concatenate block->county mappings for the requested states."""
    frames = [read_lodes_crosswalk(state, base=base) for state in states]
    lookup = pd.concat(frames, ignore_index=True).drop_duplicates("tabblk2020")
    if lookup.empty:
        raise ValueError("Block-county lookup is empty.")
    return lookup


def aggregate_od_to_county(
    od: pd.DataFrame,
    block_county_lookup: pd.DataFrame,
    *,
    year: int,
    job_type: str,
) -> pd.DataFrame:
    """Map block OD rows to county pairs and sum S000 job counts."""
    if od.empty:
        return pd.DataFrame(columns=COUNTY_OD_COLUMNS)

    home = block_county_lookup.rename(
        columns={"tabblk2020": "h_geocode", "cty": "origin_county"}
    )
    work = block_county_lookup.rename(
        columns={"tabblk2020": "w_geocode", "cty": "destination_county"}
    )

    mapped = od.merge(home, on="h_geocode", how="inner", validate="m:1")
    mapped = mapped.merge(work, on="w_geocode", how="inner", validate="m:1")
    mapped["jobs"] = pd.to_numeric(mapped["S000"], errors="coerce").fillna(0.0)
    mapped = mapped[(mapped["origin_county"] != "") & (mapped["destination_county"] != "")]

    county_od = (
        mapped.groupby(["origin_county", "destination_county"], as_index=False)["jobs"]
        .sum()
        .astype({"jobs": float})
    )
    county_od["year"] = int(year)
    county_od["job_type"] = job_type
    return county_od[county_od["jobs"] > 0].reset_index(drop=True)


def build_state_county_od(
    state: str,
    *,
    job_type: str = "JT00",
    year: int = 2022,
    base: str | Path | None = None,
    block_county_lookup: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build county OD for one state from its main + aux OD files."""
    lookup = block_county_lookup
    if lookup is None:
        lookup = read_lodes_crosswalk(state, base=base)

    parts: list[pd.DataFrame] = []
    for part in ("main", "aux"):
        try:
            od = read_lodes_od(state, job_type=job_type, year=year, part=part, base=base)
        except FileNotFoundError:
            LOGGER.warning("Missing LODES OD part=%s for state=%s; skipping.", part, state)
            continue
        parts.append(aggregate_od_to_county(od, lookup, year=year, job_type=job_type))

    if not parts:
        return pd.DataFrame(columns=COUNTY_OD_COLUMNS)

    combined = pd.concat(parts, ignore_index=True)
    return (
        combined.groupby(["origin_county", "destination_county", "year", "job_type"], as_index=False)["jobs"]
        .sum()
        .query("jobs > 0")
        .reset_index(drop=True)
    )


def build_conus_county_od(
    states: list[str] | None = None,
    *,
    job_type: str = "JT00",
    year: int = 2022,
    base: str | Path | None = None,
    parts_dir: str | Path | None = None,
    resume: bool = True,
) -> pd.DataFrame:
    """Aggregate LODES OD to county-to-county flows for many states."""
    selected = [s.lower() for s in (states or list(CONUS_STATE_ABBRS))]
    lookup = build_block_county_lookup(selected, base=base)

    parts_path = Path(parts_dir) if parts_dir is not None else None
    if parts_path is not None:
        parts_path.mkdir(parents=True, exist_ok=True)

    pieces: list[pd.DataFrame] = []
    for state in selected:
        part_file = parts_path / f"{state}_{job_type.lower()}_{year}.parquet" if parts_path else None
        if resume and part_file is not None and part_file.exists():
            LOGGER.info("Reusing LODES county OD part for state=%s -> %s", state, part_file)
            pieces.append(pd.read_parquet(part_file))
            continue

        LOGGER.info("Building LODES county OD for state=%s", state)
        state_od = build_state_county_od(
            state,
            job_type=job_type,
            year=year,
            base=base,
            block_county_lookup=lookup,
        )
        if part_file is not None:
            state_od.to_parquet(part_file, index=False)
            LOGGER.info("Wrote state part %s (%s rows)", part_file, len(state_od))
        pieces.append(state_od)

    if not pieces:
        return pd.DataFrame(columns=COUNTY_OD_COLUMNS)

    combined = pd.concat(pieces, ignore_index=True)
    county_od = (
        combined.groupby(["origin_county", "destination_county", "year", "job_type"], as_index=False)["jobs"]
        .sum()
        .query("jobs > 0")
        .reset_index(drop=True)
    )
    return county_od


def county_od_to_assignment_schema(county_od: pd.DataFrame) -> pd.DataFrame:
    """Convert county OD to the mapper schema used by county-shapefile assignment.

    Jobs (S000) are treated as daily person-trips for the passenger car mode.
    A placeholder tons column is included so existing BTS normalization can run.
    """
    required = {"origin_county", "destination_county", "jobs"}
    missing = required - set(county_od.columns)
    if missing:
        raise ValueError(f"county_od missing columns: {sorted(missing)}")

    year = int(county_od["year"].iloc[0]) if "year" in county_od.columns and len(county_od) else 0
    return pd.DataFrame(
        {
            "origin_detail_zone": county_od["origin_county"].map(normalize_county_fips),
            "destination_detail_zone": county_od["destination_county"].map(normalize_county_fips),
            "annual_tons": pd.to_numeric(county_od["jobs"], errors="coerce").fillna(0.0),
            "daily_truck_trips": pd.to_numeric(county_od["jobs"], errors="coerce").fillna(0.0),
            "annual_truck_trips": pd.to_numeric(county_od["jobs"], errors="coerce").fillna(0.0) * 365.0,
            "value": 0.0,
            "mode": "car",
            "sctgG5": "passenger",
            "year": year,
        }
    )


def run_lodes_county_od(
    output_path: str | Path,
    *,
    states: list[str] | None = None,
    job_type: str = "JT00",
    year: int = 2022,
    base_path: Path | None = None,
    repo_root: Path | None = None,
    summary_json_path: str | Path | None = None,
    parts_dir: str | Path | None = None,
    resume: bool = True,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build and write county-to-county LODES passenger OD."""
    local_root = resolve_lodes_data_root(base_path, repo_root)
    base = lodes_base_url(local_root)
    out = Path(output_path)
    parts_path = Path(parts_dir) if parts_dir is not None else out.parent / "state_parts"

    county_od = build_conus_county_od(
        states=states,
        job_type=job_type,
        year=year,
        base=base,
        parts_dir=parts_path,
        resume=resume,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    county_od.to_parquet(out, index=False)

    summary: dict[str, object] = {
        "output_path": str(out),
        "states": states or list(CONUS_STATE_ABBRS),
        "job_type": job_type,
        "year": year,
        "lodes_base": base,
        "local_root": str(local_root) if local_root else None,
        "state_year_overrides": STATE_LODES_YEAR_OVERRIDES,
        "county_pairs": int(len(county_od)),
        "total_jobs": float(county_od["jobs"].sum()) if not county_od.empty else 0.0,
        "unique_origin_counties": int(county_od["origin_county"].nunique()) if not county_od.empty else 0,
        "unique_destination_counties": int(county_od["destination_county"].nunique()) if not county_od.empty else 0,
        "state_parts_dir": str(parts_path),
    }
    if summary_json_path:
        summary_path = Path(summary_json_path)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return county_od, summary
