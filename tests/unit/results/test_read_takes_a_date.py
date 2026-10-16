"""``hmp.read`` reads the period that holds a date, and refuses what it cannot.

A date used to be ignored without a word, and every period came back.
"""

from __future__ import annotations

import datetime

import numpy as np
import pytest

import hydromodpy as hmp
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store


class _Periods:
    def __init__(self) -> None:
        self.asked: list[object] = []

    def step_at(self, time):
        self.asked.append(time)
        return 1


@pytest.fixture
def run(tmp_path):
    project = tmp_path / "ws"
    store = open_run_store(project, "run", n_cells=2, n_layers=1, n_timesteps=2)
    sid = store.sim_id
    store.write_field(sid, "head", 0, np.array([[1.0, 2.0]]), n_timesteps=2)
    store.write_field(sid, "head", 1, np.array([[3.0, 4.0]]), n_timesteps=2)
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as cat:
        run = cat[sid]
        run.periods = _Periods()
        yield run


@pytest.mark.parametrize(
    "time", ["2002-10-15", datetime.date(2002, 10, 15), np.datetime64("2002-10-15"), "last"]
)
def test_a_date_reads_its_period(run, time) -> None:
    np.testing.assert_allclose(np.ravel(hmp.read(run, "head", time=time)), [3.0, 4.0])
    assert run.periods.asked


def test_an_integer_still_reads_its_index(run) -> None:
    np.testing.assert_allclose(np.ravel(hmp.read(run, "head", time=np.int64(0))), [1.0, 2.0])
    assert not run.periods.asked


@pytest.mark.parametrize("time", [1.5, True, slice("2000", "2001")])
def test_an_unknown_time_kind_is_refused(run, time) -> None:
    with pytest.raises(TypeError):
        hmp.read(run, "head", time=time)
