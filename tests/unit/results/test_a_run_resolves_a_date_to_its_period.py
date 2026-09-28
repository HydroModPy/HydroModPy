"""A stored run turns a date into the stress period that holds it.

``Run.period_edges`` rebuilds the edges from the catalog ``period_start`` and
the end stamps of ``Run.time_index``; ``Run.step_at`` and ``Run.steps_for``
read a date through ``core.time.selection``.
"""

from __future__ import annotations

from contextlib import contextmanager

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time.selection import TimeSelectionError
from hydromodpy.results.run.timeseries import RunTimeseriesMixin


class _NoZarrCatalog:
    """A catalog without a solver ``/time`` axis: the stamps come from the bounds."""


class _TimeAxisCatalog:
    """A catalog whose store carries the solver ``/time`` axis."""

    def __init__(self, stamps: pd.DatetimeIndex) -> None:
        self._stamps = stamps

    @contextmanager
    def open_zarr(self, sim_id: str):
        class _Store:
            def read_time(inner) -> np.ndarray:
                return self._stamps.to_numpy()

        yield _Store()


class _Run(RunTimeseriesMixin):
    def __init__(self, row: dict, catalog: object | None = None) -> None:
        self._sim_id = "sim"
        self._row = row
        self._catalog = catalog if catalog is not None else _NoZarrCatalog()

    def _load_row(self) -> dict:
        return self._row


def _monthly() -> _Run:
    return _Run(
        {
            "n_timesteps": 36,
            "period_start": "2000-01-01 00:00:00",
            "period_end": "2003-01-01 00:00:00",
            "time_unit": "month",
            "flow_regime": "transient",
        }
    )


def _steady_window() -> _Run:
    # What a steady calibration phase registers: one period over the window.
    return _Run(
        {
            "n_timesteps": 1,
            "period_start": "2000-01-01 00:00:00",
            "period_end": "2003-01-01 00:00:00",
            "time_unit": "day",
            "flow_regime": "steady",
        }
    )


def test_period_edges_open_at_the_stored_start() -> None:
    edges = _monthly().period_edges
    assert list(edges) == list(pd.date_range("2000-01-01", "2003-01-01", freq="MS"))


def test_period_edges_follow_the_solver_time_axis() -> None:
    stamps = pd.date_range("2000-01-02", periods=3, freq="D")
    run = _Run(
        {"n_timesteps": 3, "period_start": "2000-01-01", "period_end": "2000-01-04"},
        _TimeAxisCatalog(stamps),
    )
    assert list(run.period_edges) == list(pd.date_range("2000-01-01", periods=4, freq="D"))
    assert run.step_at("2000-01-02 12:00") == 1


def test_step_at_resolves_a_date_inside_on_and_past_the_edges() -> None:
    run = _monthly()
    assert run.step_at("2002-10-15") == 33
    assert run.step_at("2002-10-01") == 33
    assert run.step_at("2003-01-01") == 35
    assert run.step_at("last") == 35
    assert run.step_at(-2) == 34
    with pytest.raises(TimeSelectionError, match="2000-01-01 to 2003-01-01"):
        run.step_at("2003-02-01")
    with pytest.raises(TimeSelectionError, match="outside the record"):
        run.step_at("1999-12-31")


def test_a_steady_window_resolves_every_date_of_its_record_to_zero() -> None:
    run = _steady_window()
    assert len(run.period_edges) == 2
    for date in ("2000-01-01", "2001-08-15", "2002-12-31", "2003-01-01", "first", "last"):
        assert run.step_at(date) == 0
    assert run.steps_for(period=("2000-06-01", "2002-06-01")) == (0,)


def test_a_run_without_dates_names_its_one_period_only() -> None:
    run = _Run({"n_timesteps": 1, "period_start": None, "flow_regime": "steady"})
    assert run.period_edges is None
    assert run.step_at("last") == 0
    assert run.step_at(0) == 0
    assert run.steps_for() == (0,)
    with pytest.raises(TimeSelectionError, match='this run has no dates; write "last"'):
        run.step_at("2002-10-15")


def test_a_run_without_dates_or_count_holds_one_period() -> None:
    run = _Run({"period_start": float("nan")})
    assert run.period_edges is None
    assert run.step_at("first") == 0


def test_steps_for_times_a_period_or_everything() -> None:
    run = _monthly()
    assert run.steps_for(time=["2002-10-15", "first"]) == (33, 0)
    assert run.steps_for(time="2002-10-15") == (33,)
    assert run.steps_for(period=("2002-10-15", "last")) == (33, 34, 35)
    assert run.steps_for() == tuple(range(36))
    with pytest.raises(ValueError, match="not both"):
        run.steps_for(time="first", period=("first", "last"))
