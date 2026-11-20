"""Alignment of an observed chronicle on the stamps of a run, in the units of the chronicle.

A run stamps each stress period at its end. A discharge stands for the whole period
``[start, stamp)`` and is averaged there. A MODFLOW head or a lake stage is the state at the
stamp instant, so it takes the window centred on the stamp. The chronicle below is worth its
day number from 2000-01-01 = 0, so every window mean is the middle of the days it holds.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.derive.time_alignment import (
    align_observed_simulated,
    first_period_start,
    observed_on_simulation_index,
    read_pair,
    run_period,
    run_period_edges,
    run_period_start,
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


class NoTimeGrid:
    """A run served without its time grid: asking for the periods fails."""

    @property
    def periods(self):
        raise AttributeError("no periods")


CATALOG_EDGES = pd.DatetimeIndex(["2000-01-01", "2000-02-01", "2000-03-01"])


def run_with(stamps, edges=None):
    periods = SimpleNamespace(edges=edges)
    return SimpleNamespace(periods=periods, time_index=stamps)


def test_edges_of_a_run_come_from_the_catalog_first():
    edges = run_period_edges(run_with(MONTH_ENDS, CATALOG_EDGES))

    assert edges.equals(CATALOG_EDGES)


def test_edges_of_a_run_follow_from_its_stamps():
    # Three end stamps give three periods, so four edges, the last three being the stamps.
    edges = run_period_edges(run_with(MONTH_ENDS))

    assert len(edges) == 4
    assert edges[1:].equals(MONTH_ENDS)
    assert edges[0] < MONTH_ENDS[0]


NO_EDGES = [
    pytest.param(run_with(pd.DatetimeIndex(["2000-02-01"])), id="one stamp"),
    pytest.param(run_with(None), id="no stamps"),
    pytest.param(SimpleNamespace(periods=SimpleNamespace(edges=None)), id="no time axis"),
    pytest.param(NoTimeGrid(), id="periods refused"),
]


@pytest.mark.parametrize("run", NO_EDGES)
def test_run_without_dates_has_no_edges(run):
    assert run_period_edges(run) is None


def run_with_row(row):
    def load_row():
        if isinstance(row, Exception):
            raise row
        return row

    return SimpleNamespace(_load_row=load_row)


START_BEFORE = [
    pytest.param(SimpleNamespace(), None, id="no loader"),
    pytest.param(run_with_row(RuntimeError("no row")), None, id="loader fails"),
    pytest.param(run_with_row({}), None, id="no period_start"),
    pytest.param(run_with_row({"period_start": pd.NaT}), None, id="NaT start"),
    pytest.param(run_with_row({"period_start": "2000-01-01"}), pd.Timestamp("2000-01-01"), id="ok"),
    pytest.param(run_with_row({"period_start": "2001-01-01"}), None, id="start after stamps"),
]


@pytest.mark.parametrize(("run", "expected"), START_BEFORE)
def test_run_period_start(run, expected):
    assert run_period_start(run, MONTH_ENDS) == expected


def test_run_period_is_the_date_window_of_the_edges():
    window = run_period(run_with(MONTH_ENDS, CATALOG_EDGES))

    assert (window.start, window.end) == (CATALOG_EDGES[0].date(), CATALOG_EDGES[-1].date())


def test_run_period_is_none_without_dates():
    assert run_period(run_with(None)) is None


def test_a_tz_aware_simulation_index_is_read_as_naive_utc():
    aware = MONTH_ENDS.tz_localize("UTC")

    out = observed_on_simulation_index(DAY_NUMBER, aware, method="mean")

    assert out.index.tz is None
    assert out.index.equals(MONTH_ENDS)


def test_an_empty_simulation_gives_an_empty_pair():
    empty = pd.Series([], index=pd.DatetimeIndex([]), dtype=float)

    out = align_observed_simulated(DAY_NUMBER, empty)

    assert out.empty
    assert list(out.columns) == ["obs", "sim"]


def _pair_run(stations):
    simulated = pd.Series([1.0, 2.0, 3.0], index=MONTH_ENDS)
    raw = pd.DataFrame(
        {
            "station_id": stations,
            "value": np.arange(len(DAYS_2000), dtype=float),
            "datetime": DAYS_2000,
        }
    )
    return SimpleNamespace(
        name="r",
        timeseries=lambda variable, station=None: simulated,
        observed=lambda family, station=None: raw,
        _load_row=lambda: {"period_start": "2000-01-01"},
    )


def test_read_pair_refuses_several_stations_without_a_name():
    stations = ["A"] * 100 + ["B"] * (len(DAYS_2000) - 100)

    with pytest.raises(ValueError, match="several stations.*A, B"):
        read_pair(_pair_run(stations), "discharge")


def test_read_pair_returns_both_columns_on_the_simulated_index():
    out = read_pair(_pair_run(["A"] * len(DAYS_2000)), "discharge")

    assert list(out.columns) == ["simulated", "observed"]
    assert out.index.equals(MONTH_ENDS)
    assert out["observed"].notna().all()
