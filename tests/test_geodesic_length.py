"""Geodesic length helper (pure pyproj/shapely; runs without the model environment)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyproj
import pytest
from shapely.geometry import LineString

from resiflow.exposure.geodesic import DATA_CRS, geodesic_length_m, length_check_summary

HOUSTON = pyproj.Transformer.from_crs("EPSG:4267", DATA_CRS, always_xy=True).transform(-95.37, 29.76)


def test_matches_projected_length_within_a_percent_near_houston():
    x, y = HOUSTON
    line = LineString([(x, y), (x + 3000.0, y), (x + 3000.0, y + 4000.0)])  # 7 km
    g = geodesic_length_m([line])[0]
    assert g == pytest.approx(7000.0, rel=0.01)


def test_segments_add_up_and_empty_geometries_are_zero():
    x, y = HOUSTON
    a, b = LineString([(x, y), (x + 1000, y)]), LineString([(x + 1000, y), (x + 1000, y + 1000)])
    both = LineString([(x, y), (x + 1000, y), (x + 1000, y + 1000)])
    ga, gb, gboth, gempty, gnone = geodesic_length_m([a, b, both, LineString(), None])
    assert gboth == pytest.approx(ga + gb, rel=1e-9)
    assert gempty == 0.0 and gnone == 0.0


def test_equals_independent_geodesic_between_endpoints():
    x, y = HOUSTON
    line = LineString([(x, y), (x + 20000.0, y + 15000.0)])  # straight, so one segment
    to_geo = pyproj.Transformer.from_crs(DATA_CRS, "EPSG:4267", always_xy=True)
    (lo1, la1), (lo2, la2) = to_geo.transform(x, y), to_geo.transform(x + 20000.0, y + 15000.0)
    expected = pyproj.Geod(ellps="clrk66").inv(lo1, la1, lo2, la2)[2]
    assert geodesic_length_m([line])[0] == pytest.approx(expected, rel=1e-9)


def test_summary_reports_totals_and_ratio():
    df = pd.DataFrame({"length": [100.0, 200.0, 0.5], "length_geodesic_m": [100.5, 199.0, 0.5]})
    s = length_check_summary(df)
    assert s["pieces"] == 2 and s["total_ratio"] == pytest.approx(299.5 / 300.0)
