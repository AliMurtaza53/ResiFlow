import json

import pandas as pd
import pytest

from resiflow.demand.combine import combine_freight_passenger_od
from resiflow.demand.county_commute import convert_od_by_home_county, load_county_factors
from resiflow.demand.vehicle_class import vehicle_class_for_mode, vehicle_class_for_stats


def test_freight_only_is_truck_class(monkeypatch):
    monkeypatch.delenv("RESIFLOW_VEHICLE_CLASS", raising=False)
    monkeypatch.delenv("NIRD_VEHICLE_CLASS", raising=False)
    assert vehicle_class_for_stats({"freight_flow": 5.0, "passenger_flow": 0.0}) == "ogv"
    assert vehicle_class_for_stats({"freight_flow": 5.0, "passenger_flow": 2.0}) == "car"
    assert vehicle_class_for_mode("freight") == "ogv"
    assert vehicle_class_for_mode("combined") == "car"


def test_override_wins(monkeypatch):
    monkeypatch.setenv("RESIFLOW_VEHICLE_CLASS", "car")
    assert vehicle_class_for_stats({"freight_flow": 5.0, "passenger_flow": 0.0}) == "car"
    monkeypatch.setenv("RESIFLOW_VEHICLE_CLASS", "banana")
    with pytest.raises(ValueError):
        vehicle_class_for_mode("freight")


def test_truck_pce_scales_only_the_load():
    freight = pd.DataFrame([{"origin_node": "1", "destination_node": "2", "Car21": 10.0}])
    passenger = pd.DataFrame([{"origin_node": "1", "destination_node": "2", "Car21": 3.0}])
    c = combine_freight_passenger_od(freight, passenger, truck_pce=2.0).iloc[0]
    assert c["Car21"] == 23.0  # 3 + 2*10 car equivalents
    assert c["freight_flow"] == 10.0 and c["passenger_flow"] == 3.0  # vehicles unchanged


def test_county_factors_use_home_county_and_fallback(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"counties": {"06059": {"vehicles_per_all_worker": 0.80}}}))
    f = load_county_factors(p)
    od = pd.DataFrame(
        {"origin_node": ["10", "20"], "destination_node": ["20", "10"], "Car21": [100.0, 100.0]}
    )
    out, rep = convert_od_by_home_county(od, {"10": "06059"}, f, fallback=0.5)
    assert out["Car21"].tolist() == [80.0, 50.0]
    assert rep["rows_using_fallback"] == 1.0
