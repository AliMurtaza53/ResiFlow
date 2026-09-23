"""T29 payload factors load and apply to county OD tons."""

from __future__ import annotations

import pandas as pd
import pytest

from resiflow.faf5_county_disaggregation import (
    add_default_truck_trips,
    load_t29_payload_factors,
)


def test_t29_has_five_sctgG5_groups_and_all_fallback():
    payload = load_t29_payload_factors()
    codes = set(payload["sctgG5"])
    assert codes >= {
        "sctg0109",
        "sctg1014",
        "sctg1519",
        "sctg2033",
        "sctg3499",
        "all",
    }
    assert (payload["payload_tons"] > 0).all()


def test_add_default_truck_trips_uses_t29_by_sctgG5():
    od = pd.DataFrame(
        [
            {"sctgG5": "sctg0109", "tons": 171.1},
            {"sctgG5": "sctg1014", "tons": 228.8},
        ]
    )
    out = add_default_truck_trips(od)
    by = out.set_index("sctgG5")
    assert by.loc["sctg0109", "annual_truck_trips"] == pytest.approx(10.0)
    assert by.loc["sctg1014", "annual_truck_trips"] == pytest.approx(10.0)
    assert by.loc["sctg0109", "daily_truck_trips"] == pytest.approx(10.0 / 365.0)


def test_explicit_flat_payload_overrides_t29():
    od = pd.DataFrame([{"sctgG5": "sctg0109", "tons": 100.0}])
    out = add_default_truck_trips(od, default_payload_tons=20.0)
    assert float(out["annual_truck_trips"].iloc[0]) == pytest.approx(5.0)
