import numpy as np
import pandas as pd

from resiflow.road_revised import compute_costs_for_links
from resiflow.tables import avg_fuel_usd_per_mile


def _links():
    return pd.DataFrame({"time_hr": [0.5, 1.0], "length_mile": [20.0, 50.0]})


def test_sealed_rates():
    assert avg_fuel_usd_per_mile("car") == 0.187
    assert avg_fuel_usd_per_mile("ogv") == 0.6022
    assert avg_fuel_usd_per_mile("psv") is None


def test_fuel_cost_is_rate_times_miles_and_speed_independent():
    for vt, rate in (("car", 0.187), ("ogv", 0.6022)):
        out = compute_costs_for_links(_links(), vt, inplace=False)
        op = np.asarray(out["operating_cost"] if hasattr(out, "columns") else out[:, 1])
        np.testing.assert_allclose(op, rate * np.array([20.0, 50.0]))
