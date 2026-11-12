"""Alignment of an observed chronicle on the stamps of a run, in the units of the chronicle.

A run stamps each stress period at its end. A discharge stands for the whole period
``[start, stamp)`` and is averaged there. A MODFLOW head or a lake stage is the state at the
stamp instant, so it takes the window centred on the stamp. The chronicle below is worth its
day number from 2000-01-01 = 0, so every window mean is the middle of the days it holds.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.derive.time_alignment import (
    first_period_start,
    observed_on_simulation_index,
    time_method_for,
)
from hydromodpy.results.field_registry import FIELD_REGISTRY

DAYS_2000 = pd.date_range("2000-01-01", "2000-12-31", freq="D")
DAY_NUMBER = pd.Series(np.arange(len(DAYS_2000), dtype=float), index=DAYS_2000)
# January, February and March of a monthly run, stamped at their ends.
MONTH_ENDS = pd.DatetimeIndex(["2000-02-01", "2000-03-01", "2000-04-01"])


def test_a_monthly_head_takes_the_window_centred_on_its_stamp():
    # The stamp 2000-03-01 sits 29 days after 02-01 and 31 days before 04-01.
    # Its window reaches halfway to each: [02-15 12:00, 03-16 12:00), the days
    # 16 February to 16 March, day numbers 46 to 75, mean 60.5.
    aligned = observed_on_simulation_index(DAY_NUMBER, MONTH_ENDS, method="point")

    assert aligned.iloc[1] == pytest.approx((46 + 75) / 2)


def test_a_monthly_discharge_takes_the_month_its_stamp_closes():
    # The stamp 2000-03-01 closes February, [02-01, 03-01): day numbers 31 to
    # 59, mean 45. The head above read 60.5 on the same record.
    aligned = observed_on_simulation_index(DAY_NUMBER, MONTH_ENDS, method="mean")

    assert aligned.iloc[1] == pytest.approx((31 + 59) / 2)


def test_one_steady_period_without_a_start_takes_the_whole_chronicle():
    # 365 days of 1999, 366 of 2000, 365 of 2001. The last day before the stamp,
    # 2000.0, would be one day scored as a steady stage.
    index = pd.date_range("1999-01-01", "2001-12-31", freq="D")
    record = pd.Series(index.year.astype("float64"), index=index)

    aligned = observed_on_simulation_index(record, pd.DatetimeIndex(["2001-01-01"]), method="mean")

    assert aligned.tolist() == [pytest.approx((1999 * 365 + 2000 * 366 + 2001 * 365) / 1096)]


def test_first_period_start_is_the_bound_before_the_first_stamp():
    bounds = pd.date_range("2000-01-01", periods=4, freq="MS")

    assert first_period_start(pd.DatetimeIndex(["2000-02-01"]), bounds) == bounds[0]
    assert first_period_start(pd.DatetimeIndex(["2000-04-01"]), bounds) == bounds[2]
    assert first_period_start(pd.DatetimeIndex(["2000-01-01"]), bounds) is None
    assert first_period_start(pd.DatetimeIndex(["2000-02-01"]), None) is None


@pytest.mark.parametrize("name", sorted(FIELD_REGISTRY))
def test_registry_field_aligns_by_its_cell_methods(name):
    cell_methods = FIELD_REGISTRY[name].cell_methods
    if "time: point" in cell_methods:
        expected = "point"
    elif "time:" in cell_methods:
        expected = "mean"
    else:
        # No time entry: a static field, whose value holds at every instant.
        expected = "point"

    assert time_method_for(name) == expected


def test_an_unknown_method_is_refused():
    with pytest.raises(ValueError, match="unknown time method"):
        observed_on_simulation_index(DAY_NUMBER, MONTH_ENDS, method="median")
