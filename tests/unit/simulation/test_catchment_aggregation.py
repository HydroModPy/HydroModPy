"""Unit tests for catchment_aggregation: reductions, runoff merge, area read."""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import ExtractError
from hydromodpy.core.scope import CATCHMENT
from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
    _add_runoff_to_discharge_series,
    _aggregate_from_lumped_budget,
    _aggregate_variable,
    _build_active_mask,
    _catchment_fraction,
    _detect_n_timesteps,
    _read_catchment_area_m2,
    _reduce,
    _resolve_time_index,
    aggregate_catchment_timeseries,
)

from ._test_simulation_api_builders import runs

__all__ = ["runs"]


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

    def test_outflow_sum_counts_what_leaves_and_keeps_the_mask(self):
        # Budget fluxes are negative when water leaves; what enters is no outflow.
        field = np.array([-3.0, -1000.0, 4.0, 9999.0])
        mask = np.array([True, False, True, False])
        assert _reduce(field, mask, "outflow_sum") == pytest.approx(3.0)

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
        # Non sum/outflow_sum reducers collapse a 2D field to its first layer.
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
        return [key for key, node in self._stations.items() if isinstance(node, _FakeArray)]

    def group_keys(self):
        return [key for key, node in self._stations.items() if isinstance(node, _FakeNode)]

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


def _with_mesh(get, *, area_m2, rule):
    """Wrap a fake group's ``get`` so ``mesh`` holds a stored basin of D."""
    import zarr

    mesh = zarr.group().require_group("mesh")
    node = mesh.create_array("descent_basin", data=np.ones(4, dtype=bool))
    node.attrs["basin_rule"] = rule
    node.attrs["basin_area_m2"] = area_m2

    def wrapped(key):
        return mesh if key == "mesh" else get(key)

    return wrapped


class _SeriesStore:
    """The ``timeseries`` table of a run, with a gauge or without one."""

    def __init__(self, *, gauged: bool) -> None:
        self._rows = pd.DataFrame(
            {"variable": ["discharge"], "source": ["observed" if gauged else "simulated"]}
        )

    def read_table(self, view_name):
        assert view_name == "timeseries"
        return self._rows


class TestAddRunoffToDischarge:
    def test_no_runoff_forcing_returns_unchanged_and_says_nothing_without_a_gauge(self, caplog):
        # grp.get("forcing") is None -> baseflow passed through untouched.
        idx = pd.date_range("2020-01-01", periods=3, freq="D")
        discharge = pd.Series([1.0, 2.0, 3.0], index=idx, name="discharge")
        grp = _FakeRootGroup(forcing=None)

        with caplog.at_level("WARNING"):
            out = _add_runoff_to_discharge_series(
                discharge, str(uuid4()), store=_SeriesStore(gauged=False), grp=grp
            )

        pd.testing.assert_series_equal(out, discharge)
        assert not [r for r in caplog.records if "baseflow" in r.getMessage()]

    def test_no_runoff_forcing_warns_once_per_run_in_plain_words(self, caplog):
        idx = pd.date_range("2020-01-01", periods=2, freq="D")
        discharge = pd.Series([1.0, 2.0], index=idx, name="discharge")
        sim_id = str(uuid4())
        with caplog.at_level("WARNING"):
            for _ in range(3):
                _add_runoff_to_discharge_series(
                    discharge,
                    sim_id,
                    store=_SeriesStore(gauged=True),
                    grp=_FakeRootGroup(forcing=None),
                )
        (message,) = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert message == (
            "Simulated discharge is baseflow only: the run has no runoff forcing, "
            "so it underestimates a gauged total streamflow."
        )
        assert sim_id not in message
        assert "—" not in message

    def test_runoff_added_in_m3_per_s_on_aligned_timestamps(self, monkeypatch):
        # Area chosen so the unit conversion gives a round number.
        # runoff_m3s = mm_per_day * 1e-3 * area_m2 / 86400.
        # With area = 86_400_000 m2: mm_per_day=1 -> 1e-3 * 8.64e7 / 8.64e4 = 1.0 m3/s.
        area_m2 = 86_400_000.0
        _patch_area(monkeypatch, area_m2)

        idx = pd.date_range("2020-01-01", periods=3, freq="D")
        discharge = pd.Series([10.0, 20.0, 30.0], index=idx, name="discharge")
        # 1 mm/day everywhere -> exactly 1.0 m3/s added per step. A run stamps
        # each day at its end, a daily forcing at its start, so the forcing
        # sits one day before each stamp.
        runoff_idx = pd.date_range("2019-12-31", periods=3, freq="D")
        grp = _make_grp_with_runoff(values=[1.0, 1.0, 1.0], timestamps=runoff_idx.values)

        out = _add_runoff_to_discharge_series(discharge, str(uuid4()), store=None, grp=grp)

        assert list(out.index) == list(idx)
        np.testing.assert_allclose(out.values, [11.0, 21.0, 31.0])

    def test_runoff_conversion_scales_with_magnitude(self, monkeypatch):
        # Doubling the area doubles the m3/s contribution: linear in area.
        area_m2 = 2.0 * 86_400_000.0
        _patch_area(monkeypatch, area_m2)

        idx = pd.date_range("2021-06-01", periods=2, freq="D")
        discharge = pd.Series([0.0, 0.0], index=idx, name="discharge")
        # Each daily forcing is stamped at the start of the day a stamp closes.
        runoff_idx = pd.date_range("2021-05-31", periods=2, freq="D")
        grp = _make_grp_with_runoff(values=[1.0, 3.0], timestamps=runoff_idx.values)

        out = _add_runoff_to_discharge_series(discharge, str(uuid4()), store=None, grp=grp)

        # 1 mm/day -> 2.0 m3/s, 3 mm/day -> 6.0 m3/s (area doubled).
        np.testing.assert_allclose(out.values, [2.0, 6.0])

    @pytest.mark.parametrize(
        ("area_m2", "expected"),
        [(0.0, [5.0, 7.0]), (0.5, [5.0 + 10.0e-3 * 0.5 / 86400.0, 7.0 + 10.0e-3 * 0.5 / 86400.0])],
    )
    def test_zero_area_skips_runoff_addition(self, monkeypatch, caplog, area_m2, expected):
        _patch_area(monkeypatch, area_m2)

        idx = pd.date_range("2020-01-01", periods=2, freq="D")
        discharge = pd.Series([5.0, 7.0], index=idx, name="discharge")
        grp = _make_grp_with_runoff(
            values=[10.0, 10.0], timestamps=idx.values - np.timedelta64(1, "D")
        )

        with caplog.at_level("WARNING"):
            out = _add_runoff_to_discharge_series(discharge, "sim-0", store=None, grp=grp)

        np.testing.assert_allclose(out.to_numpy(), expected, rtol=1e-12)
        said = "catchment discharge: catchment area unavailable for sim sim-0 — skipping runoff addition."
        assert (said in caplog.text) is (area_m2 == 0.0)

    def test_a_forcing_without_runoff_leaves_the_baseflow_alone(self):
        idx = pd.date_range("2020-01-01", periods=2, freq="D")
        discharge = pd.Series([5.0, 7.0], index=idx, name="discharge")
        grp = _FakeRootGroup(forcing=_FakeNode({"temperature": None}))

        out = _add_runoff_to_discharge_series(
            discharge, "sim-0", store=_SeriesStore(gauged=False), grp=grp
        )

        pd.testing.assert_series_equal(out, discharge)

    def test_a_station_that_cannot_be_read_is_skipped_and_the_next_one_is_kept(self, monkeypatch):
        _patch_area(monkeypatch, 86_400_000.0)
        day = np.array(["2019-12-31"], dtype="datetime64[ns]")

        def station(values, stamps):
            return _FakeNode({"values": _FakeArray(values), "timestamps": _FakeArray(stamps)})

        stations = {
            "flat": _FakeArray([9.0]),
            "bare": _FakeNode({"values": _FakeArray([9.0])}),
            "empty": station(np.empty(0), np.empty(0, dtype="datetime64[ns]")),
            "good": station([4.0], day),
        }
        grp = _FakeRootGroup(_FakeNode({"runoff": _FakeRunoffGroup(stations)}))
        idx = pd.date_range("2020-01-01", periods=1, freq="D")
        discharge = pd.Series([1.0], index=idx, name="discharge")

        out = _add_runoff_to_discharge_series(discharge, "sim-0", store=None, grp=grp)

        np.testing.assert_allclose(out.to_numpy(), [5.0])

    def test_the_runoff_is_scaled_by_the_area_of_the_stored_basin(self, monkeypatch):
        # catch_area would give 1 m3/s per mm/day; the basin is twice as large.
        _patch_area(monkeypatch, 86_400_000.0)
        idx = pd.date_range("2020-01-01", periods=2, freq="D")
        discharge = pd.Series([0.0, 0.0], index=idx, name="discharge")
        runoff_idx = pd.date_range("2019-12-31", periods=2, freq="D")
        grp = _make_grp_with_runoff(values=[1.0, 1.0], timestamps=runoff_idx.values)
        grp.get = _with_mesh(grp.get, area_m2=2 * 86_400_000.0, rule="near_point")

        out = _add_runoff_to_discharge_series(discharge, str(uuid4()), store=None, grp=grp)

        np.testing.assert_allclose(out.values, [2.0, 2.0])

    def test_the_runoff_area_does_not_compute_the_basin_again(self, monkeypatch):
        from hydromodpy.solver.modflow_common import catchment_basin
        from hydromodpy.spatial.drainage import descent as core_descent

        def refuse(*_args, **_kwargs):
            raise AssertionError("the runoff area computed the basin of D again")

        monkeypatch.setattr(core_descent, "descent_basin", refuse)
        monkeypatch.setattr(catchment_basin, "descent_basin", refuse)
        _patch_area(monkeypatch, 86_400_000.0)
        idx = pd.date_range("2020-01-01", periods=2, freq="D")
        discharge = pd.Series([0.0, 0.0], index=idx, name="discharge")
        runoff_idx = pd.date_range("2019-12-31", periods=2, freq="D")
        grp = _make_grp_with_runoff(values=[1.0, 1.0], timestamps=runoff_idx.values)
        grp.get = _with_mesh(grp.get, area_m2=2 * 86_400_000.0, rule="near_point")

        out = _add_runoff_to_discharge_series(discharge, str(uuid4()), store=None, grp=grp)

        np.testing.assert_allclose(out.values, [2.0, 2.0])

    def test_a_run_without_a_basin_scales_by_catch_area_and_says_so(self, monkeypatch, caplog):
        _patch_area(monkeypatch, 86_400_000.0)
        idx = pd.date_range("2020-01-01", periods=2, freq="D")
        discharge = pd.Series([0.0, 0.0], index=idx, name="discharge")
        runoff_idx = pd.date_range("2019-12-31", periods=2, freq="D")
        grp = _make_grp_with_runoff(values=[1.0, 1.0], timestamps=runoff_idx.values)

        with caplog.at_level("INFO"):
            out = _add_runoff_to_discharge_series(discharge, "sim-x", store=None, grp=grp)

        np.testing.assert_allclose(out.values, [1.0, 1.0])
        assert (
            "Catchment discharge for sim sim-x: the run stores no basin of D, so the runoff is "
            "scaled by the old support 'catch_area' (86.400 km2)." in caplog.text
        )

    def test_the_largest_basin_keeps_catch_area_without_the_message(self, monkeypatch, caplog):
        _patch_area(monkeypatch, 86_400_000.0)
        idx = pd.date_range("2020-01-01", periods=2, freq="D")
        discharge = pd.Series([0.0, 0.0], index=idx, name="discharge")
        runoff_idx = pd.date_range("2019-12-31", periods=2, freq="D")
        grp = _make_grp_with_runoff(values=[1.0, 1.0], timestamps=runoff_idx.values)
        grp.get = _with_mesh(grp.get, area_m2=5.0e9, rule="largest_basin")

        with caplog.at_level("INFO"):
            out = _add_runoff_to_discharge_series(discharge, str(uuid4()), store=None, grp=grp)

        np.testing.assert_allclose(out.values, [1.0, 1.0])
        assert "stores no basin of D" not in caplog.text

    def test_alignment_when_runoff_index_offset(self, monkeypatch):
        # Runoff stamped a few hours into each day still falls in the period
        # that day is: [stamp - 1 day, stamp).
        area_m2 = 86_400_000.0
        _patch_area(monkeypatch, area_m2)

        target = pd.date_range("2020-01-01", periods=3, freq="D")
        discharge = pd.Series([0.0, 0.0, 0.0], index=target, name="discharge")
        runoff_idx = pd.date_range("2019-12-31 02:00", periods=3, freq="D")
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

    def test_resolves_the_root_array_and_sums_its_outflow(self):
        frames = np.array([[-1.0, 2.0, -3.0], [4.0, -5.0, 6.0]])  # 2 timesteps
        grp = self._grp_with_root_field("drain", frames)
        out = _aggregate_variable(
            store=None,
            sim_id="s",
            grp=grp,
            store_var="drain",
            n_timesteps=2,
            active_mask=None,
            reducer="outflow_sum",
        )
        # Outflow per timestep: 1+3=4 ; 5.
        assert out == pytest.approx([4.0, 5.0])

    def test_prefers_derived_over_root(self):
        # Same key present in derived/ and root; derived wins.
        derived = _DictGroup({"flux": _FakeArray(np.array([[10.0, 10.0]]))})
        grp = _DictGroup({"derived": derived, "flux": _FakeArray(np.array([[1.0, 1.0]]))})
        out = _aggregate_variable(None, "s", grp, "flux", 1, None, "sum")
        assert out == pytest.approx([20.0])

    def test_missing_variable_returns_none(self):
        grp = _DictGroup({"head": _FakeArray(np.zeros((1, 3)))})
        out = _aggregate_variable(None, "s", grp, "wells|well", 1, None, "sum")
        assert out is None

    def test_mask_excludes_inactive_cells(self):
        frames = np.array([[1.0, 999.0, 2.0]])
        grp = self._grp_with_root_field("drain", frames)
        mask = np.array([True, False, True])
        out = _aggregate_variable(None, "s", grp, "drain", 1, mask, "sum")
        # Masked middle cell ignored: 1 + 2 = 3.
        assert out == pytest.approx([3.0])


def _utc(day: str):
    """The instant a run records for a calendar day: midnight UTC."""
    return pd.Timestamp(day, tz="UTC").to_pydatetime()


class TestResolveTimeIndex:
    def test_builds_range_from_period_bounds(self, runs):
        sid = runs.open(
            solver="modflow_nwt",
            n_cells=3,
            n_layers=1,
            n_timesteps=4,
            period_start=_utc("2020-01-01"),
            period_end=_utc("2020-01-04"),
        ).sim_id
        idx = _resolve_time_index(runs.store(sid), sid, 4)
        assert isinstance(idx, pd.DatetimeIndex)
        assert len(idx) == 4
        # tz may be applied by the backend; compare on the calendar date.
        idx_naive = idx.tz_localize(None) if idx.tz is not None else idx
        assert idx_naive[0].date().isoformat() == "2020-01-01"
        assert idx_naive[-1].date().isoformat() == "2020-01-04"
        # date_range with periods=n must produce a strictly increasing index.
        assert idx.is_monotonic_increasing

    def test_missing_period_raises(self, runs):
        sid = runs.open(solver="modflow_nwt", n_cells=3, n_layers=1, n_timesteps=2).sim_id
        with pytest.raises(RuntimeError, match="period_start"):
            _resolve_time_index(runs.store(sid), sid, 2)


class TestAggregateEndToEnd:
    def _setup_sim(self, runs, n_ts=3, n_cells=4):
        sid = runs.open(
            solver="modflow_nwt",
            n_cells=n_cells,
            n_layers=1,
            n_timesteps=n_ts,
            period_start=_utc("2020-01-01"),
            period_end=_utc("2020-01-03"),
        ).sim_id
        # head drives _detect_n_timesteps.
        for t in range(n_ts):
            runs.store(sid).write_field(
                sid, "head", t, np.full((1, n_cells), 5.0), n_timesteps=n_ts if t == 0 else None
            )
        return sid

    def test_writes_discharge_timeseries_from_drain_field(self, runs):
        n_ts, n_cells = 3, 4
        sid = self._setup_sim(runs, n_ts=n_ts, n_cells=n_cells)
        # Signed drain fluxes per timestep; discharge = outflow summed over cells.
        drain_frames = {
            0: np.array([[-1.0, -2.0, -3.0, -4.0]]),  # outflow = 10
            1: np.array([[-2.0, -2.0, -2.0, -2.0]]),  # outflow = 8
            2: np.array([[-1.0, -1.0, -1.0, 1.0]]),  # outflow = 3, one cell gains water
        }
        for t in range(n_ts):
            runs.store(sid).write_field(
                sid, "drain", t, drain_frames[t], n_timesteps=n_ts if t == 0 else None
            )

        aggregate_catchment_timeseries(sid, runs.store(sid))

        ts = runs.store(sid).query_timeseries(sid, CATCHMENT, "discharge")
        assert len(ts) == n_ts
        np.testing.assert_allclose(sorted(ts.values), [3.0, 8.0, 10.0])
        # Unit must be persisted as m3/s.
        rows = runs.store(sid).read_table("timeseries")
        assert set(rows.loc[rows["variable"] == "discharge", "unit"]) == {"m3 s-1"}

    def test_a_surface_excess_is_water_that_reaches_the_discharge(self, runs):
        # A Boussinesq run sends its water through the excess: the drain alone reads zero.
        n_ts = 2
        sid = runs.open(solver="boussinesq", n_cells=4, n_layers=1, n_timesteps=n_ts).sim_id
        store = runs.store(sid)
        store.write_time(sid, np.array([86400.0, 172800.0]), units="seconds since 1970-01-01")
        store.write_field(sid, "head", 0, np.zeros((1, 4)), n_timesteps=n_ts)
        store.write_field(sid, "head", 1, np.zeros((1, 4)))
        for t, (drain, excess) in enumerate([(-1.0e-9, -2.0), (-1.0e-9, -3.0)]):
            kept = {"n_timesteps": n_ts} if t == 0 else {}
            store.write_field(sid, "drain", t, np.full(4, drain), subgroup="budget", **kept)
            store.write_field(
                sid, "surface_excess", t, np.full(4, excess), subgroup="budget", **kept
            )

        aggregate_catchment_timeseries(sid, store)

        ts = store.query_timeseries(sid, CATCHMENT, "discharge")
        np.testing.assert_allclose(ts.values, [8.0 + 4e-9, 12.0 + 4e-9])

    def test_no_aggregable_field_writes_nothing(self, runs):
        # head exists (so n_timesteps>0) but no drain/well field -> no output.
        sid = self._setup_sim(runs)
        aggregate_catchment_timeseries(sid, runs.store(sid))
        with pytest.raises(KeyError):
            runs.store(sid).query_timeseries(sid, CATCHMENT, "discharge")


class TestRoutedDischarge:
    """discharge = SFR/LAK ext_outflow only (buffer DRN excluded) when routed."""

    def _setup_sim(self, runs, n_ts=3, n_cells=4, with_drains=True):
        sid = runs.open(
            solver="modflow6",
            n_cells=n_cells,
            n_layers=1,
            n_timesteps=n_ts,
            period_start=_utc("2020-01-01"),
            period_end=_utc("2020-01-03"),
        ).sim_id
        for t in range(n_ts):
            runs.store(sid).write_field(
                sid, "head", t, np.full((1, n_cells), 5.0), n_timesteps=n_ts if t == 0 else None
            )
        if with_drains:
            drain_frames = {
                0: np.array([[-1.0, -2.0, -3.0, -4.0]]),  # outflow = 10
                1: np.array([[-2.0, -2.0, -2.0, -2.0]]),  # outflow = 8
                2: np.array([[-1.0, -1.0, -1.0, -1.0]]),  # outflow = 4
            }
            for t in range(n_ts):
                runs.store(sid).write_field(
                    sid, "drain", t, drain_frames[t], n_timesteps=n_ts if t == 0 else None
                )
        return sid

    def _write_ext_outflow(self, runs, sid, station, values):
        idx = pd.date_range("2020-01-01", periods=len(values), freq="D")
        runs.store(sid).write_timeseries(
            sid, station, "ext_outflow", pd.Series(values, index=idx), unit="m3/s"
        )

    def test_discharge_is_routed_outflow_excluding_buffer_drains(self, runs):
        sid = self._setup_sim(runs)
        # Both extractors store ext_outflow positive. The buffer plain-DRN field
        # (neighboring-basin drainage) must NOT be added to the routed discharge.
        self._write_ext_outflow(runs, sid, "net:7", [1.0, 2.0, 3.0])
        self._write_ext_outflow(runs, sid, "net:2", [0.0, 0.0, 0.0])
        self._write_ext_outflow(runs, sid, "lake:res", [0.5, 0.5, 1.0])

        aggregate_catchment_timeseries(sid, runs.store(sid))

        ts = runs.store(sid).query_timeseries(sid, CATCHMENT, "discharge")
        # routed = sfr + lake per timestep; the |DRN| buffer field is excluded.
        np.testing.assert_allclose(ts.values, [1.5, 2.5, 4.0])

    def test_the_discharge_is_summed_over_the_stored_basin(self, runs):
        n_ts, n_cells = 3, 4
        sid = self._setup_sim(runs, n_ts=n_ts, n_cells=n_cells)
        sz = runs.store(sid).open_zarr(sid)
        try:
            mesh = sz.root.require_group("mesh")
            mesh.create_array("topography", data=np.full(n_cells, 10.0))
            basin = mesh.create_array("descent_basin", data=np.array([True, True, False, False]))
            basin.attrs["basin_rule"] = "near_point"
            basin.attrs["basin_area_m2"] = 2.0e6
        finally:
            sz.close()
        for t in range(n_ts):
            runs.store(sid).write_field(sid, "drain", t, np.array([[-1.0, -2.0, -4.0, -8.0]]))

        aggregate_catchment_timeseries(sid, runs.store(sid))

        ts = runs.store(sid).query_timeseries(sid, CATCHMENT, "discharge")
        np.testing.assert_allclose(ts.values, [3.0, 3.0, 3.0])

    def test_routed_branch_skips_lumped_runoff(self, runs, monkeypatch):
        import hydromodpy.simulation.extraction.derivation.catchment_aggregation as mod

        def _must_not_run(*args, **kwargs):
            raise AssertionError("lumped runoff must not be added on the routed branch")

        monkeypatch.setattr(mod, "_add_runoff_to_discharge_series", _must_not_run)
        sid = self._setup_sim(runs)
        self._write_ext_outflow(runs, sid, "net:7", [1.0, 1.0, 1.0])

        aggregate_catchment_timeseries(sid, runs.store(sid))

        ts = runs.store(sid).query_timeseries(sid, CATCHMENT, "discharge")
        # routed only; the buffer DRN field and lumped runoff are both excluded.
        np.testing.assert_allclose(ts.values, [1.0, 1.0, 1.0])

    def test_routed_only_discharge_written_without_drain_field(self, runs):
        # Pure SFR drainage: no DRN array at all, discharge = routed outflow.
        sid = self._setup_sim(runs, with_drains=False)
        self._write_ext_outflow(runs, sid, "net:7", [2.0, 4.0, 6.0])

        aggregate_catchment_timeseries(sid, runs.store(sid))

        ts = runs.store(sid).query_timeseries(sid, CATCHMENT, "discharge")
        np.testing.assert_allclose(ts.values, [2.0, 4.0, 6.0])

    def test_a_measured_outflow_does_not_trigger_routed_branch(self, runs):
        # Only a simulated ext_outflow is the routed discharge.
        sid = self._setup_sim(runs)
        idx = pd.date_range("2020-01-01", periods=3, freq="D")
        runs.store(sid).write_timeseries(
            sid, "G1", "ext_outflow", pd.Series([100.0] * 3, index=idx), source="observed"
        )

        aggregate_catchment_timeseries(sid, runs.store(sid))

        ts = runs.store(sid).query_timeseries(sid, CATCHMENT, "discharge")
        np.testing.assert_allclose(ts.values, [10.0, 8.0, 4.0])


class TestReadCatchmentArea:
    def _register(self, runs):
        sid = runs.open(solver="modflow_nwt", n_cells=4, n_layers=1, n_timesteps=2).sim_id
        return sid

    def test_returns_stored_area_converted_to_m2(self, runs):
        sid = self._register(runs)
        # catch_area is stored in km2; the reader converts to m2 (factor 1e6).
        runs.store(sid).write_geographic_metadata(sid, {"catch_area": 12.5})

        area_m2 = _read_catchment_area_m2(runs.store(sid), sid)

        assert area_m2 == pytest.approx(12.5 * 1e6)

    def test_returns_zero_when_area_absent(self, runs):
        sid = self._register(runs)
        # No catch_area row written for this sim.
        assert _read_catchment_area_m2(runs.store(sid), sid) == 0.0


class TestAggregateFromLumpedBudget:
    """The fallback that keeps discharge alive when the per-cell budget is not kept.

    With the per-cell budget unpersisted (``keep_per_cell_budget = false``),
    the catchment scalars come from the lumped per-component ``budgets``
    table instead of a Zarr field, so this path carries discharge in such a run.
    """

    def _register(self, runs, n_ts: int = 3) -> str:
        sid = runs.open(
            solver="modflow6",
            n_cells=4,
            n_layers=1,
            n_timesteps=n_ts,
            period_start=_utc("2020-01-01"),
            period_end=_utc("2020-01-03"),
        ).sim_id
        return sid

    def _write_drain_budget(self, runs, sid, values, *, component="drain"):
        for timestep, flux_out in values.items():
            runs.store(sid).write_budget(
                sid,
                timestep=timestep,
                zone_id="total",
                component=component,
                flux_in=0.0,
                flux_out=flux_out,
            )

    def test_drain_component_gives_discharge(self, runs):
        sid = self._register(runs)
        self._write_drain_budget(runs, sid, {0: 10.0, 1: 8.0, 2: 4.0})

        values = _aggregate_from_lumped_budget(runs.store(sid), sid, "drain", "outflow_sum", 3)

        assert values == pytest.approx([10.0, 8.0, 4.0])

    def test_signed_reducer_returns_in_minus_out(self, runs):
        sid = self._register(runs)
        runs.store(sid).write_budget(
            sid, timestep=0, zone_id="total", component="well", flux_in=1.0, flux_out=4.0
        )

        values = _aggregate_from_lumped_budget(runs.store(sid), sid, "well", "sum", 1)

        assert values == pytest.approx([-3.0])

    def test_missing_timestep_is_nan_not_zero(self, runs):
        # A gap must stay missing: a zero would bias the metrics toward a null flux.
        sid = self._register(runs)
        self._write_drain_budget(runs, sid, {0: 10.0, 2: 4.0})

        values = _aggregate_from_lumped_budget(runs.store(sid), sid, "drain", "outflow_sum", 3)

        assert values[0] == pytest.approx(10.0)
        assert np.isnan(values[1])
        assert values[2] == pytest.approx(4.0)

    def test_unknown_component_returns_none(self, runs):
        sid = self._register(runs)
        self._write_drain_budget(runs, sid, {0: 1.0})

        assert (
            _aggregate_from_lumped_budget(runs.store(sid), sid, "river", "outflow_sum", 1) is None
        )

    def test_unsupported_reducer_returns_none(self, runs):
        sid = self._register(runs)
        self._write_drain_budget(runs, sid, {0: 1.0})

        assert (
            _aggregate_from_lumped_budget(runs.store(sid), sid, "drain", "mean_active", 1) is None
        )

    def test_unreadable_budgets_table_raises(self, runs):
        sid = self._register(runs)

        class _BrokenStore:
            def read_table(self, view_name):
                raise RuntimeError(f"{view_name} table is unreadable")

        with pytest.raises(ExtractError, match="lumped budget"):
            _aggregate_from_lumped_budget(_BrokenStore(), sid, "drain", "outflow_sum", 1)

    def test_end_to_end_discharge_without_spatial_budget(self, runs):
        # No drain Zarr field at all: the lumped budget alone must produce the
        # catchment discharge series, which is what a run without the per-cell budget relies on.
        sid = self._register(runs)
        for t in range(3):
            runs.store(sid).write_field(
                sid, "head", t, np.full((1, 4), 5.0), n_timesteps=3 if t == 0 else None
            )
        self._write_drain_budget(runs, sid, {0: 10.0, 1: 8.0, 2: 4.0})

        aggregate_catchment_timeseries(sid, runs.store(sid))

        ts = runs.store(sid).query_timeseries(sid, CATCHMENT, "discharge")
        np.testing.assert_allclose(ts.values, [10.0, 8.0, 4.0])


class TestTheCatchmentSeriesUseTheCatchment:
    """The station is named ``catchment``. The support has to be one.

    A model domain is not a catchment: MODFLOW-NWT meshes the delineated basin
    so the two coincide, MODFLOW 6 meshes the buffered box so they do not.
    Measured on the Nancon at 25 m, 152.2 km2 of domain against 64.6 km2 of
    catchment, 2.119 m3/s of drain outflow against 0.888 m3/s inside the basin.
    Summed over the domain, a series compared to a gauge is 2.4 times the water
    that gauge sees.
    """

    def _grp(self, n_cells: int):
        """A one-row mesh of unit squares, written the way a run writes it."""
        import zarr

        root = zarr.group()
        mesh = root.require_group("mesh")
        x = np.arange(n_cells + 1, dtype="float64")
        vertices = np.array(
            [[float(v), 0.0, 0.0] for v in x] + [[float(v), 1.0, 0.0] for v in x],
            dtype="float64",
        )
        n_x = x.size
        connectivity = np.array(
            [[i, i + 1, n_x + i + 1, n_x + i] for i in range(n_cells)], dtype="int32"
        )
        mesh.create_array("vertices", data=vertices)
        mesh.create_array("face_node_connectivity", data=connectivity)
        mesh.create_array("topography", data=np.full(n_cells, 10.0, dtype="float64"))
        # The frame goes where a run actually writes it: the CF grid-mapping
        # scalar at the root, carrying crs_wkt. A fixture that put it on the
        # mesh group instead stayed green while every real run failed to place
        # the watershed, which is exactly what happened.
        crs = root.create_array("crs", shape=(), dtype="int32")
        crs.attrs["grid_mapping_name"] = "lambert_conformal_conic"
        crs.attrs["crs_wkt"] = "EPSG:2154"
        return root

    def _store_with_watershed(self, geometry):
        class _Store:
            def read_geographic_feature(self, sim_id, name):
                import geopandas as gpd

                del sim_id, name
                return gpd.GeoDataFrame(geometry=[geometry], crs="EPSG:2154")

        return _Store()

    def test_only_the_cells_inside_the_watershed_are_kept(self):
        from shapely.geometry import box

        from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
            _build_catchment_mask,
        )

        grp = self._grp(6)
        active = np.ones(6, dtype=bool)
        # A box covering the centers of the first two cells only (x in 0..2).
        mask = _build_catchment_mask(
            self._store_with_watershed(box(-0.1, -0.1, 2.0, 1.1)), "sim", grp, active
        )

        assert mask.tolist() == [True, True, False, False, False, False]

    def test_a_run_without_a_watershed_keeps_the_domain_and_warns(self, caplog):
        from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
            _build_catchment_mask,
        )

        class _Store:
            def read_geographic_feature(self, sim_id, name):
                raise KeyError(name)

        grp = self._grp(4)
        active = np.ones(4, dtype=bool)
        with caplog.at_level("WARNING"):
            mask = _build_catchment_mask(_Store(), "sim", grp, active)

        assert mask is active
        assert "neighbouring basins" in " ".join(r.getMessage() for r in caplog.records)

    def test_a_store_without_a_declared_frame_falls_back_and_says_so(self, caplog):
        # The frame is never guessed: placed on the wrong one, the watershed
        # lands somewhere else entirely and the series still look plausible.
        from shapely.geometry import box

        from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
            _build_catchment_mask,
        )

        grp = self._grp(4)
        del grp["crs"]
        active = np.ones(4, dtype=bool)
        with caplog.at_level("WARNING"):
            mask = _build_catchment_mask(
                self._store_with_watershed(box(-0.1, -0.1, 2.0, 1.1)), "sim", grp, active
            )

        assert mask is active
        assert "declares no CRS" in " ".join(r.getMessage() for r in caplog.records)

    def test_a_watershed_that_lands_nowhere_falls_back_and_says_so(self, caplog):
        from shapely.geometry import box

        from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
            _build_catchment_mask,
        )

        grp = self._grp(4)
        active = np.ones(4, dtype=bool)
        with caplog.at_level("WARNING"):
            mask = _build_catchment_mask(
                self._store_with_watershed(box(1e6, 1e6, 1e6 + 10, 1e6 + 10)), "sim", grp, active
            )

        assert mask is active
        assert "no cell" in " ".join(r.getMessage() for r in caplog.records)

    def _with_basin(self, grp, mask, *, rule="within_polygon", area_m2=2.0e6):
        node = grp["mesh"].create_array("descent_basin", data=np.asarray(mask, dtype=bool))
        node.attrs["descent_outlet"] = 0
        node.attrs["basin_rule"] = rule
        node.attrs["basin_area_m2"] = area_m2
        return grp

    def test_the_stored_basin_is_the_support_not_the_polygon(self, caplog):
        from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
            _build_catchment_mask,
        )

        class _Store:
            def read_geographic_feature(self, sim_id, name):
                raise AssertionError("the polygon was read although the run stores a basin")

        grp = self._with_basin(self._grp(6), [1, 1, 1, 0, 0, 1])
        active = np.array([1, 1, 0, 1, 1, 1], dtype=bool)
        with caplog.at_level("INFO"):
            mask = _build_catchment_mask(_Store(), "sim", grp, active)

        assert mask.tolist() == [True, True, False, False, False, True]
        assert "the basin of D, 3 of 5 active cells (2.000 km2)" in caplog.text
        assert "polygon_centroid" not in caplog.text

    def test_a_basin_with_no_active_cell_is_refused(self):
        from hydromodpy.core.exceptions import ExtractError
        from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
            _build_catchment_mask,
        )

        grp = self._with_basin(self._grp(4), [1, 1, 0, 0])
        with pytest.raises(ExtractError, match="holds no active cell"):
            _build_catchment_mask(None, "sim", grp, np.array([0, 0, 1, 1], dtype=bool))

    def test_a_run_without_a_basin_keeps_the_polygon_and_says_so(self, caplog):
        from shapely.geometry import box

        from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
            _build_catchment_mask,
        )

        with caplog.at_level("INFO"):
            mask = _build_catchment_mask(
                self._store_with_watershed(box(-0.1, -0.1, 2.0, 1.1)),
                "sim",
                self._grp(6),
                np.ones(6, dtype=bool),
            )

        assert mask.tolist() == [True, True, False, False, False, False]
        assert (
            "Catchment timeseries for sim sim: the run stores no basin of D, so the "
            "catchment series keep the old support 'polygon_centroid'." in caplog.text
        )

    def test_the_largest_basin_of_a_synthetic_domain_keeps_the_domain(self, caplog):
        from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
            _build_catchment_mask,
        )

        class _Store:
            def read_geographic_feature(self, sim_id, name):
                raise KeyError(name)

        grp = self._with_basin(self._grp(4), [1, 1, 1, 1], rule="largest_basin")
        active = np.ones(4, dtype=bool)
        with caplog.at_level("INFO"):
            mask = _build_catchment_mask(_Store(), "sim", grp, active)

        assert mask is active
        assert "stores no basin of D" not in caplog.text

    def test_no_series_computes_the_basin_again(self, monkeypatch):
        from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
            _build_catchment_mask,
        )
        from hydromodpy.solver.modflow_common import catchment_basin
        from hydromodpy.spatial.drainage import descent as core_descent

        def refuse(*_args, **_kwargs):
            raise AssertionError("the aggregation computed the basin of D again")

        monkeypatch.setattr(core_descent, "descent_basin", refuse)
        monkeypatch.setattr(catchment_basin, "descent_basin", refuse)
        grp = self._with_basin(self._grp(4), [1, 0, 1, 0])

        mask = _build_catchment_mask(None, "sim", grp, np.ones(4, dtype=bool))

        assert mask.tolist() == [True, False, True, False]


class TestLumpedBudgetPrefersTheCatchmentZone:
    """A ``zone_id = 'catchment'`` row is the only lumped row a gauge matches.

    Every other zone spans the model domain. On a buffered MODFLOW 6 grid that
    takes in the neighboring basins, so the ``catchment`` series would carry
    more water than the outlet ever sees.
    """

    def _register(self, runs, n_ts: int = 2) -> str:
        sid = runs.open(
            solver="modflow6",
            n_cells=4,
            n_layers=1,
            n_timesteps=n_ts,
            period_start=_utc("2020-01-01"),
            period_end=_utc("2020-01-02"),
        ).sim_id
        return sid

    def _write(self, runs, sid, zone, values, component="drain"):
        for timestep, flux_out in values.items():
            runs.store(sid).write_budget(
                sid,
                timestep=timestep,
                zone_id=zone,
                component=component,
                flux_in=0.0,
                flux_out=flux_out,
            )

    def test_the_catchment_row_wins_over_the_domain_row(self, runs):
        sid = self._register(runs)
        self._write(runs, sid, "0", {0: 2.119, 1: 2.0})
        self._write(runs, sid, CATCHMENT, {0: 0.888, 1: 0.8})

        values = _aggregate_from_lumped_budget(runs.store(sid), sid, "drain", "outflow_sum", 2)

        # Neither the domain row nor the sum of the two: only the basin.
        assert values == pytest.approx([0.888, 0.8])

    def test_the_two_rows_are_never_summed(self, runs):
        # The historical query had no zone filter. It was harmless only while
        # every component carried a single zone; a second row would have
        # doubled the discharge without a word.
        sid = self._register(runs, n_ts=1)
        self._write(runs, sid, "0", {0: 2.0})
        self._write(runs, sid, CATCHMENT, {0: 0.5})

        values = _aggregate_from_lumped_budget(runs.store(sid), sid, "drain", "outflow_sum", 1)

        assert values == pytest.approx([0.5])
        assert values[0] != pytest.approx(2.5)

    def test_domain_only_is_used_but_warned_about_and_never_rescaled(self, runs, caplog):
        sid = self._register(runs, n_ts=1)
        self._write(runs, sid, "0", {0: 2.119})

        with caplog.at_level("WARNING"):
            values = _aggregate_from_lumped_budget(
                runs.store(sid), sid, "drain", "outflow_sum", 1, catchment_fraction=0.42
            )

        # The value is reported as it stands: rescaling a domain total by an
        # area ratio would invent a number nothing measured.
        assert values == pytest.approx([2.119])
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "NOT rescaled" in message
        assert "42%" in message

    def test_a_domain_that_is_the_catchment_says_nothing(self, runs, caplog):
        # MODFLOW-NWT meshes the delineated basin, so its domain row already has
        # the catchment for support. Warning there would cry wolf.
        sid = self._register(runs, n_ts=1)
        self._write(runs, sid, "0", {0: 0.888})

        with caplog.at_level("WARNING"):
            values = _aggregate_from_lumped_budget(
                runs.store(sid), sid, "drain", "outflow_sum", 1, catchment_fraction=1.0
            )

        assert values == pytest.approx([0.888])
        assert caplog.records == []

    def test_catchment_fraction_reports_the_covered_share(self):
        domain = np.array([True, True, True, True])
        catchment = np.array([True, False, True, False])

        assert _catchment_fraction(catchment, domain) == pytest.approx(0.5)
        assert _catchment_fraction(None, domain) is None
        assert _catchment_fraction(catchment, np.zeros(4, dtype=bool)) is None


class TestTheCatchmentRowBeatsTheRoundedPerCellField:
    """The per-cell budget is float32 rounded to 16 bits, the lumped row float64."""

    N_TS = 2

    def _sim_with_drain_field(self, runs) -> str:
        sid = runs.open(
            solver="modflow6",
            n_cells=4,
            n_layers=1,
            n_timesteps=self.N_TS,
            period_start=_utc("2020-01-01"),
            period_end=_utc("2020-01-02"),
        ).sim_id
        for t in range(self.N_TS):
            runs.store(sid).write_field(
                sid, "head", t, np.full((1, 4), 5.0), n_timesteps=self.N_TS if t == 0 else None
            )
            runs.store(sid).write_field(
                sid,
                "drain",
                t,
                np.full((1, 4), -1.0),
                n_timesteps=self.N_TS if t == 0 else None,
            )
        return sid

    def _write_row(self, runs, sid, zone, values):
        for timestep, flux_out in values.items():
            runs.store(sid).write_budget(
                sid,
                timestep=timestep,
                zone_id=zone,
                component="drain",
                flux_in=0.0,
                flux_out=flux_out,
            )

    def _discharge(self, runs, sid) -> np.ndarray:
        aggregate_catchment_timeseries(sid, runs.store(sid))
        return runs.store(sid).query_timeseries(sid, CATCHMENT, "discharge").values

    def test_the_catchment_row_gives_the_series_exactly(self, runs):
        sid = self._sim_with_drain_field(runs)
        exact = {0: 3.141592653589793, 1: 2.718281828459045}
        self._write_row(runs, sid, CATCHMENT, exact)

        series = self._discharge(runs, sid)

        # The per-cell field would give 4.0 on both steps.
        assert series.tolist() == list(exact.values())

    def test_without_a_catchment_row_the_per_cell_field_is_used(self, runs):
        sid = self._sim_with_drain_field(runs)
        # A domain row exists but is no catchment row: it must not win.
        self._write_row(runs, sid, "0", {0: 99.0, 1: 99.0})

        series = self._discharge(runs, sid)

        np.testing.assert_allclose(series, [4.0, 4.0])
