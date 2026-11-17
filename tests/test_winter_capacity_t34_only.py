"""Winter capacity follows T34 day_open only (not the generic T26 schedule)."""

import pandas as pd

from resiflow.hazards.winter_storm_clearance import capacity_on_day


def _links():
    return (
        pd.Series([1, 3, 7, pd.NA, 2], dtype="Int64"),
        pd.Series(["minor", "moderate", "severe", "minor", "no"]),
        pd.Series([1000, 1000, 1000, 1000, 1000]),
    )


def test_closed_until_day_open_then_full_capacity():
    d, lvl, cap = _links()
    assert capacity_on_day(0, d, lvl, cap).tolist() == [0, 0, 0, 1000, 1000]
    assert capacity_on_day(3, d, lvl, cap).tolist() == [1000, 1000, 0, 1000, 1000]
    assert capacity_on_day(7, d, lvl, cap).tolist() == [1000] * 5


def test_no_residual_capacity_loss_after_reopening():
    """T26 would leave 50% capacity out to day ~98; T34-only must not."""
    d, lvl, cap = _links()
    for day in (14, 30, 60, 90, 98):
        assert capacity_on_day(day, d, lvl, cap).tolist() == [1000] * 5
