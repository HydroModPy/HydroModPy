"""Tests for the shared solver time-axis reuse.

The derived/aggregated timeseries (e.g. the catchment discharge) must share the
solver's persisted CF ``/time`` axis instead of re-deriving a drifting
``date_range(..., periods=n)``. These tests cover the decode, the shared
``solver_time_index`` helper, and the catchment aggregation wiring.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.derive.time_alignment import solver_time_index
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr

# ---------------------------------------------------------------------------
# SimulationZarr.read_time decode (duck-typed self: only touches self._root)
# ---------------------------------------------------------------------------


class _FakeArr:
    def __init__(self, values, attrs):
        self._v = np.asarray(values)
        self.attrs = dict(attrs)

    def __getitem__(self, key):
        return self._v[key]


class _FakeRoot(dict):
    pass


def _zarr_with_time(values, units="seconds since 1970-01-01"):
    obj = object.__new__(SimulationZarr)
    obj._root = _FakeRoot({"time": _FakeArr(values, {"units": units})})
    return obj


class TestReadTimeDecode:
    def test_days_units(self):
        obj = _zarr_with_time([0, 1, 2], units="days since 1970-01-01")
        idx = pd.DatetimeIndex(obj.read_time())
        assert list(idx.strftime("%Y-%m-%d")) == ["1970-01-01", "1970-01-02", "1970-01-03"]

    def test_missing_or_empty_returns_none(self):
        empty = object.__new__(SimulationZarr)
        empty._root = _FakeRoot()
        assert empty.read_time() is None
        zero = _zarr_with_time([])
        assert zero.read_time() is None


# ---------------------------------------------------------------------------
# solver_time_index helper
# ---------------------------------------------------------------------------


class _FakeCatalog:
    """Catalog double exposing open_zarr as a context manager."""

    def __init__(self, sz, *, boom: bool = False):
        self._sz = sz
        self._boom = boom

    @contextmanager
    def open_zarr(self, sim_id):
        del sim_id
        if self._boom:
            raise RuntimeError("zarr open failed")
        yield self._sz


class _SzWithTime:
    def __init__(self, times):
        self._times = times

    def read_time(self):
        return self._times


def _axis(n):
    base = np.datetime64("2019-01-02T00:00:00")
    return np.array([base + np.timedelta64(k, "D") for k in range(n)])


class TestSolverTimeIndex:
    def test_none_on_open_error(self):
        cat = _FakeCatalog(_SzWithTime(_axis(5)), boom=True)
        assert solver_time_index(cat, "sim", 5) is None


# ---------------------------------------------------------------------------
# Catchment aggregation wiring (prefer solver axis over date_range)
# ---------------------------------------------------------------------------


class _Store:
    """A run store reduced to its field store and the period its facts record."""

    def __init__(self, sz, window):
        self._sz = sz
        start, end, unit = window
        self.facts = SimpleNamespace(period_start=start, period_end=end, time_unit=unit)

    @contextmanager
    def open_zarr(self, sim_id):
        del sim_id
        yield self._sz


class TestCatchmentResolveTimeIndex:
    def test_raises_when_no_axis_and_no_period(self):
        from hydromodpy.results.derive.catchment_aggregation import series_time_index

        store = _Store(_SzWithTime(None), window=(None, None, None))
        with pytest.raises(RuntimeError, match="period_start/period_end"):
            series_time_index(store, "sim", 5)


# ---------------------------------------------------------------------------
# Derived catchment views (results.derive.views) share the same fallback
# ---------------------------------------------------------------------------


class _RunWithoutAxis:
    """Run double with no solver /time axis, only catalog period bounds."""

    def __init__(self, row):
        self._catalog = object()
        self._sim_id = "sim"
        self._row = row

    def _load_row(self):
        return self._row


class TestDerivedViewTimeIndex:
    def test_daily_fallback_stamps_each_day_end(self):
        from hydromodpy.results.derive.views import _time_index

        run = _RunWithoutAxis(
            {"period_start": "2019-01-01", "period_end": "2019-01-06", "time_unit": "day"}
        )
        idx = _time_index(run, 5)
        assert list(idx) == list(pd.date_range("2019-01-02", "2019-01-06", freq="D"))

    def test_raises_without_axis_and_bounds(self):
        from hydromodpy.results.derive.views import _time_index

        run = _RunWithoutAxis({"period_start": None, "period_end": None})
        with pytest.raises(RuntimeError, match="no /time axis"):
            _time_index(run, 3)
