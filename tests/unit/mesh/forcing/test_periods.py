"""The start and end of every stress period, :mod:`hydromodpy.spatial.mesh.forcing.periods`."""

from __future__ import annotations

import pandas as pd
import pytest

from hydromodpy.spatial.mesh.forcing import stress_period_bounds
from tests.unit.mesh.forcing.forcing_cases import window

pytestmark = pytest.mark.fast

JAN, FEB, MAR, APR, JUL = (pd.Timestamp(f"2020-{month:02d}-01") for month in (1, 2, 3, 4, 7))


def test_without_a_window_there_is_no_period_bound():
    assert stress_period_bounds(3, None) is None


def test_a_monthly_window_gives_one_half_open_period_a_month():
    bounds = stress_period_bounds(3, window("2020-01-01", "2020-03-31"))

    assert bounds == [(JAN, FEB), (FEB, MAR), (MAR, APR)]


def test_the_periods_stop_at_the_number_the_run_asks_for():
    bounds = stress_period_bounds(2, window("2020-01-01", "2020-03-31"))

    assert bounds == [(JAN, FEB), (FEB, MAR)]


def test_a_steady_run_reads_its_one_period_over_the_whole_window():
    steady = window("2020-01-01", "2020-06-30", period_bounds=((JAN, JUL),))

    assert stress_period_bounds(1, steady) == [(JAN, JUL)]


def test_explicit_periods_stop_at_the_number_the_run_asks_for():
    explicit = window(
        "2020-01-01", "2020-03-31", period_bounds=(("2020-01-01", "2020-02-01"), (FEB, APR))
    )

    assert stress_period_bounds(1, explicit) == [(JAN, FEB)]
