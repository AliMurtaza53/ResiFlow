import pandas as pd
import pytest

from preprocess import map_bts_od_to_network_centroids as mapper


def test_crosswalk_uses_exact_matches_and_nearest_fallback():
    network = pd.DataFrame(
        [
            {"centroid_id": 1001.0, "node_id": "n1", "lon": -77.0, "lat": 38.0},
            {"centroid_id": "load-2", "node_id": "n2", "lon": -78.0, "lat": 39.0},
        ]
    )
    detail = pd.DataFrame(
        [
            {"detail_zone_id": "01003", "lon": -78.01, "lat": 39.01},
        ]
    )

    crosswalk, summary = mapper.build_detail_zone_crosswalk(["1001", "01003"], network, detail)

    exact = crosswalk.set_index("detail_zone_id").loc["01001"]
    nearest = crosswalk.set_index("detail_zone_id").loc["01003"]
    assert exact["assignment_method"] == "exact_match"
    assert exact["assigned_node_id"] == "n1"
    assert nearest["assignment_method"] == "nearest_loading_node"
    assert nearest["assigned_node_id"] == "n2"
    assert nearest["distance_miles"] < 1.0
    assert summary["unmatched_before_nearest_fallback"] == 1


def test_aggregate_od_to_centroids_preserves_flows_and_adds_assignment_columns():
    od = pd.DataFrame(
        [
            {
                "origin_detail_zone": "01001",
                "destination_detail_zone": "01003",
                "sctgG5": "sctg0109",
                "mode": "truck",
                "year": 2022,
                "annual_tons": 365.0,
                "value": 10.0,
                "annual_truck_trips": 730.0,
            },
            {
                "origin_detail_zone": "01001",
                "destination_detail_zone": "01003",
                "sctgG5": "sctg0109",
                "mode": "truck",
                "year": 2022,
                "annual_tons": 365.0,
                "value": 5.0,
                "daily_truck_trips": 1.0,
            },
        ]
    )
    crosswalk = pd.DataFrame(
        [
            {
                "detail_zone_id": "01001",
                "assigned_centroid": "c1",
                "assigned_node_id": "n1",
                "assignment_method": "exact_match",
                "distance_miles": 0.0,
                "warning_flag": "",
            },
            {
                "detail_zone_id": "01003",
                "assigned_centroid": "c2",
                "assigned_node_id": "n2",
                "assignment_method": "exact_match",
                "distance_miles": 0.0,
                "warning_flag": "",
            },
        ]
    )

    centroid_od, mapped = mapper.aggregate_od_to_network_centroids(od, crosswalk)
    summary = mapper.validation_summary(od, mapped, crosswalk)

    assert len(centroid_od) == 1
    assert centroid_od.loc[0, "annual_tons"] == 730.0
    assert centroid_od.loc[0, "daily_tons"] == 2.0
    assert centroid_od.loc[0, "annual_truck_trips"] == 1095.0
    assert centroid_od.loc[0, "daily_truck_trips"] == 3.0
    assert centroid_od.loc[0, "Car21"] == 3.0
    assert centroid_od.loc[0, "origin_node"] == "n1"
    assert centroid_od.loc[0, "destination_node"] == "n2"
    assert summary["total_tons_before_mapping"] == pytest.approx(summary["total_tons_after_mapping"])
    assert summary["ii_ix_xi_xx_classification_applied"] is False


def test_network_centroids_can_be_remapped_to_assignment_nodes():
    network_centroids = pd.DataFrame(
        [
            {"CentroidID": "c1", "ID": "raw-node", "lon": -77.0, "lat": 38.0},
        ]
    )
    network_nodes = pd.DataFrame(
        [
            {"node_id": "assignment-1", "lon": -77.001, "lat": 38.001},
            {"node_id": "assignment-2", "lon": -80.0, "lat": 40.0},
        ]
    )

    mapped = mapper.map_network_centroids_to_assignment_nodes(network_centroids, network_nodes)

    assert mapped.loc[0, "centroid_id"] == "c1"
    assert mapped.loc[0, "node_id"] == "assignment-1"
    assert mapped.loc[0, "_node_distance_m"] < 200


def test_default_payload_fills_missing_truck_trips_for_assignment():
    od = pd.DataFrame(
        [
            {
                "origin_detail_zone": "01001",
                "destination_detail_zone": "01003",
                "annual_tons": 40.0,
            }
        ]
    )

    normalized = mapper.normalize_bts_od(od, default_payload_tons=20.0)

    assert normalized.loc[0, "annual_truck_trips"] == 2.0
    assert normalized.loc[0, "daily_truck_trips"] == pytest.approx(2.0 / 365.0)
