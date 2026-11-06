"""Tests of `metrics.series`."""

from __future__ import annotations

import inspect
import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.calibration.config import (
    CalibAggregateDecl,
    CalibObjectiveBlockDecl,
    CalibOutputPoint,
    CalibrationConfig,
    validate_calib_output,
)
from hydromodpy.calibration.metrics import series as series_module
from hydromodpy.calibration.metrics.observable_scoring import ObservableScorer, StationBlockScorer
from hydromodpy.calibration.metrics.observed_pairing import (
    observed_series_for_outputs,
    pair_outputs_with_observations,
)
from hydromodpy.calibration.metrics.series import ObservedSeries, add_runoff_to_discharge
from hydromodpy.calibration.metrics.trial_series_capture import TrialSeriesSink
from hydromodpy.calibration.runners import pipeline_evaluator
from hydromodpy.calibration.runners.pipeline_evaluator import PipelineTrialEvaluator
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.core.time.period_aggregation import period_edges
from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.results.derive.time_alignment import align_observed_simulated
from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
    _add_runoff_to_discharge_series,
)
from hydromodpy.simulation.soil_recharge import compute_soil_forcings
from hydromodpy.workflow.steps.prepare_solver.forcings import watershed_mean_series
from tests.unit.calibration._factories_scoring import (
    CATCH_AREA_KM2,
    adapter_result,
    objective_block,
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
    persisted = watershed_mean_series(runoff)
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


# A daily forcing whose period means are not round, so the last digit shows.
_ROUGH_DAYS = pd.date_range("2000-01-01", "2000-03-05", freq="D")
_ROUGH_RUNOFF = pd.Series(1.37 + 0.11 * (np.arange(_ROUGH_DAYS.size) % 5), index=_ROUGH_DAYS)
_STEADY = pd.DatetimeIndex(["2000-01-21"])
_ROUGH_START = pd.Timestamp("2000-01-03")


def _both_writings(runoff, index, start, area_m2):
    """The discharge a trial scores and the one a run reports, on one baseflow."""
    baseflow = pd.Series([0.4, 0.7, 1.1][: len(index)], index=index, name="discharge")
    store, grp = _derived_paths_inputs(runoff)
    ctx = _calibration_context(runoff)
    if start is not None:
        ctx.setup.time_grid = SimpleNamespace(boundaries=(start, index[-1]))
    scored = add_runoff_to_discharge(baseflow, ctx, area_m2=area_m2)
    # A nested gauge is a trial's business: the run reports the whole catchment.
    reported = _add_runoff_to_discharge_series(baseflow, "sim-0", store=store, grp=grp, start=start)
    return scored, reported


@pytest.mark.parametrize(
    ("runoff", "index", "start", "area_m2", "expected"),
    [
        # Values printed by the two separate writings of ad9c089a9, which agreed.
        (_ROUGH_RUNOFF, _SIM_INDEX, None, None, [1.9900000000000002, 2.29, 2.6900000000000004]),
        (_ROUGH_RUNOFF, _SIM_INDEX, _ROUGH_START, None, [2.03125, 2.29, 2.6900000000000004]),
        # A nested gauge: the writing of the trial, the only one that took an area.
        # The run reports the whole catchment, so the last assertion skips it.
        (
            _ROUGH_RUNOFF,
            _SIM_INDEX,
            None,
            3.3e7,
            [1.0072916666666667, 1.3072916666666667, 1.7072916666666669],
        ),
        # Each period is averaged, by hand 2 + 0.4, 5 + 0.7 and 9 + 1.1.
        (_daily_runoff_mm(), _SIM_INDEX, None, None, [2.4, 5.7, 10.100000000000001]),
        # One steady period without a start is its whole forcing window, by hand
        # (10*2 + 10*5 + 45*9) / 65 + 0.4. The sample nearest the stamp would give 9.4.
        (_daily_runoff_mm(), _STEADY, None, None, [7.707692307692308]),
        # With the run window start it is that window only: the 5 mm/day block.
        (_daily_runoff_mm(), _STEADY, pd.Timestamp("2000-01-11"), None, [5.4]),
    ],
)
def test_the_merge_moves_no_number_to_the_last_digit(
    runoff, index, start, area_m2, expected
) -> None:
    scored, reported = _both_writings(runoff, index, start, area_m2)

    assert scored.index.equals(index)
    np.testing.assert_array_equal(scored.to_numpy(), expected)
    if area_m2 is None:
        np.testing.assert_array_equal(reported.to_numpy(), expected)


def test_a_period_without_runoff_is_a_gap_in_the_trial_and_in_the_run() -> None:
    """Baseflow alone is no total discharge, so a run publishes no number a trial would drop."""
    index = pd.DatetimeIndex(["2000-03-01", "2000-04-01", "2000-05-01"])

    scored, reported = _both_writings(_ROUGH_RUNOFF, index, None, None)

    np.testing.assert_array_equal(scored, reported)
    assert np.isnan(reported.iloc[2])
    assert not reported.iloc[:2].isna().any()


def test_a_gauge_area_that_is_not_positive_is_refused_not_skipped() -> None:
    baseflow = pd.Series(0.0, index=_SIM_INDEX)

    with pytest.raises(ValueError, match="must be positive, got 0.0 m2"):
        add_runoff_to_discharge(baseflow, _calibration_context(_ROUGH_RUNOFF), area_m2=0.0)


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


# The readers of the loaded data and of the time grid, on the records they skip.


def _station(values, *, tz=None, name="S1") -> SimpleNamespace:
    stamps = pd.date_range("2000-01-01", periods=len(values), freq="D", tz=tz)
    data = pd.DataFrame({"datetime": stamps, "value": values})
    return SimpleNamespace(station_id=name, variable="discharge", data=data)


def test_load_observed_keeps_the_dated_records_and_skips_the_others() -> None:
    skipped = [
        SimpleNamespace(station_id="none", variable="discharge", data=None),
        SimpleNamespace(station_id="empty", variable="discharge", data=pd.DataFrame()),
        SimpleNamespace(station_id="broken", variable="discharge", data=pd.DataFrame({"x": [1]})),
    ]
    ctx = SimpleNamespace(
        loaded_data=SimpleNamespace(
            hydrometry=SimpleNamespace(points=[*skipped, _station([1.0, 2.0], tz="UTC")])
        )
    )

    (kept,) = series_module.load_observed(ctx, "discharge")

    assert kept.station_id == "S1"
    assert kept.series.index.tolist() == [pd.Timestamp("2000-01-01"), pd.Timestamp("2000-01-02")]
    assert kept.series.tolist() == [1.0, 2.0]


@pytest.mark.parametrize(
    ("setup", "n_timesteps", "expected"),
    [
        (None, 0, None),
        (SimpleNamespace(time_grid=SimpleNamespace(boundaries=["2000-01-01"])), 0, None),
        (SimpleNamespace(time_grid=SimpleNamespace(boundaries=["a", "b"])), 0, None),
        (
            SimpleNamespace(
                time_grid=SimpleNamespace(boundaries=["2000-01-01", "2000-01-11", "2000-01-21"])
            ),
            1,
            ["2000-01-11"],
        ),
    ],
)
def test_the_time_index_is_the_stamps_that_close_the_periods(setup, n_timesteps, expected) -> None:
    index = series_module.resolve_time_index(SimpleNamespace(setup=setup), n_timesteps)

    assert (index if index is None else index.strftime("%Y-%m-%d").tolist()) == expected


def test_the_station_runoff_is_the_mean_of_the_dated_stations() -> None:
    points = [
        SimpleNamespace(data=None),
        SimpleNamespace(data=pd.DataFrame()),
        _station([2.0, 4.0], tz="UTC"),
        _station([4.0, 8.0]),
    ]

    mean = series_module._station_runoff_mm_per_day(points)

    assert mean.tolist() == [3.0, 6.0]
    assert series_module._station_runoff_mm_per_day(points[:2]) is None


@pytest.mark.parametrize(
    ("reduced", "expected"),
    [(None, None), (pd.Series(dtype=float), None), ("utc", [1.0, 2.0])],
)
def test_the_gridded_runoff_is_a_naive_utc_series_or_nothing(
    monkeypatch, reduced, expected
) -> None:
    if isinstance(reduced, str):
        reduced = pd.Series([1.0, 2.0], index=pd.date_range("2000-01-01", periods=2, tz="UTC"))
    monkeypatch.setattr(series_module, "spatial_mean_from_fields", lambda _runoff: reduced)

    result = series_module._gridded_runoff_mm_per_day(object())

    assert result is None if expected is None else result.tolist() == expected
    if expected:
        assert result.index.tz is None


def test_a_baseflow_is_returned_alone_when_the_runoff_cannot_be_added(monkeypatch) -> None:
    simulated = pd.Series([1.0], index=pd.DatetimeIndex(["2000-01-02"]))
    no_area = SimpleNamespace(
        loaded_data=SimpleNamespace(runoff=SimpleNamespace(points=[_station([5.0])], fields=None)),
        setup=SimpleNamespace(geographic=SimpleNamespace(catch_area=0.0)),
    )
    ungridded = SimpleNamespace(
        loaded_data=SimpleNamespace(runoff=SimpleNamespace(points=None, fields=[object()])),
        setup=SimpleNamespace(geographic=SimpleNamespace(catch_area=1.0)),
    )
    monkeypatch.setattr(series_module, "spatial_mean_from_fields", lambda _runoff: None)

    assert add_runoff_to_discharge(simulated, no_area) is simulated
    assert add_runoff_to_discharge(simulated, ungridded) is simulated


# ---------------------------------------------------------------------------
# metrics_observed_pairing
# Tests of `metrics.observed_pairing`.
# ---------------------------------------------------------------------------

# From test_the_aggregation_is_declared.py
# How several targets become one cost: the fewest pairs a member is scored on.
#
# ``weighting``, ``nested_gauges`` and ``on_member_failure`` were declared here
# and never read, so a file that wrote ``weighting = "error"`` or
# ``on_member_failure = "drop"`` got the same cost as one that did not. They
# are refused, and ``hmp doctor --fix-config`` deletes them.


def _config(aggregate: dict[str, object], **over: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "parameters": {"K": {"bounds": [1e-8, 1e-2]}},
        "outputs": {
            "q": {
                "variable": "discharge",
                "support": "boundary",
                "boundary_id": "outlet",
                "observes": "J7branch",
            }
        },
        "objective_blocks": [{"name": "flows", "metric": "rmse", "uses_outputs": ["q"]}],
        "aggregate": aggregate,
    }
    payload.update(over)
    return payload


class TestTheDefaults:
    def test_one_pair_is_enough_by_default(self) -> None:
        assert CalibAggregateDecl().min_samples == 1

    def test_a_calibration_carries_one_by_default(self) -> None:
        cfg = CalibrationConfig.model_validate({"parameters": {"K": {"bounds": [1e-8, 1e-2]}}})

        assert cfg.aggregate.min_samples == 1


class TestTheRefusedKeys:
    @pytest.mark.parametrize(
        ("key", "value"),
        [("weighting", "error"), ("nested_gauges", "incremental"), ("on_member_failure", "drop")],
    )
    def test_an_aggregate_key_nothing_read_is_refused(self, key: str, value: str) -> None:
        with pytest.raises(ValueError, match=rf"'{key}' is not accepted any more.*deletes it"):
            CalibrationConfig.model_validate(_config({key: value}))

        assert key not in CalibAggregateDecl.model_fields

    @pytest.mark.parametrize(
        "key", ["lightweight_extraction", "persist_model_distribution", "persistence"]
    )
    def test_a_section_key_nothing_read_is_refused(self, key: str) -> None:
        with pytest.raises(ValueError, match=rf"'{key}' is not accepted any more.*deletes it"):
            CalibrationConfig.model_validate({key: True})

        assert key not in CalibrationConfig.model_fields


class TestWhatItRefuses:
    def test_a_min_samples_below_one_is_refused(self) -> None:
        with pytest.raises(ValueError):
            CalibrationConfig.model_validate(_config({"min_samples": 0}))


class TestMinSamplesReachesThePairing:
    def test_an_overlap_below_the_floor_is_refused_by_name(self) -> None:
        times = pd.date_range("2000-01-01", periods=3, freq="D")
        with pytest.raises(ValueError, match="min_samples"):
            pair_outputs_with_observations(
                observed={"q": pd.Series([1.0, 2.0, 3.0], index=times)},
                simulated={"q": pd.Series([1.1, 2.1, 3.1], index=times)},
                min_samples=10,
            )

    def test_an_overlap_at_the_floor_is_accepted(self) -> None:
        # Each simulated stamp closes the day observed one day before it.
        paired = pair_outputs_with_observations(
            observed={
                "q": pd.Series([1.0, 2.0, 3.0], index=pd.date_range("1999-12-31", periods=3))
            },
            simulated={
                "q": pd.Series([1.1, 2.1, 3.1], index=pd.date_range("2000-01-01", periods=3))
            },
            min_samples=3,
        )

        assert paired.n_paired["q"] == 3

    def test_the_evaluator_forwards_what_the_file_declared(self) -> None:
        """Where the metric extractor is built is where the declaration is read.

        It is built by the evaluator that runs the pipeline, because building it
        needs that evaluator's trial context.
        """

        source = inspect.getsource(pipeline_evaluator._extractor_for)

        assert "min_samples=int(cfg.aggregate.min_samples)" in source


def test_an_output_on_a_variable_with_no_observed_family_is_refused() -> None:
    outputs = {"x": SimpleNamespace(observes="S1", variable="porosity")}

    with pytest.raises(ValueError, match="output 'x' observes 'S1' but its variable 'porosity'"):
        observed_series_for_outputs(outputs, SimpleNamespace())


def test_a_record_with_no_dated_sample_has_no_span_to_name() -> None:
    times = pd.date_range("2000-01-01", periods=2, freq="D")

    with pytest.raises(ValueError, match="the record runs over no dated sample"):
        pair_outputs_with_observations(
            observed={"q": pd.Series(dtype=float)},
            simulated={"q": pd.Series([1.0, 2.0], index=times)},
        )


def test_two_outputs_on_one_family_load_its_records_once() -> None:
    records = [
        SimpleNamespace(
            station_id=name,
            variable="discharge",
            data=pd.DataFrame({"datetime": pd.to_datetime(["2000-01-01"]), "value": [value]}),
        )
        for name, value in (("A", 1.0), ("B", 2.0))
    ]
    ctx = SimpleNamespace(loaded_data=SimpleNamespace(hydrometry=SimpleNamespace(points=records)))
    outputs = {
        "qa": SimpleNamespace(observes="A", variable="discharge"),
        "qb": SimpleNamespace(observes="B", variable="discharge"),
    }

    series = observed_series_for_outputs(outputs, ctx)

    assert {name: values.tolist() for name, values in series.items()} == {"qa": [1.0], "qb": [2.0]}


# ---------------------------------------------------------------------------
# metrics_trial_series_capture
# Tests of `metrics.trial_series_capture`.
# ---------------------------------------------------------------------------

# From test_persist_trial_series.py
# persist_trial_series: opt-in, off by default, and a real capture at scoring time.
#
# Three layers are covered without a solver, the way
# ``test_metrics_observable_scoring.py`` scores
# both routes on a synthetic series:
#
# 1. The key defaults off.
# 2. :class:`TrialSeriesSink` records and drains, per thread.
# 3. Both forms of a cost (``variable`` + ``objective`` through
#    ``StationBlockScorer``, declared blocks through ``ObservableScorer``) record
#    into a sink they are built with, as a side effect of scoring the same series
#    they already align to compute a cost.
# 4. :class:`PipelineTrialEvaluator` creates a sink only when the key is on, and
#    only when it builds its own extractor: a caller-supplied ``metric_fn`` never
#    sees one.


STATION = "G1"
TIMES = pd.date_range("2001-01-31", periods=4, freq="ME")
BOUNDARIES = period_edges(TIMES, start=pd.Timestamp("2000-12-31"))
OBSERVED = pd.Series([1.0, 2.0, 3.0, 4.0], index=TIMES, name=STATION)
SIMULATED = OBSERVED.to_numpy() * 0.9 + 0.1

# Ground truth: the same alignment both scorers reduce to a cost from, so the
# sink is checked against what was actually scored, not a re-guessed index.
EXPECTED_PAIR = align_observed_simulated(
    OBSERVED, pd.Series(SIMULATED, index=TIMES), method="mean", start=BOUNDARIES[0]
)


def test_the_key_defaults_off() -> None:
    assert CalibrationConfig().persist_trial_series is False


def test_a_sink_drains_only_what_was_recorded_on_the_calling_thread() -> None:
    sink = TrialSeriesSink()
    sink.record(
        output="q", station=STATION, times=TIMES[:2], simulated=[1.0, 2.0], observed=[1.1, 2.1]
    )

    rows = sink.drain()

    assert len(rows) == 2
    assert rows[0] == {
        "output": "q",
        "station": STATION,
        "time": TIMES[0],
        "simulated": 1.0,
        "observed": 1.1,
    }
    # Drained: a second call sees nothing left over from the first.
    assert sink.drain() == []


def test_variable_and_objective_record_the_series_they_scored() -> None:
    sink = TrialSeriesSink()
    scorer = StationBlockScorer(
        "discharge",
        "nse_log",
        [ObservedSeries(station_id=STATION, variable="discharge", series=OBSERVED)],
        series_sink=sink,
    )

    scorer.score(
        {STATION: adapter_result(STATION, SIMULATED, "m3 s-1", times=TIMES)},
        boundaries=BOUNDARIES,
    )

    rows = sink.drain()
    # One edge sample does not close a period on this boundary set (same
    # alignment ``test_metrics_observable_scoring``
    # notes): 3 of the 4 stamps are the ones actually scored.
    assert [row["station"] for row in rows] == [STATION] * len(EXPECTED_PAIR)
    assert [row["output"] for row in rows] == [f"discharge@{STATION}"] * len(EXPECTED_PAIR)
    assert [row["time"] for row in rows] == list(EXPECTED_PAIR.index)
    np.testing.assert_allclose([row["simulated"] for row in rows], EXPECTED_PAIR["sim"])
    np.testing.assert_allclose([row["observed"] for row in rows], EXPECTED_PAIR["obs"])


def test_the_composite_route_records_the_series_keyed_by_output_and_station() -> None:
    sink = TrialSeriesSink()
    output = CalibOutputPoint.model_validate(
        {"variable": "discharge", "support": "point", "observes": STATION}
    )
    block = objective_block("hydrograph", "nse_log", ["gauge"])
    scorer = ObservableScorer(
        {"gauge": output}, [block], observed_records={"gauge": OBSERVED}, series_sink=sink
    )

    scorer.score(
        {"gauge": adapter_result("gauge", SIMULATED, "m3 s-1", times=TIMES)},
        boundaries=BOUNDARIES,
    )

    rows = sink.drain()
    assert [row["output"] for row in rows] == ["gauge"] * len(EXPECTED_PAIR)
    assert [row["station"] for row in rows] == [STATION] * len(EXPECTED_PAIR)
    assert [row["time"] for row in rows] == list(EXPECTED_PAIR.index)
    np.testing.assert_allclose([row["simulated"] for row in rows], EXPECTED_PAIR["sim"])
    np.testing.assert_allclose([row["observed"] for row in rows], EXPECTED_PAIR["obs"])


def test_a_network_output_never_reaches_the_sink() -> None:
    sink = TrialSeriesSink()
    output = validate_calib_output({"support": "network", "map": {"complete": "data.hydrography"}})
    block = objective_block("net", "distance_gap", ["net"])
    scorer = ObservableScorer({"net": output}, [block], series_sink=sink)

    scorer.score({}, network_values={"net": [12.0, 20.0]})

    assert sink.drain() == []


class TestThePipelineEvaluatorWiring:
    def test_a_sink_is_built_only_when_the_key_is_on(self) -> None:
        on = CalibrationConfig.model_validate({"persist_trial_series": True})
        off = CalibrationConfig()
        metric_fn = lambda ctx, **kwargs: (0.0, {})  # noqa: E731 - bypasses _extractor_for

        evaluator_on = PipelineTrialEvaluator(cfg=on, trial_ctx=object(), metric_fn=metric_fn)
        evaluator_off = PipelineTrialEvaluator(cfg=off, trial_ctx=object(), metric_fn=metric_fn)

        assert isinstance(evaluator_on.trial_series_sink, TrialSeriesSink)
        assert evaluator_off.trial_series_sink is None

    def test_a_caller_supplied_metric_fn_is_used_as_is_not_wrapped(self) -> None:
        on = CalibrationConfig.model_validate({"persist_trial_series": True})
        metric_fn = lambda ctx, **kwargs: (0.0, {})  # noqa: E731

        evaluator = PipelineTrialEvaluator(cfg=on, trial_ctx=object(), metric_fn=metric_fn)

        # A sink exists (read by the caller after evaluate()), but building the
        # extractor that would feed it is skipped: the caller's own callable runs
        # unmodified, so it never has to know the sink exists.
        assert isinstance(evaluator.trial_series_sink, TrialSeriesSink)
        assert evaluator._metric_fn is metric_fn
