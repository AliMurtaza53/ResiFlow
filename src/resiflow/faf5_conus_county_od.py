"""Build a full-CONUS county-to-county FAF5 freight OD matrix.

The workflow reads FAF5 regional OD flows and BTS county factors, then writes
only the total county-pair matrix. It avoids state/regional IX/XI/XX/II handling
and does not materialize the detailed FAF/commodity county OD table.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from resiflow import faf5_county_disaggregation as county


LOGGER = logging.getLogger(__name__)

COUNTY_PAIR_COLUMNS = ["origin_county", "destination_county", "tons", "value"]
COUNTY_OD_SCTG_COLUMNS = [
    "origin_county",
    "destination_county",
    "sctgG5",
    "mode",
    "year",
    "tons",
    "value",
]


def _aggregate_detail_to_county_pairs(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame(columns=COUNTY_PAIR_COLUMNS)
    result = detail.copy()
    result["tons"] = pd.to_numeric(result["tons"], errors="coerce").fillna(0.0)
    if "value" not in result.columns:
        result["value"] = 0.0
    result["value"] = pd.to_numeric(result["value"], errors="coerce").fillna(0.0)
    return result.groupby(["origin_county", "destination_county"], as_index=False, dropna=False).agg(
        tons=("tons", "sum"),
        value=("value", "sum"),
    )


def _combine_total_pieces(pieces: list[pd.DataFrame]) -> pd.DataFrame:
    if not pieces:
        return pd.DataFrame(columns=COUNTY_PAIR_COLUMNS)
    combined = pd.concat(pieces, ignore_index=True)
    return _aggregate_detail_to_county_pairs(combined)


def _aggregate_faf_pieces(pieces: list[pd.DataFrame]) -> pd.DataFrame:
    if not pieces:
        return pd.DataFrame(columns=["origin_faf", "destination_faf", "sctgG5", "mode", "year", "tons", "value"])
    combined = pd.concat(pieces, ignore_index=True)
    return combined.groupby(
        ["origin_faf", "destination_faf", "sctgG5", "mode", "year"],
        as_index=False,
        dropna=False,
    ).agg(tons=("tons", "sum"), value=("value", "sum"))


def load_faf_regional_totals(
    faf_od_path: str | Path,
    year: int | str,
    mode: str | int | None = "truck",
    tons_unit: str = "thousand_tons",
    read_chunksize: int = 50_000,
    combine_every: int = 25,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Stream the FAF CSV and collapse it to unique regional OD/SCTG rows."""

    pieces: list[pd.DataFrame] = []
    total_faf_rows = 0
    kept_faf_rows = 0
    table_path = Path(faf_od_path)
    for raw_chunk in pd.read_csv(table_path, dtype=str, chunksize=read_chunksize, low_memory=False):
        total_faf_rows += len(raw_chunk)
        faf_chunk = county._normalize_faf_od_frame(  # noqa: SLF001 - shared normalization for this FAF schema.
            raw_chunk,
            year=year,
            mode=mode,
            tons_unit=tons_unit,
            faf_zone_filter=None,
        )
        kept_faf_rows += len(faf_chunk)
        if not faf_chunk.empty:
            pieces.append(_aggregate_faf_pieces([faf_chunk]))
        if len(pieces) >= combine_every:
            pieces = [_aggregate_faf_pieces(pieces)]
        LOGGER.info("Read %s FAF rows; kept %s truck rows", f"{total_faf_rows:,}", f"{kept_faf_rows:,}")

    return _aggregate_faf_pieces(pieces), {
        "input_faf_rows_read": int(total_faf_rows),
        "faf_rows_after_filters": int(kept_faf_rows),
    }


def _aggregate_detail_to_county_sctg(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame(columns=COUNTY_OD_SCTG_COLUMNS)
    result = detail.copy()
    result["tons"] = pd.to_numeric(result["tons"], errors="coerce").fillna(0.0)
    if "value" not in result.columns:
        result["value"] = 0.0
    result["value"] = pd.to_numeric(result["value"], errors="coerce").fillna(0.0)
    return result.groupby(
        ["origin_county", "destination_county", "sctgG5", "mode", "year"],
        as_index=False,
        dropna=False,
    ).agg(tons=("tons", "sum"), value=("value", "sum"))


def _combine_sctg_pieces(pieces: list[pd.DataFrame]) -> pd.DataFrame:
    if not pieces:
        return pd.DataFrame(columns=COUNTY_OD_SCTG_COLUMNS)
    combined = pd.concat(pieces, ignore_index=True)
    return _aggregate_detail_to_county_sctg(combined)


def aggregate_faf_chunk_to_county_sctg(
    faf_od: pd.DataFrame,
    origin_factors: pd.DataFrame,
    destination_factors: pd.DataFrame,
    *,
    od_chunk_size: int = 500,
) -> pd.DataFrame:
    """Disaggregate regional FAF rows to county OD while preserving sctgG5."""

    if faf_od.empty:
        return pd.DataFrame(columns=COUNTY_OD_SCTG_COLUMNS)

    pieces: list[pd.DataFrame] = []
    for start in range(0, len(faf_od), od_chunk_size):
        chunk = faf_od.iloc[start : start + od_chunk_size].copy()
        detail = county.disaggregate_faf_to_county(
            chunk,
            origin_factors,
            destination_factors,
            chunk_size=od_chunk_size,
        )
        if not detail.empty:
            pieces.append(_aggregate_detail_to_county_sctg(detail))
    return _combine_sctg_pieces(pieces)


def aggregate_faf_chunk_to_county_pairs(
    faf_od: pd.DataFrame,
    origin_factors: pd.DataFrame,
    destination_factors: pd.DataFrame,
    od_chunk_size: int = 500,
) -> pd.DataFrame:
    """Aggregate normalized FAF rows directly to total county-pair rows."""

    if faf_od.empty:
        return pd.DataFrame(columns=COUNTY_PAIR_COLUMNS)

    pieces: list[pd.DataFrame] = []
    for start in range(0, len(faf_od), od_chunk_size):
        chunk = faf_od.iloc[start : start + od_chunk_size].copy()
        merged = chunk.merge(
            origin_factors,
            left_on=["origin_faf", "sctgG5"],
            right_on=["dms_orig", "sctgG5"],
            how="inner",
        )
        merged = merged.merge(
            destination_factors,
            left_on=["destination_faf", "sctgG5"],
            right_on=["dms_dest", "sctgG5"],
            how="inner",
        )
        if merged.empty:
            continue
        factor_product = merged["f_orig"] * merged["f_dest"]
        detail = pd.DataFrame(
            {
                "origin_county": merged["origin_county"],
                "destination_county": merged["destination_county"],
                "tons": merged["tons"] * factor_product,
                "value": merged["value"] * factor_product if "value" in merged.columns else np.nan,
            }
        )
        pieces.append(_aggregate_detail_to_county_pairs(detail))
    return _combine_total_pieces(pieces)


def write_total_county_od(total_od: pd.DataFrame, output_path: str | Path) -> Path:
    """Write total county OD as CSV or parquet."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".pq", ".parquet"}:
        total_od.to_parquet(path, index=False)
    else:
        total_od.to_csv(path, index=False)
    return path


def run_conus_county_od(
    faf_od_path: str | Path,
    origin_factor_path: str | Path,
    destination_factor_path: str | Path,
    output_path: str | Path,
    year: int | str,
    mode: str | int | None = "truck",
    tons_unit: str = "thousand_tons",
    read_chunksize: int = 50_000,
    od_chunk_size: int = 500,
    combine_every: int = 50,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Stream FAF5 OD to a full-CONUS total county-to-county matrix."""

    origin_factors, destination_factors = county.load_truck_disaggregation_factors(
        origin_factor_path,
        destination_factor_path,
    )

    faf_totals, faf_summary = load_faf_regional_totals(
        faf_od_path,
        year=year,
        mode=mode,
        tons_unit=tons_unit,
        read_chunksize=read_chunksize,
        combine_every=combine_every,
    )
    LOGGER.info("Collapsed FAF rows to %s regional OD/SCTG rows", f"{len(faf_totals):,}")

    pieces: list[pd.DataFrame] = []
    for start in range(0, len(faf_totals), od_chunk_size):
        total_chunk = aggregate_faf_chunk_to_county_pairs(
            faf_totals.iloc[start : start + od_chunk_size],
            origin_factors,
            destination_factors,
            od_chunk_size=od_chunk_size,
        )
        if not total_chunk.empty:
            pieces.append(total_chunk)
        if len(pieces) >= combine_every:
            pieces = [_combine_total_pieces(pieces)]
        LOGGER.info("Expanded %s of %s regional FAF rows", f"{min(start + od_chunk_size, len(faf_totals)):,}", f"{len(faf_totals):,}")

    total_od = _combine_total_pieces(pieces)
    output = write_total_county_od(total_od, output_path)
    summary = {
        "faf_od_path": str(faf_od_path),
        "origin_factor_path": str(origin_factor_path),
        "destination_factor_path": str(destination_factor_path),
        "output_path": str(output),
        "year": int(year),
        "mode": None if mode is None else str(mode),
        **faf_summary,
        "regional_faf_od_sctg_records": int(len(faf_totals)),
        "output_county_od_records": int(len(total_od)),
        "total_county_tons": float(total_od["tons"].sum()) if "tons" in total_od.columns else 0.0,
        "total_county_value": float(total_od["value"].sum()) if "value" in total_od.columns else 0.0,
        "ix_xi_xx_ii_treatment": False,
        "state_or_regional_model_treatment": False,
        "materialized_detailed_county_od": False,
    }
    return total_od, summary


def run_conus_county_od_by_sctg(
    faf_od_path: str | Path,
    origin_factor_path: str | Path,
    destination_factor_path: str | Path,
    output_path: str | Path,
    year: int | str,
    mode: str | int | None = "truck",
    tons_unit: str = "thousand_tons",
    read_chunksize: int = 50_000,
    od_chunk_size: int = 500,
    combine_every: int = 50,
    default_payload_tons: float = 20.0,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Stream FAF5 regional OD to county-to-county OD with sctgG5 preserved."""

    origin_factors, destination_factors = county.load_truck_disaggregation_factors(
        origin_factor_path,
        destination_factor_path,
    )

    faf_totals, faf_summary = load_faf_regional_totals(
        faf_od_path,
        year=year,
        mode=mode,
        tons_unit=tons_unit,
        read_chunksize=read_chunksize,
        combine_every=combine_every,
    )
    LOGGER.info("Collapsed FAF rows to %s regional OD/SCTG rows", f"{len(faf_totals):,}")

    pieces: list[pd.DataFrame] = []
    for start in range(0, len(faf_totals), od_chunk_size):
        county_chunk = aggregate_faf_chunk_to_county_sctg(
            faf_totals.iloc[start : start + od_chunk_size],
            origin_factors,
            destination_factors,
            od_chunk_size=od_chunk_size,
        )
        if not county_chunk.empty:
            pieces.append(county_chunk)
        if len(pieces) >= combine_every:
            pieces = [_combine_sctg_pieces(pieces)]
        LOGGER.info(
            "Expanded %s of %s regional FAF rows",
            f"{min(start + od_chunk_size, len(faf_totals)):,}",
            f"{len(faf_totals):,}",
        )

    county_od = _combine_sctg_pieces(pieces)
    county_od = county.add_default_truck_trips(county_od, default_payload_tons=default_payload_tons)
    output = write_total_county_od(county_od, output_path)
    summary = {
        "faf_od_path": str(faf_od_path),
        "origin_factor_path": str(origin_factor_path),
        "destination_factor_path": str(destination_factor_path),
        "output_path": str(output),
        "year": int(year),
        "mode": None if mode is None else str(mode),
        "default_payload_tons": float(default_payload_tons),
        **faf_summary,
        "regional_faf_od_sctg_records": int(len(faf_totals)),
        "output_county_od_records": int(len(county_od)),
        "total_county_tons": float(county_od["tons"].sum()) if "tons" in county_od.columns else 0.0,
        "total_county_value": float(county_od["value"].sum()) if "value" in county_od.columns else 0.0,
        "materialized_detailed_county_od": True,
        "preserved_sctgG5": True,
    }
    return county_od, summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build full-CONUS total county-to-county FAF5 freight OD")
    parser.add_argument(
        "--faf-od",
        default=r"C:\Users\akothaw\Desktop\data\faf5_data\FAF5.7.1\FAF5.7.1.csv",
        help="Path to FAF5 regional OD CSV",
    )
    parser.add_argument(
        "--origin-factors",
        default=r"C:\Users\akothaw\Desktop\data\faf5_data\county_disaggregation_factors\truck_origin_factors.csv",
        help="Path to truck origin county factor CSV",
    )
    parser.add_argument(
        "--destination-factors",
        default=r"C:\Users\akothaw\Desktop\data\faf5_data\county_disaggregation_factors\truck_destination_factors.csv",
        help="Path to truck destination county factor CSV",
    )
    parser.add_argument(
        "--output",
        default=r"C:\Users\akothaw\Desktop\data\faf5_data\processed\faf5_county_truck_od_usa_2022_total.parquet",
        help="Output total county OD CSV/parquet",
    )
    parser.add_argument("--year", default="2022")
    parser.add_argument("--mode", default="truck", help="Mode filter; use 'all' to disable")
    parser.add_argument("--tons-unit", choices=["tons", "thousand_tons"], default="thousand_tons")
    parser.add_argument("--read-chunksize", type=int, default=50_000)
    parser.add_argument("--od-chunk-size", type=int, default=500)
    parser.add_argument("--combine-every", type=int, default=50)
    parser.add_argument(
        "--summary-json",
        default=r"C:\Users\akothaw\Desktop\data\faf5_data\processed\faf5_county_truck_od_usa_2022_total_summary.json",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    args = build_arg_parser().parse_args(argv)
    mode = None if str(args.mode).lower() == "all" else args.mode
    total_od, summary = run_conus_county_od(
        faf_od_path=args.faf_od,
        origin_factor_path=args.origin_factors,
        destination_factor_path=args.destination_factors,
        output_path=args.output,
        year=args.year,
        mode=mode,
        tons_unit=args.tons_unit,
        read_chunksize=args.read_chunksize,
        od_chunk_size=args.od_chunk_size,
        combine_every=args.combine_every,
    )
    if args.summary_json:
        summary_path = Path(args.summary_json)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    LOGGER.info("Wrote %s county OD rows to %s", f"{len(total_od):,}", args.output)
    LOGGER.info("Total county tons: %s", f"{summary['total_county_tons']:,.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
