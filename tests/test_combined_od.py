import pandas as pd

from resiflow.combined_od import combine_freight_passenger_od, load_combined_assignment_od


def test_combine_freight_passenger_od_sums_flows():
    freight = pd.DataFrame(
        [
            {"origin_node": "1", "destination_node": "2", "Car21": 10.0},
            {"origin_node": "2", "destination_node": "3", "Car21": 5.0},
        ]
    )
    passenger = pd.DataFrame(
        [
            {"origin_node": "1", "destination_node": "2", "Car21": 3.0},
            {"origin_node": "4", "destination_node": "5", "Car21": 7.0},
        ]
    )
    combined = combine_freight_passenger_od(freight, passenger)
    assert combined.set_index(["origin_node", "destination_node"]).loc[("1", "2"), "Car21"] == 13.0
    assert combined.set_index(["origin_node", "destination_node"]).loc[("4", "5"), "Car21"] == 7.0


def test_load_combined_assignment_od_without_passenger():
    freight = pd.DataFrame([{"origin_node": "1", "destination_node": "2", "Car21": 8.0}])
    assignment, stats = load_combined_assignment_od(freight, passenger_path=None)
    assert stats["passenger_flow"] == 0.0
    assert assignment["Car21"].sum() == 8.0
