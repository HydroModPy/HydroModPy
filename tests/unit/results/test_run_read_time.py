"""``Run.read`` reads the period that holds a date (a stored field, one period per index), and
refuses a time of a kind it does not know.
"""

from __future__ import annotations

import datetime

import numpy as np
import pytest

import hydromodpy as hmp  # noqa: F401  (registers the fields that read() resolves)
from hydromodpy.results.catalog.facade import Catalog
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
def test_read_at_a_date(run, time) -> None:
    np.testing.assert_allclose(np.ravel(run.read("head", time=time)), [3.0, 4.0])
    assert run.periods.asked


def test_read_at_an_index(run) -> None:
    np.testing.assert_allclose(np.ravel(run.read("head", time=np.int64(0))), [1.0, 2.0])
    assert not run.periods.asked


@pytest.mark.parametrize("time", [1.5, True, slice("2000", "2001")])
def test_read_refuses_a_time_kind(run, time) -> None:
    with pytest.raises(TypeError):
        run.read("head", time=time)
