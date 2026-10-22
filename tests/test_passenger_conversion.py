import pandas as pd
import pytest

from resiflow.demand.passenger_conversion import (
    DEFAULT_PARAMS,
    PassengerConversionParams,
    convert_jobs_to_vehicle_trips,
    sensitivity_report,
)


def test_default_params_combined_factor():
    # (0.692 + 0.092/2.4) * 2.0
    expected = (0.692 + 0.092 / 2.4) * 2.0
    assert DEFAULT_PARAMS.combined_factor == pytest.approx(expected)
    assert DEFAULT_PARAMS.combined_factor == pytest.approx(1.4607, abs=1e-3)


def test_net_vehicle_trip_rate_excludes_round_trip():
    assert DEFAULT_PARAMS.net_vehicle_trip_rate == pytest.approx(0.692 + 0.092 / 2.4)
    assert DEFAULT_PARAMS.net_vehicle_trip_rate < 1.0  # mode-share/occupancy alone is a reduction


def test_convert_jobs_to_vehicle_trips_scalar():
    result = convert_jobs_to_vehicle_trips(1000.0)
    assert result == pytest.approx(1000.0 * DEFAULT_PARAMS.combined_factor)


def test_convert_jobs_to_vehicle_trips_series():
    jobs = pd.Series([100.0, 200.0])
    result = convert_jobs_to_vehicle_trips(jobs)
    assert result.iloc[0] == pytest.approx(100.0 * DEFAULT_PARAMS.combined_factor)
    assert result.iloc[1] == pytest.approx(200.0 * DEFAULT_PARAMS.combined_factor)


def test_convert_jobs_to_vehicle_trips_custom_params():
    params = PassengerConversionParams(round_trip_factor=1.0)
    result = convert_jobs_to_vehicle_trips(1000.0, params=params)
    assert result == pytest.approx(1000.0 * params.net_vehicle_trip_rate)
    assert result < 1000.0  # no round-trip doubling -> net reduction


def test_sensitivity_report_covers_round_trip_choice():
    report = sensitivity_report(jobs_total=1_000_000.0)
    by_scenario = report.set_index("scenario")

    with_rt = by_scenario.loc["central_with_round_trip", "vehicle_trips"]
    without_rt = by_scenario.loc["central_no_round_trip", "vehicle_trips"]

    assert with_rt == pytest.approx(without_rt * 2.0)
    assert without_rt < 1_000_000.0  # mode-share/occupancy reduction, no round trip
    assert with_rt > 1_000_000.0  # round-trip doubling outweighs the reduction
