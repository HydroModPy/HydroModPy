"""Unit tests for catchment_aggregation: reductions, runoff merge, area read."""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
    _CATCHMENT_STATION,
    _add_runoff_to_discharge_series,
    _aggregate_variable,
    _build_active_mask,
    _detect_n_timesteps,
    _read_catchment_area_m2,
    _reduce,
    _resolve_time_index,
    aggregate_catchment_timeseries,
)
from tests._helpers.fixtures_catalog import simulation_catalog


class TestReduce:
    def test_mean_default_respects_mask(self):
        # Masked-out cells carry outlier values that must NOT affect the mean.
        field = np.array([10.0, 1000.0, 20.0, -999.0, 30.0])
        mask = np.array([True, False, True, False, True])
        # Active cells: 10, 20, 30 -> mean = 20.
        assert _reduce(field, mask, "unknown_reducer_defaults_to_mean") == pytest.approx(20.0)

    def test_mean_active_respects_mask(self):
        field = np.array([2.0, 1.0e9, 4.0, 6.0])
        mask = np.array([True, False, True, True])
        # Active cells 2, 4, 6 -> mean 4.0; masked huge value ignored.
        assert _reduce(field, mask, "mean_active") == pytest.approx(4.0)

    def test_sum_respects_mask(self):
        field = np.array([5.0, 100.0, 7.0, 200.0])
        mask = np.array([True, False, True, False])
        # Only active cells 5 + 7 = 12.
        assert _reduce(field, mask, "sum") == pytest.approx(12.0)

    def test_abs_sum_uses_absolute_value_and_mask(self):
        # Drain fluxes are signed; discharge spec sums absolute values.
        field = np.array([-3.0, -1000.0, 4.0, 9999.0])
        mask = np.array([True, False, True, False])
        # |−3| + |4| = 7; masked cells excluded.
        assert _reduce(field, mask, "abs_sum") == pytest.approx(7.0)

    def test_max_respects_mask(self):
        field = np.array([1.0, 1.0e9, 5.0, 3.0])
        mask = np.array([True, False, True, True])
        # Masked 1e9 ignored; max over {1, 5, 3} = 5.
        assert _reduce(field, mask, "max") == pytest.approx(5.0)

    def test_percent_positive(self):
        field = np.array([1.0, -2.0, 3.0, -4.0])
        mask = np.array([True, True, True, True])
        # 2 of 4 valid cells are positive -> 50 percent.
        assert _reduce(field, mask, "percent_positive") == pytest.approx(50.0)

    def test_no_mask_falls_back_to_sentinel_filter(self):
        # Without a mask, values <= -9000 are treated as no-data.
        field = np.array([10.0, -9999.0, 30.0])
        assert _reduce(field, None, "sum") == pytest.approx(40.0)

    def test_mask_size_mismatch_falls_back_to_sentinel(self):
        # A mask whose size differs from the field is ignored; sentinel rule applies.
        field = np.array([10.0, 20.0, -9999.0])
        wrong_mask = np.array([True, False])
        assert _reduce(field, wrong_mask, "sum") == pytest.approx(30.0)

    def test_all_invalid_returns_nan(self):
        field = np.array([-9999.0, -9999.0])
        assert np.isnan(_reduce(field, None, "sum"))

    def test_2d_sum_flattens_layers_by_summation(self):
        # Two layers, three cells; sum reducer adds layers then sums cells.
        field = np.array([[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]])
        # Column sums: 11, 22, 33; total = 66.
        assert _reduce(field, None, "sum") == pytest.approx(66.0)

    def test_2d_mean_picks_first_layer(self):
        # Non sum/abs_sum reducers collapse a 2D field to its first layer.
        field = np.array([[2.0, 4.0, 6.0], [100.0, 200.0, 300.0]])
        # First layer mean = (2+4+6)/3 = 4.
        assert _reduce(field, None, "mean_active") == pytest.approx(4.0)


class _FakeArray:
    """Minimal Zarr-array stand-in supporting slice reads and ``.shape``."""

    def __init__(self, data):
        self._data = np.asarray(data)

    @property
    def shape(self):
        return self._data.shape

    def __getitem__(self, key):
        return self._data[key]


class _FakeNode:
    """Dict-like Zarr group node without a ``shape`` attribute."""

    def __init__(self, mapping):
        self._mapping = mapping

    def __contains__(self, key):
        return key in self._mapping

    def __getitem__(self, key):
        return self._mapping[key]


class _FakeRunoffGroup:
    def __init__(self, stations):
        # stations: dict[str, _FakeNode]
        self._stations = stations

    def array_keys(self):
        return []

    def group_keys(self):
        return list(self._stations.keys())

    def __getitem__(self, key):
        return self._stations[key]


class _FakeRootGroup:
    def __init__(self, forcing):
        self._forcing = forcing

    def get(self, key):
        if key == "forcing":
            return self._forcing
        return None


def _make_grp_with_runoff(values, timestamps):
    station = _FakeNode(
        {
            "values": _FakeArray(np.asarray(values, dtype="float64")),
            "timestamps": _FakeArray(np.asarray(timestamps)),
        }
    )
    runoff = _FakeRunoffGroup({"station0": station})
    forcing = _FakeNode({"runoff": runoff})
    return _FakeRootGroup(forcing)


class _AreaStub:
    """Store stub exposing only the catchment area used by the runoff merge."""

    def __init__(self, area_m2):
        self._area_m2 = area_m2


def _patch_area(monkeypatch, area_m2):
    import hydromodpy.simulation.extraction.derivation.catchment_aggregation as mod

    monkeypatch.setattr(mod, "_read_catchment_area_m2", lambda store, sim_id: area_m2)


class TestAddRunoffToDischarge:
    def test_no_runoff_forcing_returns_unchanged(self):
        # grp.get("forcing") is None -> baseflow passed through untouched.
        idx = pd.date_range("2020-01-01", periods=3, freq="D")
        discharge = pd.Series([1.0, 2.0, 3.0], index=idx, name="discharge")
        grp = _FakeRootGroup(forcing=None)

        out = _add_runoff_to_discharge_series(discharge, str(uuid4()), store=None, grp=grp)

        pd.testing.assert_series_equal(out, discharge)

    def test_runoff_added_in_m3_per_s_on_aligned_timestamps(self, monkeypatch):
        # Area chosen so the unit conversion gives a round number.
        # runoff_m3s = mm_per_day * 1e-3 * area_m2 / 86400.
        # With area = 86_400_000 m2: mm_per_day=1 -> 1e-3 * 8.64e7 / 8.64e4 = 1.0 m3/s.
        area_m2 = 86_400_000.0
        _patch_area(monkeypatch, area_m2)

        idx = pd.date_range("2020-01-01", periods=3, freq="D")
        discharge = pd.Series([10.0, 20.0, 30.0], index=idx, name="discharge")
        # 1 mm/day everywhere -> exactly 1.0 m3/s added per step.
        grp = _make_grp_with_runoff(values=[1.0, 1.0, 1.0], timestamps=idx.values)

        out = _add_runoff_to_discharge_series(discharge, str(uuid4()), store=None, grp=grp)

        assert list(out.index) == list(idx)
        np.testing.assert_allclose(out.values, [11.0, 21.0, 31.0])

    def test_runoff_conversion_scales_with_magnitude(self, monkeypatch):
        # Doubling the area doubles the m3/s contribution: linear in area.
        area_m2 = 2.0 * 86_400_000.0
        _patch_area(monkeypatch, area_m2)

        idx = pd.date_range("2021-06-01", periods=2, freq="D")
        discharge = pd.Series([0.0, 0.0], index=idx, name="discharge")
        grp = _make_grp_with_runoff(values=[1.0, 3.0], timestamps=idx.values)

        out = _add_runoff_to_discharge_series(discharge, str(uuid4()), store=None, grp=grp)

        # 1 mm/day -> 2.0 m3/s, 3 mm/day -> 6.0 m3/s (area doubled).
        np.testing.assert_allclose(out.values, [2.0, 6.0])

    def test_zero_area_skips_runoff_addition(self, monkeypatch):
        _patch_area(monkeypatch, 0.0)

        idx = pd.date_range("2020-01-01", periods=2, freq="D")
        discharge = pd.Series([5.0, 7.0], index=idx, name="discharge")
        grp = _make_grp_with_runoff(values=[10.0, 10.0], timestamps=idx.values)

        out = _add_runoff_to_discharge_series(discharge, str(uuid4()), store=None, grp=grp)

        pd.testing.assert_series_equal(out, discharge)

    def test_nearest_alignment_when_runoff_index_offset(self, monkeypatch):
        # Runoff timestamps differ slightly; reindex(method="nearest") maps them.
        area_m2 = 86_400_000.0
        _patch_area(monkeypatch, area_m2)

        target = pd.date_range("2020-01-01", periods=3, freq="D")
        discharge = pd.Series([0.0, 0.0, 0.0], index=target, name="discharge")
        # Runoff stamped a few hours off the daily grid but nearest to each day.
        runoff_idx = target + pd.Timedelta(hours=2)
        grp = _make_grp_with_runoff(values=[1.0, 2.0, 4.0], timestamps=runoff_idx.values)

        out = _add_runoff_to_discharge_series(discharge, str(uuid4()), store=None, grp=grp)

        assert list(out.index) == list(target)
        np.testing.assert_allclose(out.values, [1.0, 2.0, 4.0])


class _DictGroup:
    """Generic dict-backed Zarr group: supports get/in/getitem/iter/keys."""

    def __init__(self, mapping):
        self._mapping = dict(mapping)

    def get(self, key):
        return self._mapping.get(key)

    def __contains__(self, key):
        return key in self._mapping

    def __getitem__(self, key):
        return self._mapping[key]

    def __iter__(self):
        return iter(self._mapping)


class TestDetectNTimesteps:
    def test_uses_head_shape_first(self):
        # head with 5 timesteps takes precedence over derived arrays.
        grp = _DictGroup(
            {
                "head": _FakeArray(np.zeros((5, 3))),
                "derived": _DictGroup({"watertable": _FakeArray(np.zeros((2, 3)))}),
            }
        )
        assert _detect_n_timesteps(grp) == 5

    def test_falls_back_to_first_derived_array(self):
        grp = _DictGroup({"derived": _DictGroup({"watertable": _FakeArray(np.zeros((4, 3)))})})
        assert _detect_n_timesteps(grp) == 4

    def test_returns_zero_when_nothing_present(self):
        assert _detect_n_timesteps(_DictGroup({})) == 0


class TestBuildActiveMask:
    def test_no_mesh_returns_none(self):
        assert _build_active_mask(_DictGroup({})) is None

    def test_mesh_without_topography_returns_none(self):
        grp = _DictGroup({"mesh": _DictGroup({})})
        assert _build_active_mask(grp) is None

    def test_topography_marks_finite_above_sentinel(self):
        # -9999 and NaN cells are inactive; finite cells above -9000 are active.
        topo = np.array([10.0, -9999.0, 5.0, np.nan, 0.0])
        grp = _DictGroup({"mesh": _DictGroup({"topography": _FakeArray(topo)})})
        mask = _build_active_mask(grp)
        np.testing.assert_array_equal(mask, [True, False, True, False, True])


class TestAggregateVariable:
    def _grp_with_root_field(self, name, frames):
        # frames: array shaped (n_ts, n_cells); stored at root under *name*.
        return _DictGroup({name: _FakeArray(np.asarray(frames, dtype="float64"))})

    def test_resolves_root_alternative_and_abs_sum(self):
        # store_var "drains|drn|drain" must resolve to the "drn" root array.
        frames = np.array([[-1.0, 2.0, -3.0], [4.0, -5.0, 6.0]])  # 2 timesteps
        grp = self._grp_with_root_field("drn", frames)
        out = _aggregate_variable(
            store=None,
            sim_id="s",
            grp=grp,
            store_var="drains|drn|drain",
            n_timesteps=2,
            active_mask=None,
            reducer="abs_sum",
        )
        # abs sums per timestep: 1+2+3=6 ; 4+5+6=15.
        assert out == pytest.approx([6.0, 15.0])

    def test_prefers_derived_over_root(self):
        # Same key present in derived/ and root; derived wins.
        derived = _DictGroup({"flux": _FakeArray(np.array([[10.0, 10.0]]))})
        grp = _DictGroup({"derived": derived, "flux": _FakeArray(np.array([[1.0, 1.0]]))})
        out = _aggregate_variable(None, "s", grp, "flux", 1, None, "sum")
        assert out == pytest.approx([20.0])

    def test_missing_variable_returns_none(self):
        grp = _DictGroup({"head": _FakeArray(np.zeros((1, 3)))})
        out = _aggregate_variable(None, "s", grp, "wells|wel", 1, None, "sum")
        assert out is None

    def test_mask_excludes_inactive_cells(self):
        frames = np.array([[1.0, 999.0, 2.0]])
        grp = self._grp_with_root_field("drn", frames)
        mask = np.array([True, False, True])
        out = _aggregate_variable(None, "s", grp, "drn", 1, mask, "sum")
        # Masked middle cell ignored: 1 + 2 = 3.
        assert out == pytest.approx([3.0])


@pytest.fixture
def catalog(tmp_path):
    with simulation_catalog(tmp_path / "workspace") as cat:
        yield cat


class TestResolveTimeIndex:
    def test_builds_range_from_period_bounds(self, catalog):
        sid = str(uuid4())
        reg = catalog.register_simulation(
            sid,
            project="test",
            solver="modflow_nwt",
            n_cells=3,
            n_layers=1,
            n_timesteps=4,
            period_start="2020-01-01",
            period_end="2020-01-04",
        )
        if reg.zarr is not None:
            reg.zarr.close()
        idx = _resolve_time_index(catalog, sid, 4)
        assert isinstance(idx, pd.DatetimeIndex)
        assert len(idx) == 4
        # tz may be applied by the backend; compare on the calendar date.
        idx_naive = idx.tz_localize(None) if idx.tz is not None else idx
        assert idx_naive[0].date().isoformat() == "2020-01-01"
        assert idx_naive[-1].date().isoformat() == "2020-01-04"
        # date_range with periods=n must produce a strictly increasing index.
        assert idx.is_monotonic_increasing

    def test_missing_period_raises(self, catalog):
        sid = str(uuid4())
        reg = catalog.register_simulation(
            sid,
            project="test",
            solver="modflow_nwt",
            n_cells=3,
            n_layers=1,
            n_timesteps=2,
        )
        if reg.zarr is not None:
            reg.zarr.close()
        with pytest.raises(RuntimeError, match="period_start"):
            _resolve_time_index(catalog, sid, 2)


class TestAggregateEndToEnd:
    def _setup_sim(self, catalog, n_ts=3, n_cells=4):
        sid = str(uuid4())
        reg = catalog.register_simulation(
            sid,
            project="test",
            solver="modflow_nwt",
            n_cells=n_cells,
            n_layers=1,
            n_timesteps=n_ts,
            period_start="2020-01-01",
            period_end="2020-01-03",
        )
        if reg.zarr is not None:
            reg.zarr.close()
        # head drives _detect_n_timesteps.
        for t in range(n_ts):
            catalog.write_field(
                sid, "head", t, np.full((1, n_cells), 5.0), n_timesteps=n_ts if t == 0 else None
            )
        return sid

    def test_writes_discharge_timeseries_from_drain_field(self, catalog):
        n_ts, n_cells = 3, 4
        sid = self._setup_sim(catalog, n_ts=n_ts, n_cells=n_cells)
        # Signed drain fluxes per timestep; discharge = abs_sum over cells.
        drain_frames = {
            0: np.array([[-1.0, -2.0, -3.0, -4.0]]),  # abs_sum = 10
            1: np.array([[-2.0, -2.0, -2.0, -2.0]]),  # abs_sum = 8
            2: np.array([[1.0, 1.0, 1.0, 1.0]]),  # abs_sum = 4
        }
        for t in range(n_ts):
            catalog.write_field(
                sid, "drn", t, drain_frames[t], n_timesteps=n_ts if t == 0 else None
            )

        aggregate_catchment_timeseries(sid, catalog)

        ts = catalog.query_timeseries(sid, _CATCHMENT_STATION, "discharge")
        assert len(ts) == n_ts
        np.testing.assert_allclose(sorted(ts.values), [4.0, 8.0, 10.0])
        # Unit must be persisted as m3/s.
        unit_row = catalog.connection.execute(
            "SELECT DISTINCT unit FROM timeseries WHERE sim_id = ? AND variable = 'discharge'",
            [sid],
        ).fetchone()
        assert unit_row[0] == "m3/s"

    def test_no_aggregable_field_writes_nothing(self, catalog):
        # head exists (so n_timesteps>0) but no drain/well field -> no output.
        sid = self._setup_sim(catalog)
        aggregate_catchment_timeseries(sid, catalog)
        with pytest.raises(KeyError):
            catalog.query_timeseries(sid, _CATCHMENT_STATION, "discharge")


class TestReadCatchmentArea:
    def _register(self, catalog):
        sid = str(uuid4())
        reg = catalog.register_simulation(
            sid,
            project="test",
            solver="modflow_nwt",
            n_cells=4,
            n_layers=1,
            n_timesteps=2,
        )
        if reg.zarr is not None:
            reg.zarr.close()
        return sid

    def test_returns_stored_area_converted_to_m2(self, catalog):
        sid = self._register(catalog)
        # catch_area is stored in km2; the reader converts to m2 (factor 1e6).
        catalog.write_geographic_metadata(sid, {"catch_area": 12.5})

        area_m2 = _read_catchment_area_m2(catalog, sid)

        assert area_m2 == pytest.approx(12.5 * 1e6)

    def test_returns_zero_when_area_absent(self, catalog):
        sid = self._register(catalog)
        # No catch_area row written for this sim.
        assert _read_catchment_area_m2(catalog, sid) == 0.0

    def test_reads_via_connection_property(self, catalog):
        sid = self._register(catalog)
        catalog.write_geographic_metadata(sid, {"catch_area": 1.0})
        # _read_catchment_area_m2 uses store.connection first; confirm it works.
        assert catalog.connection is not None
        assert _read_catchment_area_m2(catalog, sid) == pytest.approx(1.0e6)
