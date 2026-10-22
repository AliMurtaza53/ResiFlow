import numpy as np
import pandas as pd
import pytest

from preprocess.build_multinode_county_subareas import (
    _weighted_kmeans,
    cluster_county_subareas,
    subareas_for_overload_ratio,
)


@pytest.mark.parametrize(
    "overload_ratio,expected",
    [
        (0.5, 2),   # below min -> clamp to minimum (2)
        (1.9, 2),
        (2.1, 3),
        (5.0, 5),
        (10.0, 6),  # above max -> clamp to cap (6)
    ],
)
def test_subareas_for_overload_ratio(overload_ratio, expected):
    assert subareas_for_overload_ratio(overload_ratio) == expected


def test_weighted_kmeans_separates_distinct_clusters():
    points = np.array(
        [[0.0, 0.0], [0.1, 0.1], [0.0, 0.1], [10.0, 10.0], [10.1, 10.1], [10.0, 10.1]]
    )
    weights = np.ones(len(points))
    labels = _weighted_kmeans(points, weights, k=2, seed=1)
    assert len(set(labels[:3])) == 1
    assert len(set(labels[3:])) == 1
    assert labels[0] != labels[3]


def test_weighted_kmeans_handles_k_greater_equal_n():
    points = np.array([[0.0, 0.0], [1.0, 1.0]])
    weights = np.ones(2)
    labels = _weighted_kmeans(points, weights, k=5)
    assert list(labels) == [0, 1]


def test_cluster_county_subareas_weights_sum_to_one_per_county():
    block_employment = pd.DataFrame(
        {
            "county_fips": ["00001"] * 4,
            "lon": [-80.0, -80.01, -79.0, -79.01],
            "lat": [40.0, 40.01, 41.0, 41.01],
            "freight_jobs": [10.0, 20.0, 5.0, 5.0],
        }
    )
    overload_ratios = pd.Series({"00001": 2.5})

    subareas = cluster_county_subareas(block_employment, overload_ratios)

    assert subareas["weight"].sum() == pytest.approx(1.0)
    assert (subareas["county_fips"] == "00001").all()
    assert list(subareas["subarea_rank"]) == sorted(subareas["subarea_rank"])
