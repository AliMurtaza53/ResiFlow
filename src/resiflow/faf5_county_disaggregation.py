"""County-level FAF5 truck OD disaggregation using BTS experimental factors.

The functions here disaggregate FAF zone-to-zone commodity flows to
county-to-county flows with the public BTS experimental factors:

``county_tons = faf_tons * f_orig * f_dest``

This is intentionally a preprocessing module. It does not change the NIRD
assignment engine.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


LOGGER = logging.getLogger(__name__)

MODE_CODES = {
    "truck": "1",
    "rail": "2",
    "water": "3",
    "air": "4",
    "multiple": "5",
    "pipeline": "6",
    "other": "7",
}

SCTG_G5_GROUPS: tuple[tuple[str, range], ...] = (
    ("sctg0109", range(1, 10)),
    ("sctg1014", range(10, 15)),
    ("sctg1519", range(15, 20)),
    ("sctg2033", range(20, 34)),
    ("sctg3499", range(34, 100)),
)

COUNTY_OD_COLUMNS = [
    "origin_faf",
    "destination_faf",
    "origin_county",
    "destination_county",
    "sctgG5",
    "mode",
    "year",
    "tons",
    "value",
]


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result.columns = [str(col).strip() for col in result.columns]
    return result


def _column_lookup(df: pd.DataFrame) -> dict[str, str]:
    return {str(col).strip().lower(): str(col).strip() for col in df.columns}


def _rename_first(df: pd.DataFrame, aliases: Iterable[str], target: str) -> pd.DataFrame:
    lookup = _column_lookup(df)
    for alias in aliases:
        col = lookup.get(alias.lower())
        if col is not None:
            return df.rename(columns={col: target})
    return df


def _require_columns(df: pd.DataFrame, required: Iterable[str], table_name: str) -> None:
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"{table_name} is missing required columns: {missing}")


def _read_csv_string_keys(path: str | Path) -> pd.DataFrame:
    return _clean_columns(pd.read_csv(path, dtype=str, low_memory=False))


def _as_key(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip()


def _as_county_code(series: pd.Series) -> pd.Series:
    keys = _as_key(series)
    return keys.map(lambda value: value.zfill(5) if value.isdigit() and len(value) < 5 else value)


def _as_faf_zone_code(series: pd.Series) -> pd.Series:
    keys = _as_key(series)
    return keys.map(lambda value: str(int(value)) if value.isdigit() else value)


def _as_number(series: pd.Series, column_name: str) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if values.isna().any():
        bad = int(values.isna().sum())
        raise ValueError(f"Column {column_name!r} contains {bad:,} non-numeric values")
    return values.astype(float)


def _as_optional_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0).astype(float)


def load_truck_disaggregation_factors(
    origin_factor_path: str | Path,
    destination_factor_path: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load and normalize BTS truck origin/destination factor files."""

    origin = _read_csv_string_keys(origin_factor_path)
    destination = _read_csv_string_keys(destination_factor_path)

    origin = _rename_first(origin, ["dms_orig"], "dms_orig")
    origin = _rename_first(origin, ["dms_orig_c", "dms_orig_cnty", "origin_county"], "origin_county")
    origin = _rename_first(origin, ["sctgG5", "sctgg5", "commodity_group"], "sctgG5")
    origin = _rename_first(origin, ["f_orig", "origin_factor"], "f_orig")

    destination = _rename_first(destination, ["dms_dest"], "dms_dest")
    destination = _rename_first(
        destination,
        ["dms_dest_c", "dms_dest_cnty", "destination_county"],
        "destination_county",
    )
    destination = _rename_first(destination, ["sctgG5", "sctgg5", "commodity_group"], "sctgG5")
    destination = _rename_first(destination, ["f_dest", "destination_factor"], "f_dest")

    _require_columns(origin, ["dms_orig", "origin_county", "sctgG5", "f_orig"], "origin_factors")
    _require_columns(destination, ["dms_dest", "destination_county", "sctgG5", "f_dest"], "destination_factors")

    origin = origin[["dms_orig", "origin_county", "sctgG5", "f_orig"]].copy()
    destination = destination[["dms_dest", "destination_county", "sctgG5", "f_dest"]].copy()
    origin["dms_orig"] = _as_faf_zone_code(origin["dms_orig"])
    origin["sctgG5"] = _as_key(origin["sctgG5"])
    origin["origin_county"] = _as_county_code(origin["origin_county"])
    destination["dms_dest"] = _as_faf_zone_code(destination["dms_dest"])
    destination["sctgG5"] = _as_key(destination["sctgG5"])
    destination["destination_county"] = _as_county_code(destination["destination_county"])
    origin["f_orig"] = _as_number(origin["f_orig"], "f_orig")
    destination["f_dest"] = _as_number(destination["f_dest"], "f_dest")

    return origin, destination


def validate_disaggregation_factors(
    origin_factors: pd.DataFrame,
    destination_factors: pd.DataFrame,
    tolerance: float = 1e-6,
) -> dict[str, pd.DataFrame]:
    """Validate factor sums by FAF zone and commodity group."""

    _require_columns(origin_factors, ["dms_orig", "origin_county", "sctgG5", "f_orig"], "origin_factors")
    _require_columns(destination_factors, ["dms_dest", "destination_county", "sctgG5", "f_dest"], "destination_factors")

    origin_summary = (
        origin_factors.groupby(["dms_orig", "sctgG5"], as_index=False)["f_orig"]
        .sum()
        .rename(columns={"f_orig": "factor_sum"})
    )
    destination_summary = (
        destination_factors.groupby(["dms_dest", "sctgG5"], as_index=False)["f_dest"]
        .sum()
        .rename(columns={"f_dest": "factor_sum"})
    )
    origin_summary["abs_diff_from_1"] = (origin_summary["factor_sum"] - 1.0).abs()
    destination_summary["abs_diff_from_1"] = (destination_summary["factor_sum"] - 1.0).abs()
    origin_summary["within_tolerance"] = origin_summary["abs_diff_from_1"] <= tolerance
    destination_summary["within_tolerance"] = destination_summary["abs_diff_from_1"] <= tolerance
    return {
        "origin_factor_sums": origin_summary,
        "destination_factor_sums": destination_summary,
    }


def _read_table(path: str | Path) -> pd.DataFrame:
    table_path = Path(path)
    suffix = table_path.suffix.lower()
    if suffix in {".pq", ".parquet"}:
        return _clean_columns(pd.read_parquet(table_path))
    if suffix == ".csv":
        return _read_csv_string_keys(table_path)
    raise ValueError(f"Unsupported FAF OD format: {table_path}")


def _resolve_year_column(df: pd.DataFrame, base_name: str, year: int | str | None) -> str | None:
    lookup = _column_lookup(df)
    direct = lookup.get(base_name.lower())
    if direct is not None:
        return direct
    if year is not None:
        yearly = lookup.get(f"{base_name}_{year}".lower())
        if yearly is not None:
            return yearly
    candidates = [col for col in df.columns if str(col).lower().startswith(f"{base_name}_")]
    return candidates[0] if candidates else None


def _normalize_faf_od_frame(
    faf_od: pd.DataFrame,
    year: int | str | None = None,
    mode: str | int | None = "truck",
    tons_unit: str = "thousand_tons",
    faf_zone_filter: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Normalize FAF regional OD columns in an in-memory frame."""

    df = _clean_columns(faf_od)
    df = _rename_first(df, ["dms_orig", "origin_faf", "origin_zone"], "origin_faf")
    df = _rename_first(df, ["dms_dest", "destination_faf", "destination_zone"], "destination_faf")
    df = _rename_first(df, ["sctg2", "sctg", "commodity"], "sctg")
    df = _rename_first(df, ["sctgG5", "sctgg5"], "sctgG5")
    df = _rename_first(df, ["dms_mode", "mode"], "mode")

    tons_col = _resolve_year_column(df, "tons", year)
    if tons_col is None:
        raise ValueError("FAF OD table must contain 'tons' or 'tons_YEAR'")
    value_col = _resolve_year_column(df, "value", year)

    _require_columns(df, ["origin_faf", "destination_faf", "mode"], "faf_od")
    if "sctg" not in df.columns and "sctgG5" not in df.columns:
        raise ValueError("FAF OD table must contain 'sctg2'/'sctg' or 'sctgG5'")

    result = pd.DataFrame(
        {
            "origin_faf": _as_key(df["origin_faf"]),
            "destination_faf": _as_key(df["destination_faf"]),
            "mode": _as_key(df["mode"]),
            "tons": _as_number(df[tons_col], tons_col),
            "year": int(year) if year is not None else np.nan,
        }
    )
    if "sctg" in df.columns:
        result["sctg"] = _as_key(df["sctg"])
    if "sctgG5" in df.columns:
        result["sctgG5"] = _as_key(df["sctgG5"])
    result["value"] = _as_optional_number(df[value_col]) if value_col else np.nan

    if tons_unit == "thousand_tons":
        result["tons"] = result["tons"] * 1000.0
    elif tons_unit != "tons":
        raise ValueError("tons_unit must be 'tons' or 'thousand_tons'")

    mode_code = MODE_CODES.get(str(mode).lower(), str(mode)) if mode is not None else None
    if mode_code is not None:
        mode_text = result["mode"].astype(str).str.strip().str.lower()
        result = result[(mode_text == str(mode_code).lower()) | (mode_text == str(mode).lower())].copy()
    if faf_zone_filter is not None:
        zones = {str(int(str(zone).strip())) if str(zone).strip().isdigit() else str(zone).strip() for zone in faf_zone_filter}
        origin = _as_faf_zone_code(result["origin_faf"])
        destination = _as_faf_zone_code(result["destination_faf"])
        result = result[origin.isin(zones) | destination.isin(zones)].copy()
    result["origin_faf"] = _as_faf_zone_code(result["origin_faf"])
    result["destination_faf"] = _as_faf_zone_code(result["destination_faf"])
    result = result[result["tons"] > 0].reset_index(drop=True)
    return map_faf_sctg_to_sctgG5(result)


def load_faf_regional_od(
    faf_od_path: str | Path,
    year: int | str | None = None,
    mode: str | int | None = "truck",
    tons_unit: str = "thousand_tons",
    faf_zone_filter: Iterable[str] | None = None,
    chunksize: int | None = None,
) -> pd.DataFrame:
    """Load and normalize FAF regional OD flows.

    When ``chunksize`` is provided for CSV input, rows are streamed and filtered
    before concatenation. This is useful for VA-scale runs from national FAF CSVs.
    """

    table_path = Path(faf_od_path)
    if chunksize and table_path.suffix.lower() == ".csv":
        pieces: list[pd.DataFrame] = []
        for chunk in pd.read_csv(table_path, dtype=str, chunksize=chunksize, low_memory=False):
            normalized = _normalize_faf_od_frame(
                chunk,
                year=year,
                mode=mode,
                tons_unit=tons_unit,
                faf_zone_filter=faf_zone_filter,
            )
            if not normalized.empty:
                pieces.append(normalized)
        if not pieces:
            return pd.DataFrame(
                columns=["origin_faf", "destination_faf", "mode", "tons", "year", "sctg", "sctgG5", "value"]
            )
        return pd.concat(pieces, ignore_index=True)

    df = _read_table(table_path)
    return _normalize_faf_od_frame(
        df,
        year=year,
        mode=mode,
        tons_unit=tons_unit,
        faf_zone_filter=faf_zone_filter,
    )


def _sctg_to_group(value: object) -> str:
    text = str(value).strip().lower()
    if text.startswith("sctg") and len(text) > 4:
        return text
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        raise ValueError(f"Cannot map SCTG value {value!r} to sctgG5")
    code = int(digits)
    for group, codes in SCTG_G5_GROUPS:
        if code in codes:
            return group
    raise ValueError(f"SCTG code {value!r} is outside the expected 01-43 range")


def map_faf_sctg_to_sctgG5(faf_od: pd.DataFrame) -> pd.DataFrame:
    """Ensure a FAF OD table has BTS factor-compatible ``sctgG5`` groups."""

    result = faf_od.copy()
    if "origin_faf" in result.columns:
        result["origin_faf"] = _as_faf_zone_code(result["origin_faf"])
    if "destination_faf" in result.columns:
        result["destination_faf"] = _as_faf_zone_code(result["destination_faf"])
    if "sctgG5" not in result.columns or result["sctgG5"].isna().any():
        if "sctg" not in result.columns:
            raise ValueError("Cannot derive sctgG5 without an sctg/sctg2 column")
        result["sctgG5"] = result["sctg"].map(_sctg_to_group)
    else:
        result["sctgG5"] = _as_key(result["sctgG5"]).str.lower()
    return result


def _missing_factor_records(
    faf_od: pd.DataFrame,
    origin_factors: pd.DataFrame,
    destination_factors: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    od_origin_keys = faf_od[["origin_faf", "sctgG5"]].drop_duplicates()
    od_destination_keys = faf_od[["destination_faf", "sctgG5"]].drop_duplicates()
    origin_keys = origin_factors[["dms_orig", "sctgG5"]].drop_duplicates()
    destination_keys = destination_factors[["dms_dest", "sctgG5"]].drop_duplicates()
    missing_origin = od_origin_keys.merge(
        origin_keys,
        left_on=["origin_faf", "sctgG5"],
        right_on=["dms_orig", "sctgG5"],
        how="left",
        indicator=True,
    )
    missing_destination = od_destination_keys.merge(
        destination_keys,
        left_on=["destination_faf", "sctgG5"],
        right_on=["dms_dest", "sctgG5"],
        how="left",
        indicator=True,
    )
    return (
        missing_origin.loc[missing_origin["_merge"] == "left_only", ["origin_faf", "sctgG5"]],
        missing_destination.loc[missing_destination["_merge"] == "left_only", ["destination_faf", "sctgG5"]],
    )


def disaggregate_faf_to_county(
    faf_od: pd.DataFrame,
    origin_factors: pd.DataFrame,
    destination_factors: pd.DataFrame,
    chunk_size: int = 10_000,
    drop_missing: bool = True,
) -> pd.DataFrame:
    """Disaggregate regional FAF OD rows to county-to-county OD rows.

    Processing is chunked over FAF OD rows to avoid constructing a national
    cross join all at once.
    """

    faf = map_faf_sctg_to_sctgG5(faf_od)
    _require_columns(faf, ["origin_faf", "destination_faf", "sctgG5", "mode", "year", "tons"], "faf_od")
    missing_origin, missing_destination = _missing_factor_records(faf, origin_factors, destination_factors)
    if (not drop_missing) and (not missing_origin.empty or not missing_destination.empty):
        raise ValueError(
            "Missing disaggregation factors. "
            f"origin_missing={len(missing_origin):,}, destination_missing={len(missing_destination):,}"
        )

    outputs: list[pd.DataFrame] = []
    for start in range(0, len(faf), chunk_size):
        chunk = faf.iloc[start : start + chunk_size].copy()
        chunk["_od_row_id"] = np.arange(start, start + len(chunk))
        merged = chunk.merge(
            origin_factors,
            left_on=["origin_faf", "sctgG5"],
            right_on=["dms_orig", "sctgG5"],
            how="inner" if drop_missing else "left",
        )
        merged = merged.merge(
            destination_factors,
            left_on=["destination_faf", "sctgG5"],
            right_on=["dms_dest", "sctgG5"],
            how="inner" if drop_missing else "left",
        )
        if merged.empty:
            continue
        factor_product = merged["f_orig"] * merged["f_dest"]
        out = pd.DataFrame(
            {
                "origin_faf": merged["origin_faf"],
                "destination_faf": merged["destination_faf"],
                "origin_county": _as_key(merged["origin_county"]),
                "destination_county": _as_key(merged["destination_county"]),
                "sctgG5": merged["sctgG5"],
                "mode": merged["mode"],
                "year": merged["year"],
                "tons": merged["tons"] * factor_product,
                "value": merged["value"] * factor_product if "value" in merged.columns else np.nan,
            }
        )
        outputs.append(out)
    if not outputs:
        return pd.DataFrame(columns=COUNTY_OD_COLUMNS)
    county_od = pd.concat(outputs, ignore_index=True)
    return county_od.groupby(
        ["origin_faf", "destination_faf", "origin_county", "destination_county", "sctgG5", "mode", "year"],
        as_index=False,
        dropna=False,
    ).agg(tons=("tons", "sum"), value=("value", "sum"))


def _normalize_payload_factors(payload_factors: pd.DataFrame) -> pd.DataFrame:
    payload = _clean_columns(payload_factors)
    payload = _rename_first(payload, ["sctgG5", "sctgg5", "commodity"], "sctgG5")
    payload = _rename_first(payload, ["payload_tons", "payload", "tons_per_truck"], "payload_tons")
    _require_columns(payload, ["sctgG5", "payload_tons"], "payload_factors")
    payload = payload.copy()
    payload["sctgG5"] = _as_key(payload["sctgG5"]).str.lower()
    payload["payload_tons"] = _as_number(payload["payload_tons"], "payload_tons")
    if "truck_type" not in payload.columns:
        payload["truck_type"] = "truck"
    return payload[["sctgG5", "truck_type", "payload_tons"]]


def convert_tons_to_truck_trips(
    county_od: pd.DataFrame,
    payload_factors: pd.DataFrame | None = None,
    annual_to_daily_factor: float = 365,
    default_payload_tons: float | None = None,
) -> pd.DataFrame:
    """Add annual/daily truck trip fields when payload factors are available."""

    result = county_od.copy()
    if payload_factors is None:
        if default_payload_tons is None:
            return result
        result["annual_truck_trips"] = result["tons"] / float(default_payload_tons)
        result["daily_truck_trips"] = result["annual_truck_trips"] / float(annual_to_daily_factor)
        return result
    payload = _normalize_payload_factors(payload_factors)
    result = result.merge(payload, on="sctgG5", how="left")
    missing_payload = result["payload_tons"].isna()
    if missing_payload.any():
        missing_groups = sorted(result.loc[missing_payload, "sctgG5"].dropna().unique())
        raise ValueError(f"Missing payload factors for sctgG5 groups: {missing_groups}")
    result["annual_truck_trips"] = result["tons"] / result["payload_tons"]
    result["daily_truck_trips"] = result["annual_truck_trips"] / float(annual_to_daily_factor)
    return result


def add_default_truck_trips(
    county_od: pd.DataFrame,
    *,
    default_payload_tons: float = 20.0,
    annual_to_daily_factor: float = 365,
) -> pd.DataFrame:
    """Convert county tons to truck trips using a single payload assumption."""

    return convert_tons_to_truck_trips(
        county_od,
        payload_factors=None,
        annual_to_daily_factor=annual_to_daily_factor,
        default_payload_tons=default_payload_tons,
    )


def write_county_od_outputs(county_od: pd.DataFrame, output_path: str | Path) -> Path:
    """Write county OD output as CSV or parquet based on suffix."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".pq", ".parquet"}:
        county_od.to_parquet(path, index=False)
    else:
        county_od.to_csv(path, index=False)
    return path


def summarize_disaggregation_quality(
    faf_od: pd.DataFrame,
    county_od: pd.DataFrame,
    origin_factors: pd.DataFrame | None = None,
    destination_factors: pd.DataFrame | None = None,
) -> dict[str, object]:
    """Summarize total preservation and missing-factor diagnostics."""

    total_faf_tons = float(pd.to_numeric(faf_od["tons"], errors="coerce").fillna(0.0).sum())
    total_county_tons = float(pd.to_numeric(county_od["tons"], errors="coerce").fillna(0.0).sum())
    percent_difference = (
        100.0 * (total_county_tons - total_faf_tons) / total_faf_tons
        if total_faf_tons
        else 0.0
    )
    summary: dict[str, object] = {
        "total_faf_tons": total_faf_tons,
        "total_county_tons": total_county_tons,
        "percent_difference": percent_difference,
        "faf_od_records": int(len(faf_od)),
        "output_county_od_records": int(len(county_od)),
    }
    if origin_factors is not None and destination_factors is not None:
        missing_origin, missing_destination = _missing_factor_records(faf_od, origin_factors, destination_factors)
        summary["missing_origin_factor_records"] = int(len(missing_origin))
        summary["missing_destination_factor_records"] = int(len(missing_destination))
        input_keys = faf_od[["origin_faf", "destination_faf", "sctgG5", "mode", "year"]].drop_duplicates()
        output_keys = county_od[["origin_faf", "destination_faf", "sctgG5", "mode", "year"]].drop_duplicates()
        dropped = input_keys.merge(output_keys, on=["origin_faf", "destination_faf", "sctgG5", "mode", "year"], how="left", indicator=True)
        summary["faf_od_records_dropped"] = int((dropped["_merge"] == "left_only").sum())
    return summary


def load_payload_factors(path: str | Path | None) -> pd.DataFrame | None:
    if path is None:
        return None
    return _read_table(path)


def run_county_disaggregation(
    faf_od_path: str | Path,
    origin_factor_path: str | Path,
    destination_factor_path: str | Path,
    output_path: str | Path,
    year: int | str,
    mode: str | int | None = "truck",
    payload_factors_path: str | Path | None = None,
    tons_unit: str = "thousand_tons",
    chunk_size: int = 10_000,
    read_chunksize: int | None = None,
    faf_zone_filter: Iterable[str] | None = None,
    annual_to_daily_factor: float = 365,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Run the BTS county-factor workflow and write output."""

    origin_factors, destination_factors = load_truck_disaggregation_factors(origin_factor_path, destination_factor_path)
    factor_validation = validate_disaggregation_factors(origin_factors, destination_factors)
    bad_origin = int((~factor_validation["origin_factor_sums"]["within_tolerance"]).sum())
    bad_destination = int((~factor_validation["destination_factor_sums"]["within_tolerance"]).sum())
    if bad_origin or bad_destination:
        LOGGER.warning("Factor sums outside tolerance: origin=%s destination=%s", bad_origin, bad_destination)
    faf_od = load_faf_regional_od(
        faf_od_path,
        year=year,
        mode=mode,
        tons_unit=tons_unit,
        faf_zone_filter=faf_zone_filter,
        chunksize=read_chunksize,
    )
    county_od = disaggregate_faf_to_county(
        faf_od,
        origin_factors,
        destination_factors,
        chunk_size=chunk_size,
    )
    payload_factors = load_payload_factors(payload_factors_path)
    county_od = convert_tons_to_truck_trips(
        county_od,
        payload_factors=payload_factors,
        annual_to_daily_factor=annual_to_daily_factor,
    )
    output = write_county_od_outputs(county_od, output_path)
    summary = summarize_disaggregation_quality(faf_od, county_od, origin_factors, destination_factors)
    summary["output_path"] = str(output)
    return county_od, summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Disaggregate FAF5 regional OD flows to county-level truck OD")
    parser.add_argument("--faf-od", required=True, help="Path to FAF regional OD CSV/parquet")
    parser.add_argument("--origin-factors", required=True, help="Path to BTS truck origin factor CSV")
    parser.add_argument("--destination-factors", required=True, help="Path to BTS truck destination factor CSV")
    parser.add_argument("--output", required=True, help="Output county OD CSV/parquet")
    parser.add_argument("--year", required=True, help="FAF year to read, e.g. 2022")
    parser.add_argument("--mode", default="truck", help="Mode filter, default truck")
    parser.add_argument("--payload-factors", default=None, help="Optional payload factor CSV/parquet")
    parser.add_argument("--tons-unit", choices=["tons", "thousand_tons"], default="thousand_tons")
    parser.add_argument("--chunk-size", type=int, default=10_000)
    parser.add_argument("--read-chunksize", type=int, default=None, help="CSV read chunksize for large FAF OD files")
    parser.add_argument(
        "--faf-zone-filter",
        default=None,
        help="Optional comma-separated FAF zones. Keeps rows where origin or destination is in the set.",
    )
    parser.add_argument("--annual-to-daily-factor", type=float, default=365)
    parser.add_argument("--summary-json", default=None, help="Optional path for summary JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    args = build_arg_parser().parse_args(argv)
    county_od, summary = run_county_disaggregation(
        faf_od_path=args.faf_od,
        origin_factor_path=args.origin_factors,
        destination_factor_path=args.destination_factors,
        output_path=args.output,
        year=args.year,
        mode=args.mode,
        payload_factors_path=args.payload_factors,
        tons_unit=args.tons_unit,
        chunk_size=args.chunk_size,
        read_chunksize=args.read_chunksize,
        faf_zone_filter=[zone.strip() for zone in args.faf_zone_filter.split(",")] if args.faf_zone_filter else None,
        annual_to_daily_factor=args.annual_to_daily_factor,
    )
    LOGGER.info("Wrote %s county OD rows to %s", len(county_od), args.output)
    LOGGER.info("Disaggregation summary: %s", summary)
    if args.summary_json:
        summary_path = Path(args.summary_json)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
