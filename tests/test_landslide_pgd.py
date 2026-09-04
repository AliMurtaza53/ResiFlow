"""Sanity checks for the HAZUS landslide PGD implementation (hazards/landslide_pgd.py)."""

from __future__ import annotations

import numpy as np
import pytest

from resiflow.hazards.landslide_pgd import (
    bin_fractional_susceptibility_to_class,
    critical_acceleration_for_class,
    expected_displacement_factor_cm,
    expected_pgd_mm,
    n_cycles,
)


def test_bin_fractional_susceptibility_matches_n10_scheme():
    # max_count=81 (USGS n10): bin_width=8.1
    values = np.array([0.0, 1.0, 8.1, 8.2, 40.5, 81.0])
    classes = bin_fractional_susceptibility_to_class(values, max_count=81.0)
    assert list(classes) == [0.0, 1.0, 1.0, 2.0, 5.0, 10.0]


def test_n_cycles_matches_figure_4_12_reference_points():
    # HAZUS Fig 4-12: n(M=6) ~= 6 cycles, n(M=7.5) ~= 15 cycles.
    assert n_cycles(6.0) == pytest.approx(6.0, abs=0.2)
    assert n_cycles(7.5) == pytest.approx(15.0, abs=0.2)


def test_critical_acceleration_table_4_16():
    assert critical_acceleration_for_class(0) is None  # "None" category
    assert critical_acceleration_for_class(1) == pytest.approx(0.60)  # I
    assert critical_acceleration_for_class(10) == pytest.approx(0.05)  # X
    with pytest.raises(ValueError):
        critical_acceleration_for_class(11)


def test_displacement_factor_is_mean_of_bounds_at_table_points():
    # ratio=0.50 table row: upper=2.8, lower=1.6 -> mean=2.2
    factor = expected_displacement_factor_cm(np.array([0.50]))
    assert factor[0] == pytest.approx(2.2, rel=1e-6)


def test_displacement_factor_clamps_outside_table_domain():
    low = expected_displacement_factor_cm(np.array([0.01]))
    edge_low = expected_displacement_factor_cm(np.array([0.10]))
    high = expected_displacement_factor_cm(np.array([0.99]))
    edge_high = expected_displacement_factor_cm(np.array([0.90]))
    assert low[0] == pytest.approx(edge_low[0])
    assert high[0] == pytest.approx(edge_high[0])


def test_expected_pgd_zero_when_pga_below_critical_acceleration():
    # Category IX (ac=0.10g) under 0.05g shaking: a_is <= a_c -> no movement.
    susceptibility = np.array([[9.0]])
    pga = np.array([[0.05]])
    pgd = expected_pgd_mm(susceptibility, pga, magnitude=6.0)
    assert pgd[0, 0] == pytest.approx(0.0)


def test_expected_pgd_positive_and_matches_hand_calc():
    # Category IX (ac=0.10g), pga=0.30g, M=6.0 -> hand-calculated ~130.6mm
    # (see landslide_pgd.py's docstring for the digitized Fig 4-13 table used).
    susceptibility = np.array([[9.0]])
    pga = np.array([[0.30]])
    pgd = expected_pgd_mm(susceptibility, pga, magnitude=6.0)
    assert pgd[0, 0] == pytest.approx(130.6, rel=0.03)


def test_expected_pgd_none_category_always_zero():
    susceptibility = np.array([[0.0]])
    pga = np.array([[1.0]])  # extreme shaking, still "None" susceptibility
    pgd = expected_pgd_mm(susceptibility, pga, magnitude=7.5)
    assert pgd[0, 0] == pytest.approx(0.0)


def test_expected_pgd_propagates_nan_nodata():
    susceptibility = np.array([[np.nan]])
    pga = np.array([[0.30]])
    pgd = expected_pgd_mm(susceptibility, pga, magnitude=6.0)
    assert np.isnan(pgd[0, 0])
