#!/usr/bin/env python3
"""Apply resiflow.demand.passenger_conversion to an existing passenger assignment OD.

Lets the TODAY's single-node passenger OD (origin_node,destination_node,
Car21, Car21 == raw LODES jobs) be put on the same vehicle-trip footing
as a redistribute_county_od_to_subareas.py run with
--vehicle-conversion-scenario, so a before/after comparison isn't
confounded by one side being raw jobs and the other being converted
vehicle trips.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from resiflow.demand.passenger_conversion import SENSITIVITY_SCENARIOS, convert_jobs_to_vehicle_trips  # noqa: E402

LOGGER = logging.getLogger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--passenger-od", required=True, help="Existing passenger assignment OD parquet (origin_node,destination_node,Car21)")
    parser.add_argument("--scenario", default="central_with_round_trip", choices=sorted(SENSITIVITY_SCENARIOS))
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    args = build_arg_parser().parse_args(argv)

    od = pd.read_parquet(args.passenger_od)
    params = SENSITIVITY_SCENARIOS[args.scenario]
    before_total = od["Car21"].sum()
    od["Car21"] = convert_jobs_to_vehicle_trips(od["Car21"], params=params)
    after_total = od["Car21"].sum()
    LOGGER.info(
        "Scenario '%s' (combined_factor=%.4f): %.1f jobs -> %.1f vehicle trips",
        args.scenario,
        params.combined_factor,
        before_total,
        after_total,
    )

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    od.to_parquet(args.output, index=False)
    LOGGER.info("Wrote %d rows to %s", len(od), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
