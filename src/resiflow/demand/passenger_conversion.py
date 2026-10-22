"""Convert LODES job counts to daily vehicle trips.

Before this module existed, LODES S000 (job count) was copied directly
into daily assignment demand (see resiflow.lodes_county_od's
county_od_to_assignment_schema docstring: "Jobs (S000) are treated as
daily person-trips for the passenger car mode"). That conflates three
separate, documented things:

  1. A job relationship is not a daily trip -- commuters who worked from
     home that day, or any day they didn't commute, generate no vehicle
     trip. ACS commuting-mode tables report "worked at home" as its own
     share of all workers, which nets this out for free when auto mode
     share is read as a fraction of ALL workers (not just those who
     commute by some means).
  2. Not every commuting worker drives alone -- some carpool (sharing one
     vehicle among several people), some use transit/walk/other modes
     (zero vehicle-trip contribution here; freight/passenger vehicle
     assignment, not person-trip assignment).
  3. A home->work LODES pair is one direction. A static daily assignment
     needs the return (work->home) leg too, same as the existing GB
     pipeline's own convention (nird_script1.py literally does
     ``od_node_2021["Car21"] = od_node_2021["Car21"] * 2`` for exactly
     this reason) -- this module defaults to the same round-trip
     doubling for consistency with that established precedent, but
     exposes it as a parameter since "does a LODES home-work pair
     already represent a full day's bidirectional flow" is a genuine,
     unresolved modeling choice, not a settled fact.

Default parameters and their sources (national, uniform by default --
a real simplification; county-level ACS tables could refine this later
if the sensitivity below turns out to matter):

  - auto_share_drove_alone = 0.692, auto_share_carpool = 0.092: 2024 ACS
    1-year national commuting-mode shares (drove alone 69.2%, carpooled
    9.2%, worked at home 13.3%, remainder transit/walk/other ~8.3%).
    Source: Census Bureau ACS 1-year commuting tables (B08301/S0801),
    as summarized by newgeography.com's 2024 ACS release writeup.
    Both shares are fractions of ALL workers (so "worked at home" and
    non-auto modes are already excluded -- no separate "attendance"
    factor is layered on top, which would double-count the same
    exclusion).
  - carpool_occupancy = 2.4: standard transportation-planning estimate
    for persons per carpool vehicle (used here only to convert carpool
    PERSON trips into carpool VEHICLE trips; drove-alone is always 1
    person per vehicle by definition). Flagged as the least-certain
    input -- plausible range 2.0-2.8 in the literature.
  - round_trip_factor = 2.0: matches this codebase's own existing GB
    convention (see docstring above), representing the AM + PM commute
    legs of a single home-work relationship.

Combined default: vehicle_trips_daily = jobs * (0.692 + 0.092/2.4) * 2.0
                                       ≈ jobs * 1.46

Note this is LARGER than the naive jobs-as-trips baseline, not smaller
-- round-trip doubling (x2) outweighs the mode-share/occupancy
reduction (x0.73). Whether that round-trip doubling belongs here at all
is the single largest source of uncertainty in this conversion (see
``round_trip_factor`` sensitivity below): without it, the net factor is
~0.73x (a reduction), matching the more intuitive expectation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

# National 2024 ACS 1-year commuting-mode shares (fraction of ALL workers).
DEFAULT_AUTO_SHARE_DROVE_ALONE = 0.692
DEFAULT_AUTO_SHARE_CARPOOL = 0.092
# Standard transportation-planning carpool-occupancy estimate (persons/vehicle).
DEFAULT_CARPOOL_OCCUPANCY = 2.4
# Matches the existing GB pipeline's own round-trip convention.
DEFAULT_ROUND_TRIP_FACTOR = 2.0


@dataclass(frozen=True)
class PassengerConversionParams:
    """Documented parameters for jobs -> daily vehicle trips. See module docstring for sources."""

    auto_share_drove_alone: float = DEFAULT_AUTO_SHARE_DROVE_ALONE
    auto_share_carpool: float = DEFAULT_AUTO_SHARE_CARPOOL
    carpool_occupancy: float = DEFAULT_CARPOOL_OCCUPANCY
    round_trip_factor: float = DEFAULT_ROUND_TRIP_FACTOR

    @property
    def net_vehicle_trip_rate(self) -> float:
        """Vehicle trips per job, before round-trip doubling."""
        return self.auto_share_drove_alone + self.auto_share_carpool / self.carpool_occupancy

    @property
    def combined_factor(self) -> float:
        """Vehicle trips per job, including round-trip doubling -- the single multiplier to apply."""
        return self.net_vehicle_trip_rate * self.round_trip_factor


DEFAULT_PARAMS = PassengerConversionParams()

# Sensitivity scenarios: same auto-share/occupancy assumptions, differing
# only on the single most uncertain modeling choice (round-trip doubling).
SENSITIVITY_SCENARIOS: dict[str, PassengerConversionParams] = {
    "central_with_round_trip": DEFAULT_PARAMS,
    "central_no_round_trip": replace(DEFAULT_PARAMS, round_trip_factor=1.0),
    "low_carpool_occupancy": replace(DEFAULT_PARAMS, carpool_occupancy=2.0),
    "high_carpool_occupancy": replace(DEFAULT_PARAMS, carpool_occupancy=2.8),
}


def convert_jobs_to_vehicle_trips(
    jobs: pd.Series | float,
    params: PassengerConversionParams = DEFAULT_PARAMS,
) -> pd.Series | float:
    """Convert LODES job counts to daily vehicle trips using ``params``."""
    return jobs * params.combined_factor


def sensitivity_report(jobs_total: float) -> pd.DataFrame:
    """Vehicle-trip totals under each named sensitivity scenario, for reporting uncertainty."""
    rows = [
        {
            "scenario": name,
            "net_vehicle_trip_rate": p.net_vehicle_trip_rate,
            "round_trip_factor": p.round_trip_factor,
            "combined_factor": p.combined_factor,
            "vehicle_trips": jobs_total * p.combined_factor,
        }
        for name, p in SENSITIVITY_SCENARIOS.items()
    ]
    return pd.DataFrame(rows)


__all__ = [
    "PassengerConversionParams",
    "DEFAULT_PARAMS",
    "SENSITIVITY_SCENARIOS",
    "convert_jobs_to_vehicle_trips",
    "sensitivity_report",
]
