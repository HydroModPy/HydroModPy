"""Tests of `metrics.series`."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.calibration.metrics import series as series_module
from hydromodpy.calibration.metrics.series import add_runoff_to_discharge
from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
    _add_runoff_to_discharge_series,
)
from hydromodpy.simulation.soil_recharge import compute_soil_forcings
from hydromodpy.workflow.steps.prepare_solver.prepare import _watershed_mean_series
from tests.unit.calibration._factories_scoring import (
    CATCH_AREA_KM2,
    scored_discharge,
    soil_forcings,
)

# From test_a_gridded_runoff_is_added_to_the_scored_discharge.py
# A gridded runoff enters the scored discharge as it enters the stored one.
#
# A SIM2 runoff loads as gridded fields, not station points. The run reduces it
# to a watershed-mean series (``forcing/runoff/_watershed``) and the derived
# catchment discharge adds that series. The calibration metric read only station
# points, so it scored the drain baseflow alone against total streamflow while the
# stored run reported drain plus runoff.


# 1 mm/day over 86.4 km² is exactly 1 m³/s: 1e-3 * 8.64e7 / 86400.
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
        setup=SimpleNamespace(geographic=SimpleNamespace(catch_area=CATCH_AREA_KM2)),
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


def _stored_run(runoff: LoadResult):
    """The fields store a run persists for a gridded runoff, and its catalog."""
    persisted = _watershed_mean_series(runoff)
    station = _Node(
        {
            "values": _Array(persisted.to_numpy(dtype="float64")),
            "timestamps": _Array(pd.DatetimeIndex(persisted.index).values),
        }
    )
    grp = _Node({"forcing": _Node({"runoff": _StationGroup({"catchment": station})})})
    store = SimpleNamespace(read_geographic_metadata=lambda _sim_id: {"catch_area": CATCH_AREA_KM2})
    return store, grp


@pytest.fixture()
def _fresh_warnings(monkeypatch):
    monkeypatch.setattr(series_module, "_RUNOFF_WARNING_EMITTED", set())


@pytest.mark.usefixtures("_fresh_warnings")
def test_a_gridded_runoff_is_added_as_its_watershed_mean() -> None:
    baseflow = pd.Series(0.0, index=_SIM_INDEX, name="discharge")

    scored = add_runoff_to_discharge(baseflow, _context(_gridded_runoff()))

    assert scored.tolist() == pytest.approx([3.5, 6.5, 10.5])


@pytest.mark.usefixtures("_fresh_warnings")
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


@pytest.mark.usefixtures("_fresh_warnings")
def test_a_gauge_scales_the_gridded_runoff_by_the_area_it_drains() -> None:
    baseflow = pd.Series(0.0, index=_SIM_INDEX, name="discharge")

    scored = add_runoff_to_discharge(
        baseflow, _context(_gridded_runoff()), area_m2=CATCH_AREA_KM2 * 1e6 / 2.0
    )

    assert scored.tolist() == pytest.approx([1.75, 3.25, 5.25])


@pytest.mark.usefixtures("_fresh_warnings")
def test_a_runoff_day_without_a_valid_pixel_is_refused_by_name() -> None:
    runoff = _gridded_runoff()
    runoff.fields[0].data["runoff"][5] = np.nan
    baseflow = pd.Series(0.0, index=_SIM_INDEX, name="discharge")

    with pytest.raises(DataContractViolation, match="no valid pixel in time step 5"):
        add_runoff_to_discharge(baseflow, _context(runoff))


@pytest.mark.usefixtures("_fresh_warnings")
def test_no_runoff_at_all_still_says_so(caplog) -> None:
    baseflow = pd.Series([0.4, 0.7, 1.1], index=_SIM_INDEX, name="discharge")

    with caplog.at_level(logging.WARNING, logger=series_module.__name__):
        scored = add_runoff_to_discharge(baseflow, _context(LoadResult()))

    assert scored.tolist() == baseflow.tolist()
    (record,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "no runoff data loaded" in record.getMessage()


# From test_a_period_without_runoff_is_a_gap_in_the_scored_discharge.py
# A period the runoff forcing does not cover is a gap, not baseflow only.
#
# ``period_mean_on_index`` answers NaN for a period holding no runoff sample.
# Adding that NaN as zero scored the drain baseflow alone against a total
# streamflow observation, the apples-to-oranges the runoff addition exists to
# remove. The summed discharge is a gap there, and the score drops the pair.


def _runoff_ending_before_the_last_period() -> LoadResult:
    days = pd.date_range("2000-01-01", "2000-01-20", freq="D")
    values = np.full((days.size, 1, 1), 2.0)
    dataset = xr.Dataset(
        {"runoff": (("time", "y", "x"), values)},
        coords={"time": days, "y": [0.5], "x": [0.5]},
    )
    record = FieldRecord(
        variable="runoff",
        source="sim2",
        unit="mm/day",
        data=dataset,
        bbox=(0.0, 0.0, 1.0, 1.0),
        crs="EPSG:2154",
    )
    return LoadResult(fields=[record])


@pytest.mark.usefixtures("_fresh_warnings")
def test_a_period_without_runoff_is_a_gap_in_the_scored_discharge() -> None:
    baseflow = pd.Series([0.4, 0.7, 1.1], index=_SIM_INDEX, name="discharge")

    scored = add_runoff_to_discharge(baseflow, _context(_runoff_ending_before_the_last_period()))

    assert scored.iloc[:2].tolist() == pytest.approx([2.4, 2.7])
    assert np.isnan(scored.iloc[2])


@pytest.mark.usefixtures("_fresh_warnings")
def test_the_periods_that_lost_their_runoff_are_counted_once(caplog) -> None:
    baseflow = pd.Series([0.4, 0.7, 1.1], index=_SIM_INDEX, name="discharge")
    context = _context(_runoff_ending_before_the_last_period())

    with caplog.at_level(logging.WARNING, logger=series_module.__name__):
        add_runoff_to_discharge(baseflow, context)
        add_runoff_to_discharge(baseflow, context)

    messages = [r.getMessage() for r in caplog.records if "no runoff" in r.getMessage()]
    assert len(messages) == 1
    assert "1 of 3" in messages[0]


# From test_runoff_period_alignment.py
# The calibration path and the derived path must average runoff the same way.
#
# The runoff forcing is added to a baseflow twice in this repository: once when
# the calibration metric builds the simulated discharge it scores
# (``calibration.metrics.series.add_runoff_to_discharge``) and once when the
# catalog materializes the catchment discharge a run is read back from
# (``simulation.extraction.derivation.catchment_aggregation``). If the two align
# the daily forcing on the stress periods by different rules, a run scores against
# one discharge and reports another.


_EXPECTED_M3_PER_S = [2.0, 5.0, 9.0]


def _daily_runoff_mm() -> pd.Series:
    parts = [
        pd.Series(value, index=pd.date_range(start, end, freq="D", inclusive="left"))
        for start, end, value in (
            ("2000-01-01", "2000-01-11", 2.0),
            ("2000-01-11", "2000-01-21", 5.0),
            ("2000-01-21", "2000-03-06", 9.0),
        )
    ]
    return pd.concat(parts)


class _FakeArray:
    """Zarr-array stand-in supporting slice reads and ``.shape``."""

    def __init__(self, data) -> None:
        self._data = np.asarray(data)

    @property
    def shape(self):
        return self._data.shape

    def __getitem__(self, key):
        return self._data[key]


class _FakeNode:
    """Dict-like Zarr group node, deliberately without ``.shape``."""

    def __init__(self, mapping) -> None:
        self._mapping = mapping

    def __contains__(self, key) -> bool:
        return key in self._mapping

    def __getitem__(self, key):
        return self._mapping[key]


class _FakeRunoffGroup:
    def __init__(self, stations) -> None:
        self._stations = stations

    def array_keys(self):
        return []

    def group_keys(self):
        return list(self._stations.keys())

    def __getitem__(self, key):
        return self._stations[key]


class _FakeRootGroup:
    def __init__(self, forcing) -> None:
        self._forcing = forcing

    def get(self, key):
        return self._forcing if key == "forcing" else None


def _derived_paths_inputs(runoff: pd.Series):
    station = _FakeNode(
        {
            "values": _FakeArray(runoff.to_numpy(dtype="float64")),
            "timestamps": _FakeArray(pd.DatetimeIndex(runoff.index).values),
        }
    )
    grp = _FakeRootGroup(_FakeNode({"runoff": _FakeRunoffGroup({"station0": station})}))
    store = SimpleNamespace(read_geographic_metadata=lambda _sim_id: {"catch_area": CATCH_AREA_KM2})
    return store, grp


def _calibration_context(runoff: pd.Series):
    frame = pd.DataFrame(
        {"datetime": pd.DatetimeIndex(runoff.index), "value": runoff.to_numpy(dtype="float64")}
    )
    return SimpleNamespace(
        loaded_data=SimpleNamespace(runoff=SimpleNamespace(points=[SimpleNamespace(data=frame)])),
        setup=SimpleNamespace(geographic=SimpleNamespace(catch_area=CATCH_AREA_KM2)),
    )


def test_the_calibration_path_averages_the_forcing_over_each_stress_period() -> None:
    runoff = _daily_runoff_mm()
    baseflow = pd.Series(0.0, index=_SIM_INDEX, name="discharge")

    scored = add_runoff_to_discharge(baseflow, _calibration_context(runoff))

    assert list(scored.index) == list(_SIM_INDEX)
    assert scored.tolist() == pytest.approx(_EXPECTED_M3_PER_S)


def test_the_derived_path_averages_the_forcing_over_each_stress_period() -> None:
    runoff = _daily_runoff_mm()
    baseflow = pd.Series(0.0, index=_SIM_INDEX, name="discharge")
    store, grp = _derived_paths_inputs(runoff)

    reported = _add_runoff_to_discharge_series(baseflow, "sim-0", store=store, grp=grp)

    assert list(reported.index) == list(_SIM_INDEX)
    assert reported.tolist() == pytest.approx(_EXPECTED_M3_PER_S)


def test_what_a_run_is_scored_on_is_what_it_reports() -> None:
    runoff = _daily_runoff_mm()
    baseflow = pd.Series([0.4, 0.7, 1.1], index=_SIM_INDEX, name="discharge")
    store, grp = _derived_paths_inputs(runoff)

    scored = add_runoff_to_discharge(baseflow, _calibration_context(runoff))
    reported = _add_runoff_to_discharge_series(baseflow, "sim-0", store=store, grp=grp)

    assert scored.tolist() == pytest.approx(reported.tolist())
    assert scored.tolist() == pytest.approx([2.4, 5.7, 10.1])


def test_a_single_steady_period_is_the_mean_of_its_whole_forcing_window() -> None:
    """The index phase one of the Abherve method runs on.

    One steady stress period covering the run, and a daily forcing over it. A
    single stamp carries no spacing, so without the window start the whole
    forcing window is the period: (10*2 + 10*5 + 45*9) / 65 mm/day. A rule
    that picks the sample nearest the stamp answers 9.0 here, which is the
    failure the whole single-source fix is about, and the one an index with an
    even spacing cannot expose.
    """
    runoff = _daily_runoff_mm()
    steady = pd.DatetimeIndex(["2000-01-21"])
    baseflow = pd.Series(0.0, index=steady, name="discharge")
    store, grp = _derived_paths_inputs(runoff)

    scored = add_runoff_to_discharge(baseflow, _calibration_context(runoff))
    reported = _add_runoff_to_discharge_series(baseflow, "sim-0", store=store, grp=grp)

    expected = float(runoff.mean())
    assert expected == pytest.approx(475.0 / 65.0)
    assert scored.tolist() == pytest.approx([expected])
    assert scored.tolist() == pytest.approx(reported.tolist())


def test_a_steady_period_followed_by_short_ones_is_averaged_on_both_paths() -> None:
    """A median spacing small enough to flip a guard must not flip the rule.

    A long spin-up followed by short transient periods is what a staged
    calibration produces, and it is the index on which a rule keyed on the
    MEDIAN spacing sends every period, the long one included, to the nearest
    sample.
    """
    runoff = _daily_runoff_mm()
    mixed = pd.DatetimeIndex(["2000-01-20", "2000-02-25", "2000-02-27", "2000-02-29", "2000-03-02"])
    baseflow = pd.Series(0.0, index=mixed, name="discharge")
    store, grp = _derived_paths_inputs(runoff)

    scored = add_runoff_to_discharge(baseflow, _calibration_context(runoff))
    reported = _add_runoff_to_discharge_series(baseflow, "sim-0", store=store, grp=grp)

    assert scored.tolist() == pytest.approx(reported.tolist())
    # The first period reaches back over the 2 mm/day block and the 5 mm/day
    # one, so its mean is strictly between them and is not the 5.0 the stamp
    # sits on.
    assert 2.0 < scored.iloc[0] < 5.0
    # The short periods sit inside the 9 mm/day block.
    assert scored.iloc[-1] == pytest.approx(9.0)


def test_a_single_steady_period_with_its_start_averages_its_own_window() -> None:
    """With the run window start, the steady period is [start, stamp) only.

    The window [2000-01-11, 2000-01-21) holds the 5 mm/day block alone. Both
    paths receive the start: the calibration one from the time grid, the
    derived one from the catalog.
    """
    runoff = _daily_runoff_mm()
    steady = pd.DatetimeIndex(["2000-01-21"])
    baseflow = pd.Series(0.0, index=steady, name="discharge")
    store, grp = _derived_paths_inputs(runoff)
    ctx = _calibration_context(runoff)
    ctx.setup.time_grid = SimpleNamespace(
        boundaries=(pd.Timestamp("2000-01-11"), pd.Timestamp("2000-01-21"))
    )

    scored = add_runoff_to_discharge(baseflow, ctx)
    reported = _add_runoff_to_discharge_series(
        baseflow, "sim-0", store=store, grp=grp, start=pd.Timestamp("2000-01-11")
    )

    assert scored.tolist() == pytest.approx([5.0])
    assert reported.tolist() == pytest.approx([5.0])


# From test_the_calibration_discharge_adds_the_soil_runoff.py
# In soil mode, the calibration discharge reads the soil's own runoff.
#
# The soil reservoir always hands back a runoff ``LoadResult`` (zero when
# ``impervious_fraction`` is 0), so the calibration must add that one instead of
# whatever ``[data.types]`` happened to load, and never warns "Add 'runoff'" in
# soil mode: R2 forbids ``[data.runoff]`` there in the first place.


def _gridded_runoff__calibration_discharge(base_value: float) -> LoadResult:
    """A daily, single-cell runoff grid holding ``base_value`` mm/day."""
    days = pd.date_range("2000-01-01", "2000-03-05", freq="D")
    values = np.full((days.size, 1, 1), base_value)
    dataset = xr.Dataset(
        {"runoff": (("time", "y", "x"), values)},
        coords={"time": days, "y": [0.0], "x": [0.0]},
    )
    record = FieldRecord(
        variable="runoff",
        source="soil_reservoir",
        unit="mm/day",
        data=dataset,
        bbox=(0.0, 0.0, 1.0, 1.0),
        crs="EPSG:2154",
    )
    return LoadResult(fields=[record])


def _context__calibration_discharge(
    *, loaded_runoff: LoadResult | None, soil_runoff: LoadResult | None
) -> SimpleNamespace:
    soil = SimpleNamespace(runoff=soil_runoff) if soil_runoff is not None else None
    return SimpleNamespace(
        loaded_data=SimpleNamespace(runoff=loaded_runoff),
        setup=SimpleNamespace(
            geographic=SimpleNamespace(catch_area=CATCH_AREA_KM2),
            soil_forcings=soil,
        ),
    )


@pytest.fixture()
def _fresh_warnings__calibration_discharge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(series_module, "_RUNOFF_WARNING_EMITTED", set())


@pytest.mark.usefixtures("_fresh_warnings__calibration_discharge")
def test_the_soil_runoff_is_added_instead_of_the_loaded_one() -> None:
    baseflow = pd.Series(0.0, index=_SIM_INDEX, name="discharge")
    ctx = _context__calibration_discharge(
        loaded_runoff=None, soil_runoff=_gridded_runoff__calibration_discharge(1.0)
    )

    scored = add_runoff_to_discharge(baseflow, ctx)

    assert scored.tolist() == pytest.approx([1.0, 1.0, 1.0])


@pytest.mark.usefixtures("_fresh_warnings__calibration_discharge")
def test_no_add_runoff_warning_fires_in_soil_mode(caplog: pytest.LogCaptureFixture) -> None:
    baseflow = pd.Series([0.4, 0.7, 1.1], index=_SIM_INDEX, name="discharge")
    ctx = _context__calibration_discharge(
        loaded_runoff=None, soil_runoff=_gridded_runoff__calibration_discharge(2.0)
    )

    with caplog.at_level(logging.WARNING, logger=series_module.__name__):
        add_runoff_to_discharge(baseflow, ctx)

    assert not [r for r in caplog.records if "runoff" in r.getMessage().lower()]


@pytest.mark.usefixtures("_fresh_warnings__calibration_discharge")
def test_without_soil_forcings_the_loaded_runoff_is_used_as_before() -> None:
    baseflow = pd.Series(0.0, index=_SIM_INDEX, name="discharge")
    ctx = _context__calibration_discharge(
        loaded_runoff=_gridded_runoff__calibration_discharge(3.0), soil_runoff=None
    )

    scored = add_runoff_to_discharge(baseflow, ctx)

    assert scored.tolist() == pytest.approx([3.0, 3.0, 3.0])


# From test_two_trials_scored_discharge_differs_by_curve_number.py
# Two trials with different ``curve_number`` are scored differently.
#
# Mirrors ``test_metrics_series.py``:
# a calibration trial rebuilds its own ``SoilForcings`` from its own config
# (``_RECHARGE_PREFIX`` already covers every field under
# ``flow.sinks_sources.recharge.soil``, ``curve_number`` and ``runoff_time``
# included), and ``add_runoff_to_discharge`` reads
# ``ctx.setup.soil_forcings.runoff``, which now carries the routed
# curve-number share along with the sealed one. Two ``compute_soil_forcings``
# calls that differ only in ``curve_number``, piped the same way a trial's own
# context would be, prove the trial recomputation path reaches the new term.


def _runoff(forcings) -> np.ndarray:
    return forcings.runoff.fields[0].data["runoff"].to_numpy()


def test_each_trial_recomputes_its_own_curve_number_runoff() -> None:
    off_runoff = _runoff(soil_forcings(curve_number=None, runoff_time=0.0))
    on_runoff = _runoff(soil_forcings(curve_number=85.0, runoff_time=0.0))

    assert off_runoff == pytest.approx(0.0)
    assert np.all(on_runoff > 0.0)


def test_two_trials_get_different_scored_discharge_by_curve_number() -> None:
    low_discharge = scored_discharge(soil_forcings(curve_number=70.0, runoff_time=0.0))
    high_discharge = scored_discharge(soil_forcings(curve_number=90.0, runoff_time=0.0))

    assert not np.allclose(low_discharge.to_numpy(), high_discharge.to_numpy())


# From test_two_trials_scored_discharge_differs_by_impervious_runoff.py
# Two trials with different ``impervious_fraction`` are scored differently.
#
# A calibration trial rebuilds its own ``SoilForcings`` from its own config
# (``TrialContext.fork`` calls ``apply_structural_updates_from_data``, which
# calls ``compute_soil_forcings`` on the patched ``cfg.flow``), the same way it
# already does for ``ru``. ``add_runoff_to_discharge`` -- the function
# ``composite.py`` calls once per trial, never twice -- then reads
# ``ctx.setup.soil_forcings.runoff`` and adds it to the scored discharge.
#
# This test exercises that chain with a tiny synthetic soil case instead of a
# full MODFLOW run: two ``compute_soil_forcings`` calls that differ only in
# ``impervious_fraction``, each piped through ``add_runoff_to_discharge`` the
# way a trial's own context would be. The expected volume is exact because the
# kernel's runoff is ``impervious_fraction * precipitation``
# (``hydromodpy/physics/hydrology/soil_reservoir/kernel.py``), so a constant
# rain and a known area give a closed-form discharge difference.


def test_each_trial_recomputes_its_own_runoff() -> None:
    low_runoff = _runoff(soil_forcings(rain=10.0, impervious_fraction=0.0))
    high_runoff = _runoff(soil_forcings(rain=10.0, impervious_fraction=0.08))

    assert low_runoff == pytest.approx(0.0)
    assert high_runoff == pytest.approx(0.08 * 10.0)


def test_two_trials_get_different_scored_discharge_by_the_expected_volume() -> None:
    low_discharge = scored_discharge(soil_forcings(rain=10.0, impervious_fraction=0.0))
    high_discharge = scored_discharge(soil_forcings(rain=10.0, impervious_fraction=0.08))

    delta = high_discharge - low_discharge
    # 0.08 x 10 mm/day sealed runoff, over 86.4 km2, is 0.8 m3/s: the exact
    # volume the impervious fraction alone adds, added once.
    expected_m3_per_s = 0.08 * 10.0 * 1e-3 * (CATCH_AREA_KM2 * 1e6) / 86400.0
    assert delta.to_numpy() == pytest.approx(expected_m3_per_s)


# From test_two_trials_scored_discharge_differs_by_runoff_lag.py
# Two trials with different ``runoff_lag`` are scored differently.
#
# Mirrors ``test_metrics_series.py``: a
# calibration trial rebuilds its own ``SoilForcings`` from its own config, and
# ``add_runoff_to_discharge`` reads ``ctx.setup.soil_forcings.runoff``, which
# now carries the delayed curve-number share. Two ``compute_soil_forcings``
# calls that differ only in ``runoff_lag``, piped the same way a trial's own
# context would be, prove the trial recomputation path reaches the new term.


def _lagged(runoff_lag: float):
    return soil_forcings(pulsed=True, curve_number=85.0, runoff_time=0.0, runoff_lag=runoff_lag)


def test_each_trial_recomputes_its_own_runoff_lag() -> None:
    assert not np.allclose(_runoff(_lagged(0.0)), _runoff(_lagged(3.0)))


def test_two_trials_get_different_scored_discharge_by_runoff_lag() -> None:
    unlagged_discharge = scored_discharge(_lagged(0.0))
    lagged_discharge = scored_discharge(_lagged(3.0))

    assert not np.allclose(unlagged_discharge.to_numpy(), lagged_discharge.to_numpy())
