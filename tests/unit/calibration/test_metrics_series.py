"""Simulated discharge scored against observations, on one stress-period grid.

Adds the runoff forcing (mm/day, over a catchment area in m2) to the baseflow (m3/s)
the same way a stored run does. Also covers the readers of the observed records and
of the time grid.
"""

from __future__ import annotations

import inspect
import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.calibration.metrics import series as series_module
from hydromodpy.calibration.metrics.series import add_runoff_to_discharge
from hydromodpy.calibration.runners import pipeline_evaluator
from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.results.derive.catchment_aggregation import with_runoff
from hydromodpy.workflow.steps.prepare_solver.forcings import watershed_mean_series
from tests.unit.calibration._factories_scoring import (
    CATCH_AREA_KM2,
    scored_discharge,
    soil_forcings,
)

# 1 mm/day over 86.4 km2 is exactly 1 m3/s: 1e-3 * 8.64e7 / 86400.
SIM_INDEX = pd.DatetimeIndex(["2000-01-11", "2000-01-21", "2000-02-20"])
BASEFLOW = [0.4, 0.7, 1.1]  # m3/s


def runoff_grid(days, values, *, source="sim2") -> LoadResult:
    """Runoff in mm/day, values shaped (time, y, x), on cells one unit wide."""
    n_y, n_x = values.shape[1:]
    dataset = xr.Dataset(
        {"runoff": (("time", "y", "x"), values)},
        coords={"time": days, "y": np.arange(n_y)[::-1] + 0.5, "x": np.arange(n_x) + 0.5},
    )
    record = FieldRecord(
        variable="runoff",
        source=source,
        unit="mm/day",
        data=dataset,
        bbox=(0.0, 0.0, float(n_x), float(n_y)),
        crs="EPSG:2154",
    )
    return LoadResult(fields=[record])


def gridded_runoff() -> LoadResult:
    # Cells hold base + (0, 1, 2, 3) mm/day, so the mean is base + 1.5.
    # The base is 2, 5 and 9 mm/day on the three periods.
    days = pd.date_range("2000-01-01", "2000-03-05", freq="D")
    base = np.where(days < "2000-01-11", 2.0, np.where(days < "2000-01-21", 5.0, 9.0))
    offsets = np.array([[0.0, 1.0], [2.0, 3.0]])
    return runoff_grid(days, base[:, None, None] + offsets[None, :, :])


def short_runoff() -> LoadResult:
    """A uniform 2 mm/day that stops before the last period."""
    days = pd.date_range("2000-01-01", "2000-01-20", freq="D")
    return runoff_grid(days, np.full((days.size, 1, 1), 2.0))


def uniform_runoff(mm_per_day: float) -> LoadResult:
    days = pd.date_range("2000-01-01", "2000-03-05", freq="D")
    return runoff_grid(days, np.full((days.size, 1, 1), mm_per_day), source="soil_reservoir")


def context(runoff: LoadResult) -> SimpleNamespace:
    return SimpleNamespace(
        loaded_data=SimpleNamespace(runoff=runoff),
        setup=SimpleNamespace(geographic=SimpleNamespace(catch_area=CATCH_AREA_KM2)),
    )


def soil_context(*, loaded_runoff, soil_runoff) -> SimpleNamespace:
    ctx = context(loaded_runoff)
    ctx.setup.soil_forcings = None if soil_runoff is None else SimpleNamespace(runoff=soil_runoff)
    return ctx


def point_context(runoff: pd.Series) -> SimpleNamespace:
    """A project whose runoff is a daily station record (mm/day)."""
    frame = pd.DataFrame(
        {"datetime": pd.DatetimeIndex(runoff.index), "value": runoff.to_numpy(dtype="float64")}
    )
    return SimpleNamespace(
        loaded_data=SimpleNamespace(runoff=SimpleNamespace(points=[SimpleNamespace(data=frame)])),
        setup=SimpleNamespace(geographic=SimpleNamespace(catch_area=CATCH_AREA_KM2)),
    )


class ArrayStub:
    def __init__(self, data) -> None:
        self._data = np.asarray(data)

    @property
    def shape(self):
        return self._data.shape

    def __getitem__(self, key):
        return self._data[key]


class NodeStub:
    def __init__(self, mapping) -> None:
        self._mapping = mapping

    def __contains__(self, key) -> bool:
        return key in self._mapping

    def __getitem__(self, key):
        return self._mapping[key]

    def get(self, key):
        return self._mapping.get(key)


class StationGroupStub:
    def __init__(self, stations) -> None:
        self._stations = stations

    def array_keys(self):
        return []

    def group_keys(self):
        return list(self._stations)

    def __getitem__(self, key):
        return self._stations[key]


def stored_run(runoff_mm: pd.Series):
    """The fields store a run persists for a daily runoff series, and its catalog."""
    station = NodeStub(
        {
            "values": ArrayStub(runoff_mm.to_numpy(dtype="float64")),
            "timestamps": ArrayStub(pd.DatetimeIndex(runoff_mm.index).values),
        }
    )
    grp = NodeStub({"forcing": NodeStub({"runoff": StationGroupStub({"catchment": station})})})
    store = SimpleNamespace(read_geographic_metadata=lambda _sim_id: {"catch_area": CATCH_AREA_KM2})
    return store, grp


def stepped_runoff() -> pd.Series:
    """Daily runoff at 2, 5 then 9 mm/day over 2000-01-01 to 2000-03-05."""
    parts = [
        pd.Series(value, index=pd.date_range(start, end, freq="D", inclusive="left"))
        for start, end, value in (
            ("2000-01-01", "2000-01-11", 2.0),
            ("2000-01-11", "2000-01-21", 5.0),
            ("2000-01-21", "2000-03-06", 9.0),
        )
    ]
    return pd.concat(parts)


# A daily forcing whose period means are not round, so the last digit shows.
ROUGH_DAYS = pd.date_range("2000-01-01", "2000-03-05", freq="D")
ROUGH_RUNOFF = pd.Series(1.37 + 0.11 * (np.arange(ROUGH_DAYS.size) % 5), index=ROUGH_DAYS)


SCORED_RUNOFF = [
    pytest.param(None, [3.5, 6.5, 10.5], id="whole catchment"),
    pytest.param(CATCH_AREA_KM2 * 1e6 / 2.0, [1.75, 3.25, 5.25], id="gauge draining half"),
]


@pytest.mark.parametrize(("area_m2", "expected"), SCORED_RUNOFF)
def test_gridded_runoff_added(area_m2, expected) -> None:
    # Watershed mean 3.5, 6.5, 10.5 mm/day, 1 mm/day over 86.4 km2 is 1 m3/s.
    baseflow = pd.Series(0.0, index=SIM_INDEX, name="discharge")

    scored = add_runoff_to_discharge(baseflow, context(gridded_runoff()), area_m2=area_m2)

    assert scored.tolist() == pytest.approx(expected)


def test_scored_like_the_run_report(caplog) -> None:
    runoff = gridded_runoff()
    baseflow = pd.Series(BASEFLOW, index=SIM_INDEX, name="discharge")
    store, grp = stored_run(watershed_mean_series(runoff))

    with caplog.at_level(logging.WARNING, logger=series_module.__name__):
        scored = add_runoff_to_discharge(baseflow, context(runoff))
    reported = with_runoff(baseflow, "sim-0", store=store, grp=grp)

    assert scored.tolist() == pytest.approx(reported.tolist())
    assert scored.tolist() == pytest.approx([3.9, 7.2, 11.6])
    assert not [r for r in caplog.records if "no runoff" in r.getMessage()]


def test_runoff_day_without_pixel_refused() -> None:
    runoff = gridded_runoff()
    runoff.fields[0].data["runoff"][5] = np.nan
    baseflow = pd.Series(0.0, index=SIM_INDEX, name="discharge")

    with pytest.raises(DataContractViolation, match="no valid pixel in time step 5"):
        add_runoff_to_discharge(baseflow, context(runoff))


def test_non_positive_gauge_area_refused() -> None:
    baseflow = pd.Series(0.0, index=SIM_INDEX)

    with pytest.raises(ValueError, match="must be positive, got 0.0 m2"):
        add_runoff_to_discharge(baseflow, point_context(ROUGH_RUNOFF), area_m2=0.0)


def test_period_without_runoff_is_a_gap() -> None:
    baseflow = pd.Series(BASEFLOW, index=SIM_INDEX, name="discharge")

    scored = add_runoff_to_discharge(baseflow, context(short_runoff()))

    assert scored.iloc[:2].tolist() == pytest.approx([2.4, 2.7])
    assert np.isnan(scored.iloc[2])


def test_steady_then_short_periods_averaged_alike() -> None:
    # A long spin-up followed by short periods is what a staged calibration
    # produces. A rule keyed on the median spacing would send every period,
    # the long one included, to the nearest sample.
    runoff = stepped_runoff()
    mixed = pd.DatetimeIndex(["2000-01-20", "2000-02-25", "2000-02-27", "2000-02-29", "2000-03-02"])
    baseflow = pd.Series(0.0, index=mixed, name="discharge")
    store, grp = stored_run(runoff)

    scored = add_runoff_to_discharge(baseflow, point_context(runoff))
    reported = with_runoff(baseflow, "sim-0", store=store, grp=grp)

    assert scored.tolist() == pytest.approx(reported.tolist())
    # The first period spans the 2 and the 5 mm/day blocks, so its mean lies between them.
    assert 2.0 < scored.iloc[0] < 5.0
    # The short periods sit inside the 9 mm/day block.
    assert scored.iloc[-1] == pytest.approx(9.0)


def test_gap_in_trial_and_in_run() -> None:
    # Baseflow alone is no total discharge, so a run publishes no number a trial would drop.
    index = pd.DatetimeIndex(["2000-03-01", "2000-04-01", "2000-05-01"])
    baseflow = pd.Series(BASEFLOW, index=index, name="discharge")
    store, grp = stored_run(ROUGH_RUNOFF)

    scored = add_runoff_to_discharge(baseflow, point_context(ROUGH_RUNOFF))
    reported = with_runoff(baseflow, "sim-0", store=store, grp=grp, start=None)

    np.testing.assert_array_equal(scored, reported)
    assert np.isnan(reported.iloc[2])
    assert not reported.iloc[:2].isna().any()


RUNOFF_SOURCES = [
    pytest.param(None, 1.0, 1.0, id="soil runoff replaces the loaded one"),
    pytest.param(3.0, None, 3.0, id="no soil forcings, loaded runoff"),
]


@pytest.mark.parametrize(("loaded_mm", "soil_mm", "expected_m3_s"), RUNOFF_SOURCES)
def test_runoff_source(loaded_mm, soil_mm, expected_m3_s) -> None:
    baseflow = pd.Series(0.0, index=SIM_INDEX, name="discharge")
    ctx = soil_context(
        loaded_runoff=None if loaded_mm is None else uniform_runoff(loaded_mm),
        soil_runoff=None if soil_mm is None else uniform_runoff(soil_mm),
    )

    scored = add_runoff_to_discharge(baseflow, ctx)

    assert scored.tolist() == pytest.approx([expected_m3_s] * 3)


def runoff_of(forcings) -> np.ndarray:
    return forcings.runoff.fields[0].data["runoff"].to_numpy()


def test_curve_number_runoff() -> None:
    off_runoff = runoff_of(soil_forcings(curve_number=None, runoff_time=0.0))
    on_runoff = runoff_of(soil_forcings(curve_number=85.0, runoff_time=0.0))

    assert off_runoff == pytest.approx(0.0)
    assert np.all(on_runoff > 0.0)


def test_curve_number_discharge() -> None:
    low = scored_discharge(soil_forcings(curve_number=70.0, runoff_time=0.0))
    high = scored_discharge(soil_forcings(curve_number=90.0, runoff_time=0.0))

    assert not np.allclose(low.to_numpy(), high.to_numpy())


def test_impervious_runoff() -> None:
    low_runoff = runoff_of(soil_forcings(rain=10.0, impervious_fraction=0.0))
    high_runoff = runoff_of(soil_forcings(rain=10.0, impervious_fraction=0.08))

    assert low_runoff == pytest.approx(0.0)
    assert high_runoff == pytest.approx(0.08 * 10.0)


def test_impervious_discharge() -> None:
    low = scored_discharge(soil_forcings(rain=10.0, impervious_fraction=0.0))
    high = scored_discharge(soil_forcings(rain=10.0, impervious_fraction=0.08))

    # 0.08 x 10 mm/day of sealed runoff over 86.4 km2 is 0.8 m3/s, added once.
    expected_m3_s = 0.08 * 10.0 * 1e-3 * (CATCH_AREA_KM2 * 1e6) / 86400.0
    assert (high - low).to_numpy() == pytest.approx(expected_m3_s)


def lagged(runoff_lag: float):
    return soil_forcings(pulsed=True, curve_number=85.0, runoff_time=0.0, runoff_lag=runoff_lag)


def test_runoff_lag() -> None:
    assert not np.allclose(runoff_of(lagged(0.0)), runoff_of(lagged(3.0)))


def test_runoff_lag_discharge() -> None:
    unlagged = scored_discharge(lagged(0.0))
    late = scored_discharge(lagged(3.0))

    assert not np.allclose(unlagged.to_numpy(), late.to_numpy())


def station(values, *, tz=None, name="S1") -> SimpleNamespace:
    stamps = pd.date_range("2000-01-01", periods=len(values), freq="D", tz=tz)
    data = pd.DataFrame({"datetime": stamps, "value": values})
    return SimpleNamespace(station_id=name, variable="discharge", data=data)


def test_load_observed_skips_undated() -> None:
    skipped = [
        SimpleNamespace(station_id="none", variable="discharge", data=None),
        SimpleNamespace(station_id="empty", variable="discharge", data=pd.DataFrame()),
        SimpleNamespace(station_id="broken", variable="discharge", data=pd.DataFrame({"x": [1]})),
    ]
    ctx = SimpleNamespace(
        loaded_data=SimpleNamespace(
            hydrometry=SimpleNamespace(points=[*skipped, station([1.0, 2.0], tz="UTC")])
        )
    )

    (kept,) = series_module.load_observed(ctx, "discharge")

    assert kept.station_id == "S1"
    assert kept.series.index.tolist() == [pd.Timestamp("2000-01-01"), pd.Timestamp("2000-01-02")]
    assert kept.series.tolist() == [1.0, 2.0]


def grid_setup(*boundaries):
    return SimpleNamespace(time_grid=SimpleNamespace(boundaries=list(boundaries)))


TIME_INDEX = [
    pytest.param(None, 0, None, id="no setup"),
    pytest.param(grid_setup("2000-01-01"), 0, None, id="one boundary"),
    pytest.param(grid_setup("a", "b"), 0, None, id="not dates"),
    pytest.param(
        grid_setup("2000-01-01", "2000-01-11", "2000-01-21"), 1, ["2000-01-11"], id="one stamp"
    ),
]


@pytest.mark.parametrize(("setup", "n_timesteps", "expected"), TIME_INDEX)
def test_time_index_of_stamps(setup, n_timesteps, expected) -> None:
    index = series_module.resolve_time_index(SimpleNamespace(setup=setup), n_timesteps)

    assert (index if index is None else index.strftime("%Y-%m-%d").tolist()) == expected


def test_station_runoff_mean() -> None:
    points = [
        SimpleNamespace(data=None),
        SimpleNamespace(data=pd.DataFrame()),
        station([2.0, 4.0], tz="UTC"),
        station([4.0, 8.0]),
    ]

    mean = series_module._station_runoff_mm_per_day(points)

    assert mean.tolist() == [3.0, 6.0]
    assert series_module._station_runoff_mm_per_day(points[:2]) is None


@pytest.mark.parametrize(
    ("reduced", "expected"),
    [
        pytest.param(None, None, id="nothing reduced"),
        pytest.param(pd.Series(dtype=float), None, id="empty"),
        pytest.param(
            pd.Series([1.0, 2.0], index=pd.date_range("2000-01-01", periods=2, tz="UTC")),
            [1.0, 2.0],
            id="utc series",
        ),
    ],
)
def test_gridded_runoff_series(monkeypatch, reduced, expected) -> None:
    monkeypatch.setattr(series_module, "spatial_mean_from_fields", lambda _runoff: reduced)

    result = series_module._gridded_runoff_mm_per_day(object())

    if expected is None:
        assert result is None
    else:
        assert result.tolist() == expected
        assert result.index.tz is None


def test_baseflow_alone_without_runoff(monkeypatch) -> None:
    simulated = pd.Series([1.0], index=pd.DatetimeIndex(["2000-01-02"]))
    no_area = SimpleNamespace(
        loaded_data=SimpleNamespace(runoff=SimpleNamespace(points=[station([5.0])], fields=None)),
        setup=SimpleNamespace(geographic=SimpleNamespace(catch_area=0.0)),
    )
    ungridded = SimpleNamespace(
        loaded_data=SimpleNamespace(runoff=SimpleNamespace(points=None, fields=[object()])),
        setup=SimpleNamespace(geographic=SimpleNamespace(catch_area=1.0)),
    )
    monkeypatch.setattr(series_module, "spatial_mean_from_fields", lambda _runoff: None)

    assert add_runoff_to_discharge(simulated, no_area) is simulated
    assert add_runoff_to_discharge(simulated, ungridded) is simulated


def test_evaluator_forwards_min_samples() -> None:
    # The evaluator holds the trial context, so it builds the extractor.
    source = inspect.getsource(pipeline_evaluator._extractor_for)

    assert "min_samples=int(cfg.aggregate.min_samples)" in source
