"""A gridded runoff enters the scored discharge as it enters the stored one.

A SIM2 runoff loads as gridded fields, not station points. The run reduces it
to a watershed-mean series (``forcing/runoff/_watershed``) and the derived
catchment discharge adds that series. The calibration metric read only station
points, so it scored the drain baseflow alone against total streamflow while the
stored run reported drain plus runoff.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.calibration.metrics import series as series_module
from hydromodpy.calibration.metrics.series import add_runoff_to_discharge
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
    _add_runoff_to_discharge_series,
)
from hydromodpy.workflow.steps.prepare_solver.prepare import _watershed_mean_series

# 1 mm/day over 86.4 km² is exactly 1 m³/s: 1e-3 * 8.64e7 / 86400.
_CATCH_AREA_KM2 = 86.4
_SIM_INDEX = pd.DatetimeIndex(["2000-01-11", "2000-01-21", "2000-02-20"])


def _gridded_runoff() -> LoadResult:
    """Daily runoff on a 2 x 2 grid whose cells differ by a constant offset.

    The cells hold ``base + (0, 1, 2, 3)`` mm/day, so the watershed mean is
    ``base + 1.5``. ``base`` is 2, 5 and 9 mm/day on the three periods.
    """
    days = pd.date_range("2000-01-01", "2000-03-05", freq="D")
    base = np.where(days < "2000-01-11", 2.0, np.where(days < "2000-01-21", 5.0, 9.0))
    offsets = np.array([[0.0, 1.0], [2.0, 3.0]])
    values = base[:, None, None] + offsets[None, :, :]
    dataset = xr.Dataset(
        {"runoff": (("time", "y", "x"), values)},
        coords={"time": days, "y": [1.5, 0.5], "x": [0.5, 1.5]},
    )
    record = FieldRecord(
        variable="runoff",
        source="sim2",
        unit="mm/day",
        data=dataset,
        bbox=(0.0, 0.0, 2.0, 2.0),
        crs="EPSG:2154",
    )
    return LoadResult(fields=[record])


def _context(runoff: LoadResult) -> SimpleNamespace:
    return SimpleNamespace(
        loaded_data=SimpleNamespace(runoff=runoff),
        setup=SimpleNamespace(geographic=SimpleNamespace(catch_area=_CATCH_AREA_KM2)),
    )


class _Array:
    def __init__(self, data) -> None:
        self._data = np.asarray(data)

    @property
    def shape(self):
        return self._data.shape

    def __getitem__(self, key):
        return self._data[key]


class _Node:
    def __init__(self, mapping) -> None:
        self._mapping = mapping

    def __contains__(self, key) -> bool:
        return key in self._mapping

    def __getitem__(self, key):
        return self._mapping[key]

    def get(self, key):
        return self._mapping.get(key)


class _StationGroup:
    def __init__(self, stations) -> None:
        self._stations = stations

    def array_keys(self):
        return []

    def group_keys(self):
        return list(self._stations)

    def __getitem__(self, key):
        return self._stations[key]


class _AreaConnection:
    def execute(self, sql: str, params):
        return SimpleNamespace(fetchone=lambda: (_CATCH_AREA_KM2,))


def _stored_run(runoff: LoadResult):
    """The fields store a run persists for a gridded runoff, and its catalog."""
    persisted = _watershed_mean_series(runoff)
    station = _Node(
        {
            "values": _Array(persisted.to_numpy(dtype="float64")),
            "timestamps": _Array(pd.DatetimeIndex(persisted.index).values),
        }
    )
    grp = _Node({"forcing": _Node({"runoff": _StationGroup({"_watershed": station})})})
    store = SimpleNamespace(connection=_AreaConnection())
    return store, grp


@pytest.fixture(autouse=True)
def _fresh_warnings(monkeypatch):
    monkeypatch.setattr(series_module, "_RUNOFF_WARNING_EMITTED", set())


def test_a_gridded_runoff_is_added_as_its_watershed_mean() -> None:
    baseflow = pd.Series(0.0, index=_SIM_INDEX, name="discharge")

    scored = add_runoff_to_discharge(baseflow, _context(_gridded_runoff()))

    assert scored.tolist() == pytest.approx([3.5, 6.5, 10.5])


def test_a_gridded_runoff_is_scored_as_the_run_reports_it(caplog) -> None:
    runoff = _gridded_runoff()
    baseflow = pd.Series([0.4, 0.7, 1.1], index=_SIM_INDEX, name="discharge")
    store, grp = _stored_run(runoff)

    with caplog.at_level(logging.WARNING, logger=series_module.__name__):
        scored = add_runoff_to_discharge(baseflow, _context(runoff))
    reported = _add_runoff_to_discharge_series(baseflow, "sim-0", store=store, grp=grp)

    assert scored.tolist() == pytest.approx(reported.tolist())
    assert scored.tolist() == pytest.approx([3.9, 7.2, 11.6])
    assert not [r for r in caplog.records if "no runoff" in r.getMessage()]


def test_a_gauge_scales_the_gridded_runoff_by_the_area_it_drains() -> None:
    baseflow = pd.Series(0.0, index=_SIM_INDEX, name="discharge")

    scored = add_runoff_to_discharge(
        baseflow, _context(_gridded_runoff()), area_m2=_CATCH_AREA_KM2 * 1e6 / 2.0
    )

    assert scored.tolist() == pytest.approx([1.75, 3.25, 5.25])


def test_no_runoff_at_all_still_says_so(caplog) -> None:
    baseflow = pd.Series([0.4, 0.7, 1.1], index=_SIM_INDEX, name="discharge")

    with caplog.at_level(logging.WARNING, logger=series_module.__name__):
        scored = add_runoff_to_discharge(baseflow, _context(LoadResult()))

    assert scored.tolist() == baseflow.tolist()
    (record,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "no runoff data loaded" in record.getMessage()
