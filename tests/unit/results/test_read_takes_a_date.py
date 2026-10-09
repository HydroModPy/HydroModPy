"""``hmp.read`` reads the period that holds a date, and refuses what it cannot.

A date used to be ignored without a word, and every period came back.
"""

from __future__ import annotations

import datetime
import uuid

import numpy as np
import pytest

import hydromodpy as hmp
from tests._helpers.fixtures_catalog import simulation_catalog


class _Periods:
    def __init__(self) -> None:
        self.asked: list[object] = []

    def step_at(self, time):
        self.asked.append(time)
        return 1


@pytest.fixture
def run(tmp_path):
    with simulation_catalog(tmp_path / "ws") as cat:
        sid = str(uuid.uuid4())
        reg = cat.register_simulation(
            sid, project="p", solver="modflow6", n_cells=2, n_layers=1, n_timesteps=2
        )
        reg.zarr.close()
        cat.write_field(sid, "head", 0, np.array([[1.0, 2.0]]), n_timesteps=2)
        cat.write_field(sid, "head", 1, np.array([[3.0, 4.0]]), n_timesteps=2)
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
