"""Tests for the shared solver time-axis reuse.

The derived/aggregated timeseries (e.g. the catchment discharge) must share the
solver's persisted CF ``/time`` axis instead of re-deriving a drifting
``date_range(..., periods=n)``. These tests cover the decode, the shared
``solver_time_index`` helper, and the catchment aggregation wiring.
"""

from __future__ import annotations

from contextlib import contextmanager

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
    def test_seconds_since_epoch(self):
        # 2019-01-02 00:00:00Z and +1 day, as integer seconds since 1970.
        base = int(pd.Timestamp("2019-01-02", tz="UTC").timestamp())
        obj = _zarr_with_time([base, base + 86400, base + 2 * 86400])
        out = obj.read_time()
        idx = pd.DatetimeIndex(out)
        assert list(idx.strftime("%Y-%m-%d %H:%M:%S")) == [
            "2019-01-02 00:00:00",
            "2019-01-03 00:00:00",
            "2019-01-04 00:00:00",
        ]
        # Exact daily cadence, no drift.
        assert set(idx.to_series().diff().dropna().dt.total_seconds()) == {86400.0}

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
    def test_returns_axis_when_length_matches(self):
        cat = _FakeCatalog(_SzWithTime(_axis(5)))
        idx = solver_time_index(cat, "sim", 5)
        assert isinstance(idx, pd.DatetimeIndex)
        assert len(idx) == 5
        assert set(idx.to_series().diff().dropna().dt.total_seconds()) == {86400.0}

    def test_none_on_length_mismatch(self):
        cat = _FakeCatalog(_SzWithTime(_axis(4)))
        assert solver_time_index(cat, "sim", 5) is None

    def test_none_when_axis_missing(self):
        cat = _FakeCatalog(_SzWithTime(None))
        assert solver_time_index(cat, "sim", 5) is None

    def test_none_when_no_open_zarr(self):
        assert solver_time_index(object(), "sim", 5) is None

    def test_none_on_open_error(self):
        cat = _FakeCatalog(_SzWithTime(_axis(5)), boom=True)
        assert solver_time_index(cat, "sim", 5) is None


# ---------------------------------------------------------------------------
# Catchment aggregation wiring (prefer solver axis over date_range)
# ---------------------------------------------------------------------------


class _Conn:
    def __init__(self, row):
        self._row = row

    def execute(self, *_a, **_k):
        return self

    def fetchone(self):
        return self._row


class _Store:
    def __init__(self, sz, row):
        self._sz = sz
        self.connection = _Conn(row)

    @contextmanager
    def open_zarr(self, sim_id):
        del sim_id
        yield self._sz


class TestCatchmentResolveTimeIndex:
    def test_prefers_solver_axis(self):
        from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
            _resolve_time_index,
        )

        store = _Store(_SzWithTime(_axis(5)), row=("2019-01-01", "2019-12-31", "DAYS"))
        idx = _resolve_time_index(store, "sim", 5)
        # Solver axis (clean 86400s), not the drifting date_range over the window.
        assert set(idx.to_series().diff().dropna().dt.total_seconds()) == {86400.0}

    def test_falls_back_to_period_bounds_when_axis_absent(self):
        from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
            _resolve_time_index,
        )

        # The window end is exclusive and each period is stamped at its end,
        # as the solvers write it. The fallback used to put the first stamp on
        # the window start.
        store = _Store(_SzWithTime(None), row=("2019-01-01", "2019-01-06", "day"))
        idx = _resolve_time_index(store, "sim", 5)
        assert len(idx) == 5
        assert idx[0] == pd.Timestamp("2019-01-02")
        assert idx[-1] == pd.Timestamp("2019-01-06")

    def test_raises_when_no_axis_and_no_period(self):
        from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
            _resolve_time_index,
        )

        store = _Store(_SzWithTime(None), row=(None, None, None))
        with pytest.raises(RuntimeError, match="period_start/period_end"):
            _resolve_time_index(store, "sim", 5)


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
    def test_monthly_fallback_stamps_each_month_end(self):
        from hydromodpy.results.derive.views import _time_index

        # Nancon window: 36 monthly periods over [2000-01-01, 2003-01-01).
        # Each stamp is the end of its month, at midnight. The old
        # date_range(start, end, periods=n) put n points on n-1 intervals and
        # drifted by hours from the second stamp on.
        run = _RunWithoutAxis(
            {"period_start": "2000-01-01", "period_end": "2003-01-01", "time_unit": "month"}
        )
        idx = _time_index(run, 36)
        expected = pd.date_range("2000-02-01", "2003-01-01", freq="MS")
        assert list(idx) == list(expected)

    def test_daily_fallback_stamps_each_day_end(self):
        from hydromodpy.results.derive.views import _time_index

        run = _RunWithoutAxis(
            {"period_start": "2019-01-01", "period_end": "2019-01-06", "time_unit": "day"}
        )
        idx = _time_index(run, 5)
        assert list(idx) == list(pd.date_range("2019-01-02", "2019-01-06", freq="D"))

    def test_catchment_mean_uses_the_fallback(self, monkeypatch):
        from hydromodpy.results.derive import views

        stack = np.arange(12, dtype=float).reshape(3, 4)
        monkeypatch.setattr(views, "_catchment_mask", lambda sim: None)
        monkeypatch.setattr(views, "_stack_field", lambda sim, variable: stack)
        run = _RunWithoutAxis(
            {"period_start": "2000-01-01", "period_end": "2000-04-01", "time_unit": "month"}
        )
        series = views.catchment_mean(run, "watertable_depth")
        assert list(series.index) == [
            pd.Timestamp("2000-02-01"),
            pd.Timestamp("2000-03-01"),
            pd.Timestamp("2000-04-01"),
        ]
        assert series.tolist() == [1.5, 5.5, 9.5]

    def test_raises_without_axis_and_bounds(self):
        from hydromodpy.results.derive.views import _time_index

        run = _RunWithoutAxis({"period_start": None, "period_end": None})
        with pytest.raises(RuntimeError, match="no /time axis"):
            _time_index(run, 3)
