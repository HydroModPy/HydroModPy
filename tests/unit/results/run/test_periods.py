"""Stress periods of a run: edges, and the steps a date or a window selects.

``periods.edges`` rebuilds the edges from the catalog ``period_start`` and the end stamps of
the run. ``step_at`` and ``steps_for`` read a date through ``core.time.selection``.
"""

from __future__ import annotations

from contextlib import contextmanager

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.run.periods import RunPeriods
from hydromodpy.results.run.timeseries import RunTimeseriesMixin


class NoZarrCatalog:
    """A catalog without a solver ``/time`` axis: the stamps come from the bounds."""


class FakeRun(RunTimeseriesMixin):
    def __init__(self, row):
        self._sim_id = "sim"
        self._row = row
        self._catalog = NoZarrCatalog()
        self.periods = RunPeriods(self)

    def _load_row(self):
        return self._row


def monthly_run():
    return FakeRun(
        {
            "n_timesteps": 36,
            "period_start": "2000-01-01 00:00:00",
            "period_end": "2003-01-01 00:00:00",
            "time_unit": "month",
            "flow_regime": "transient",
        }
    )


def test_period_edges_open_at_the_stored_start():
    edges = monthly_run().periods.edges
    assert list(edges) == list(pd.date_range("2000-01-01", "2003-01-01", freq="MS"))


def test_a_run_without_dates_or_count_holds_one_period():
    run = FakeRun({"period_start": float("nan")})
    assert run.periods.edges is None
    assert run.periods.step_at("first") == 0


def test_steps_for_times_a_period_or_everything():
    run = monthly_run()
    assert run.periods.steps_for(time=["2002-10-15", "first"]) == (33, 0)
    assert run.periods.steps_for(time="2002-10-15") == (33,)
    assert run.periods.steps_for(period=("2002-10-15", "last")) == (33, 34, 35)
    assert run.periods.steps_for() == tuple(range(36))
    with pytest.raises(ValueError, match="not both"):
        run.periods.steps_for(time="first", period=("first", "last"))
