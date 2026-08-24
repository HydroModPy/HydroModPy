"""The calibration path and the derived path must average runoff the same way.

The runoff forcing is added to a baseflow twice in this repository: once when
the calibration metric builds the simulated discharge it scores
(``calibration.metrics.series.add_runoff_to_discharge``) and once when the
catalog materialises the catchment discharge a run is read back from
(``simulation.extraction.derivation.catchment_aggregation``). If the two align
the daily forcing on the stress periods by different rules, a run scores against
one discharge and reports another.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.metrics.series import add_runoff_to_discharge
from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
    _add_runoff_to_discharge_series,
)

# 1 mm/day over 86.4 km² is exactly 1 m³/s: 1e-3 * 8.64e7 / 86400.
_CATCH_AREA_KM2 = 86.4

# Three unevenly spaced stress periods. Halfway to each neighbour, they span
# 2000-01-06..01-15, 01-16..02-04 and 02-05..03-05, and the forcing below is
# constant on each of those spans, so the period means are 2, 5 and 9 mm/day
# by construction.
_SIM_INDEX = pd.DatetimeIndex(["2000-01-11", "2000-01-21", "2000-02-20"])
_EXPECTED_M3_PER_S = [2.0, 5.0, 9.0]


def _daily_runoff_mm() -> pd.Series:
    parts = [
        pd.Series(value, index=pd.date_range(start, end, freq="D", inclusive="left"))
        for start, end, value in (
            ("2000-01-06", "2000-01-16", 2.0),
            ("2000-01-16", "2000-02-05", 5.0),
            ("2000-02-05", "2000-03-06", 9.0),
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


class _AreaConnection:
    def __init__(self, area_km2: float) -> None:
        self._area_km2 = area_km2

    def execute(self, sql: str, params):
        return SimpleNamespace(fetchone=lambda: (self._area_km2,))


def _derived_paths_inputs(runoff: pd.Series):
    station = _FakeNode(
        {
            "values": _FakeArray(runoff.to_numpy(dtype="float64")),
            "timestamps": _FakeArray(pd.DatetimeIndex(runoff.index).values),
        }
    )
    grp = _FakeRootGroup(_FakeNode({"runoff": _FakeRunoffGroup({"station0": station})}))
    store = SimpleNamespace(connection=_AreaConnection(_CATCH_AREA_KM2))
    return store, grp


def _calibration_context(runoff: pd.Series):
    frame = pd.DataFrame(
        {"datetime": pd.DatetimeIndex(runoff.index), "value": runoff.to_numpy(dtype="float64")}
    )
    return SimpleNamespace(
        loaded_data=SimpleNamespace(runoff=SimpleNamespace(points=[SimpleNamespace(data=frame)])),
        setup=SimpleNamespace(geographic=SimpleNamespace(catch_area=_CATCH_AREA_KM2)),
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

    One steady stress period covering the run, and a daily forcing over it. The
    period mean of the window above is (10*2 + 20*5 + 30*9) / 60 = 6.5 mm/day.
    A rule that picks the sample nearest the stamp answers 5.0 here, which is
    the failure the whole single-source fix is about, and the one an index with
    an even spacing cannot expose.
    """
    runoff = _daily_runoff_mm()
    steady = pd.DatetimeIndex(["2000-01-21"])
    baseflow = pd.Series(0.0, index=steady, name="discharge")
    store, grp = _derived_paths_inputs(runoff)

    scored = add_runoff_to_discharge(baseflow, _calibration_context(runoff))
    reported = _add_runoff_to_discharge_series(baseflow, "sim-0", store=store, grp=grp)

    expected = float(runoff.mean())
    assert expected == pytest.approx(6.5)
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
