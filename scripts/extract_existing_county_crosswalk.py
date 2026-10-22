#!/usr/bin/env python3
"""Extract today's existing single-node county->node crosswalk.

The crosswalk CSV that scripts/build_conus_freight_od.py writes
(bts_county_to_network_centroid_crosswalk_{year}.csv) lives under the
faf5_data root used to BUILD the OD (a co-author's machine per
docs/FREIGHT_OD_DISAGGREGATION.md), not under Hopper's scratch -- only the
final deliverables were copied over. But faf5_od_matrix_by_sctg.pq already
carries both origin_detail_zone/destination_detail_zone (county FIPS) and
origin_node/destination_node, so the existing single-node mapping is fully
recoverable from it without needing the original crosswalk file or the
TIGER county shapefile.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

LOGGER = logging.getLogger(__name__)


def extract_crosswalk(od_by_sctg: pd.DataFrame) -> pd.DataFrame:
    origin = od_by_sctg[["origin_detail_zone", "origin_node"]].rename(
        columns={"origin_detail_zone": "county_id", "origin_node": "node_id"}
    )
    destination = od_by_sctg[["destination_detail_zone", "destination_node"]].rename(
        columns={"destination_detail_zone": "county_id", "destination_node": "node_id"}
    )
    crosswalk = pd.concat([origin, destination], ignore_index=True).drop_duplicates("county_id")

    multi_node_counties = (
        pd.concat([origin, destination], ignore_index=True).groupby("county_id")["node_id"].nunique()
    )
    inconsistent = multi_node_counties[multi_node_counties > 1]
    if not inconsistent.empty:
        LOGGER.warning(
            "%d counties map to >1 node in the source OD (unexpected under today's "
            "single-node mapping); keeping the first node seen for each.",
            len(inconsistent),
        )
    return crosswalk.reset_index(drop=True)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--od-by-sctg", required=True, help="faf5_od_matrix_by_sctg.pq")
    parser.add_argument("--output", required=True, help="Output CSV: county_id,node_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    args = build_arg_parser().parse_args(argv)

    od_by_sctg = pd.read_parquet(
        args.od_by_sctg, columns=["origin_detail_zone", "destination_detail_zone", "origin_node", "destination_node"]
    )
    crosswalk = extract_crosswalk(od_by_sctg)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    crosswalk.to_csv(args.output, index=False)
    LOGGER.info("Wrote %d county->node rows to %s", len(crosswalk), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
