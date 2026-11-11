"""The one-period grid of a steady initialization spans the source grid.

A steady start runs one period as long as the source periods together, and keeps
the lengths of the source periods so a rate is averaged over them.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.time.steady_initialization import single_period_mean_forcing_time_grid

_DAY = 86400.0

_WINDOW = SimpleNamespace(start="2020-01-01", end="2020-01-05", step_value=2, step_unit="hour")

# One row per source grid: its fields, the period length in seconds, the record lengths
# kept (None when the source has fewer than two valid periods) and the boundaries kept.
_GRIDS = [
    pytest.param(
        {"period_lengths_seconds": [_DAY, _DAY, 2 * _DAY]},
        4 * _DAY,
        [_DAY, _DAY, 2 * _DAY],
        (),
        id="three_periods_sum",
    ),
    pytest.param(
        {"period_lengths_seconds": [_DAY, 0.0, float("nan"), -_DAY, 2 * _DAY]},
        3 * _DAY,
        [_DAY, 2 * _DAY],
        (),
        id="zero_nan_and_negative_periods_dropped",
    ),
    pytest.param(
        {"period_lengths_seconds": [10.0]}, 10.0, None, (), id="one_period_keeps_no_records"
    ),
    pytest.param({}, 1.0, None, (), id="no_period_is_one_second"),
    pytest.param(
        {"period_lengths_seconds": [_DAY, _DAY], "boundaries": ("a", "b", "c")},
        2 * _DAY,
        [_DAY, _DAY],
        ("a", "c"),
        id="boundaries_cut_to_the_two_ends",
    ),
    pytest.param(
        {"period_lengths_seconds": [_DAY, _DAY], "boundaries": ("a",)},
        2 * _DAY,
        [_DAY, _DAY],
        (),
        id="one_boundary_is_no_boundary",
    ),
]


@pytest.mark.parametrize(("fields", "length", "records", "boundaries"), _GRIDS)
def test_the_period_is_the_sum_of_the_valid_source_periods(
    fields, length, records, boundaries
) -> None:
    grid = single_period_mean_forcing_time_grid(SimpleNamespace(**fields))

    assert grid.period_lengths_seconds.tolist() == [length]
    assert grid.nstp_per_period == 1
    assert grid.boundaries == boundaries
    if records is None:
        assert grid.record_lengths_seconds is None
    else:
        assert np.asarray(grid.record_lengths_seconds).tolist() == records


def test_a_window_with_boundaries_is_cut_to_one_period_between_the_two_ends() -> None:
    source = SimpleNamespace(
        period_lengths_seconds=[_DAY, _DAY], boundaries=("t0", "t1", "t2"), window=_WINDOW
    )

    window = single_period_mean_forcing_time_grid(source).window

    assert window.period_bounds == (("t0", "t2"),)
    assert (window.start, window.end) == ("2020-01-01", "2020-01-05")
    assert (window.step_value, window.step_unit) == (2, "hour")
    assert window.coverage_policy == "ignore"


def test_a_window_without_boundaries_is_kept_as_it_is() -> None:
    source = SimpleNamespace(period_lengths_seconds=[_DAY, _DAY], window=_WINDOW)

    assert single_period_mean_forcing_time_grid(source).window is _WINDOW


def test_a_grid_with_no_window_has_none() -> None:
    source = SimpleNamespace(period_lengths_seconds=[_DAY, _DAY])

    assert single_period_mean_forcing_time_grid(source).window is None
