"""HAZUS Earthquake Model landslide PGD (permanent ground displacement).

Implements HAZUS Earthquake Model Technical Manual Section 4.2.2.2:
 - Table 4-16: critical acceleration a_c (g) per susceptibility category
   (None, I-X).
 - Equation 4-15: n(M), the number of equivalent shaking cycles.
 - Equation 4-14: E[PGD] = E[d/a_is] * a_is * n.
 - Figure 4-13: displacement factor d/a_is (cm/cycle) vs. a_c/a_is, upper and
   lower bound curves. The manual presents this only as a graph; the values
   in _RATIO_TABLE/_UPPER_CM/_LOWER_CM below were digitized by hand from that
   figure and supplied directly by the user (not estimated/invented here).

Deliberate modeling choices, not fabricated data:
 - E[d/a_is] is the mean of the log-linear-interpolated upper and lower bound
   curves at a pixel's a_c/a_is ratio -- the expected value of a uniform
   distribution between those bounds, per the manual's stated assumption.
 - Ratios outside the digitized table's domain [0.10, 0.90] are clamped to
   the nearest edge rather than extrapolated.
 - Table 4-17's "percentage of map area susceptible" factor is intentionally
   NOT applied. That factor exists for area-averaged HAZUS runs (e.g. a
   census tract with unknown internal geology); here every pixel already
   carries its own susceptibility class, so no area-averaging is needed.
"""

from __future__ import annotations

import numpy as np

# Table 4-16: critical acceleration a_c (g) by susceptibility category.
CRITICAL_ACCELERATION_G: dict[str, float | None] = {
    "None": None,
    "I": 0.60,
    "II": 0.50,
    "III": 0.40,
    "IV": 0.35,
    "V": 0.30,
    "VI": 0.25,
    "VII": 0.20,
    "VIII": 0.15,
    "IX": 0.10,
    "X": 0.05,
}

# Ordered None, I, II, ... X -- index i <-> raster class value i (0-10).
_CATEGORY_BY_INDEX = ["None", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]

# Figure 4-13, digitized: a_c/a_is ratio -> displacement factor (cm/cycle).
_RATIO_TABLE = np.array([0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90])
_UPPER_CM = np.array([40.0, 31.0, 23.0, 12.0, 5.8, 2.8, 1.4, 0.62, 0.22, 0.055])
_LOWER_CM = np.array([22.0, 17.0, 12.5, 6.5, 3.1, 1.6, 0.82, 0.34, 0.11, 0.022])
_LOG_UPPER = np.log10(_UPPER_CM)
_LOG_LOWER = np.log10(_LOWER_CM)
RATIO_TABLE_MIN = float(_RATIO_TABLE[0])
RATIO_TABLE_MAX = float(_RATIO_TABLE[-1])


def critical_acceleration_for_class(class_index: int) -> float | None:
    """Table 4-16 lookup for an integer susceptibility class (0=None..10=X)."""
    if class_index < 0 or class_index >= len(_CATEGORY_BY_INDEX):
        raise ValueError(f"Susceptibility class {class_index} out of range [0, 10]")
    return CRITICAL_ACCELERATION_G[_CATEGORY_BY_INDEX[class_index]]


def n_cycles(magnitude: float) -> float:
    """Equation 4-15: number of equivalent cycles as a function of moment magnitude."""
    m = magnitude
    n = 0.3419 * m**3 - 5.5214 * m**2 + 33.6154 * m - 70.7692
    return max(n, 0.0)


def bin_fractional_susceptibility_to_class(
    susceptibility_count: np.ndarray, max_count: float
) -> np.ndarray:
    """Equal-width binning of a continuous susceptibility count into None/I-X.

    Some real-world susceptibility products (e.g. USGS's n10 slope-relief
    threshold model) are NOT pre-classified into HAZUS's 11-category scheme --
    n10's value is literally a count of susceptible 10m sub-cells within each
    90m cell (0..max_count, i.e. a fraction of area classified susceptible by
    an underlying binary model), a continuous quantity, not an ordinal
    category. This bins it: 0 -> "None" (class 0); otherwise the nonzero
    range (0, max_count] is split into 10 equal-width bins -> class 1 (I,
    least susceptible) .. class 10 (X, most susceptible). This is a modeling
    choice (equal-width bins on the fractional-area value, not a physically
    calibrated crosswalk to Wilson & Keefer's geologic-group categories) --
    documented, not fabricated: it preserves the source data's monotonic
    ordering and treats it as the ordinal proxy it actually is.
    """
    bin_width = max_count / 10.0
    class_index = np.where(
        susceptibility_count <= 0,
        0,
        np.ceil(susceptibility_count / bin_width),
    )
    return np.clip(class_index, 0, 10)


def expected_displacement_factor_cm(ratio: np.ndarray) -> np.ndarray:
    """Figure 4-13: E[d/a_is] (cm/cycle) as mean(upper, lower) at a_c/a_is=ratio.

    Log-linear interpolation between digitized table points; ratios outside
    [0.10, 0.90] are clamped to the nearest edge (not extrapolated).
    """
    ratio_c = np.clip(ratio, RATIO_TABLE_MIN, RATIO_TABLE_MAX)
    log_upper = np.interp(ratio_c, _RATIO_TABLE, _LOG_UPPER)
    log_lower = np.interp(ratio_c, _RATIO_TABLE, _LOG_LOWER)
    upper = np.power(10.0, log_upper)
    lower = np.power(10.0, log_lower)
    return (upper + lower) / 2.0


def expected_pgd_mm(
    susceptibility_class: np.ndarray,
    pga_g: np.ndarray,
    magnitude: float,
) -> np.ndarray:
    """Equation 4-14 applied per-pixel: E[PGD] (mm) from susceptibility class + PGA.

    ``susceptibility_class`` is an integer array, 0 (None) .. 10 (X), same
    shape as ``pga_g``. NaN in either input propagates to NaN in the output
    (nodata). Pixels where PGA does not exceed the critical acceleration
    (a_is <= a_c) get PGD=0, per the Newmark rigid-block assumption --
    downslope movement only occurs once a_is exceeds a_c.
    """
    shape = pga_g.shape
    valid = ~np.isnan(pga_g) & ~np.isnan(susceptibility_class)
    class_int = np.where(valid, np.clip(np.round(susceptibility_class), 0, 10), 0).astype(int)

    ac = np.full(shape, np.nan, dtype="float64")
    for idx, category in enumerate(_CATEGORY_BY_INDEX):
        ac_value = CRITICAL_ACCELERATION_G[category]
        mask = valid & (class_int == idx)
        if ac_value is None:
            ac[mask] = np.inf  # "None" category: never susceptible
        else:
            ac[mask] = ac_value

    n = n_cycles(magnitude)
    ratio = np.divide(ac, pga_g, out=np.full(shape, np.inf, dtype="float64"), where=(pga_g > 0))
    factor_cm = expected_displacement_factor_cm(ratio)
    pgd_cm = factor_cm * pga_g * n

    no_movement = ~valid | (pga_g <= ac)
    pgd_mm = np.where(no_movement, 0.0, pgd_cm * 10.0)
    pgd_mm = np.where(valid, pgd_mm, np.nan)
    return pgd_mm.astype("float32")
