"""A run carries its own score against the observations ingested beside it.

A simulated stamp closes its stress period and an observation is stamped at
the start of what it measures, so a daily record pairs with the simulated
stamp one day after it. These tests used to give both series the same stamps,
which paired each period with the day that opens the next one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.simulation.extraction.derivation.fit_metrics import write_fit_metrics


class _FakeConnection:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    def execute(self, _sql: str, _params: list) -> _FakeConnection:
        return self

    def df(self) -> pd.DataFrame:
        return self._frame


class _FakeStore:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.connection = _FakeConnection(frame)
        self.metrics: list[dict] = []

    def write_metric(self, sim_id, station_id, metric_name, value, **kwargs):
        self.metrics.append(
            {"station_id": station_id, "name": metric_name, "value": value, **kwargs}
        )


def _frame(sim_times, sim_values, obs_times, obs_values) -> pd.DataFrame:
    rows = [
        {"station_id": "_catchment", "variable": "discharge", "time": t, "value": v}
        for t, v in zip(sim_times, sim_values, strict=True)
    ]
    rows += [
        {"station_id": "NANCON", "variable": "discharge_obs", "time": t, "value": v}
        for t, v in zip(obs_times, obs_values, strict=True)
    ]
    return pd.DataFrame(rows)


def _closing(days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The simulated stamps that close the days of ``days``."""
    return days.shift(1, freq="D")


def test_a_perfect_run_scores_one_everywhere() -> None:
    days = pd.date_range("2001-01-01", periods=40, freq="D", tz="UTC")
    values = np.linspace(1.0, 4.0, 40)
    store = _FakeStore(_frame(_closing(days), values, days, values))

    assert write_fit_metrics("sim", store) > 0

    by_name = {m["name"]: m["value"] for m in store.metrics}
    assert by_name["nse"] == pytest.approx(1.0)
    assert by_name["kge"] == pytest.approx(1.0)
    assert by_name["rmse"] == pytest.approx(0.0, abs=1e-12)
    # The decomposition travels with the score: a bare KGE cannot tell a timing
    # error from an amplitude one.
    assert {"kge_r", "kge_alpha", "kge_beta"} <= set(by_name)


def test_the_panel_is_written_under_the_observed_station(store_days=40) -> None:
    days = pd.date_range("2001-01-01", periods=store_days, freq="D", tz="UTC")
    store = _FakeStore(
        _frame(_closing(days), np.arange(store_days) + 1.0, days, np.arange(store_days) + 2.0)
    )

    write_fit_metrics("sim", store)

    assert {m["station_id"] for m in store.metrics} == {"NANCON"}
    assert {m["variable"] for m in store.metrics} == {"discharge"}
    assert {m["n_samples"] for m in store.metrics} == {store_days}


def test_a_gauge_stamped_at_another_hour_still_pairs() -> None:
    # A daily run stamped at midnight and a gauge stamped at noon share no exact
    # timestamp. An empty overlap would read as "no observation" when the two
    # cover the same years.
    sim_days = pd.date_range("2001-01-02 00:00", periods=30, freq="D", tz="UTC")
    obs_days = pd.date_range("2001-01-01 12:00", periods=30, freq="D", tz="UTC")
    values = np.linspace(1.0, 3.0, 30)
    store = _FakeStore(_frame(sim_days, values, obs_days, values))

    write_fit_metrics("sim", store)

    by_name = {m["name"]: m["value"] for m in store.metrics}
    assert by_name["nse"] == pytest.approx(1.0)
    assert {m["n_samples"] for m in store.metrics} == {30}


def test_series_that_never_overlap_are_not_scored(caplog) -> None:
    sim_days = pd.date_range("2001-01-01", periods=10, freq="D", tz="UTC")
    obs_days = pd.date_range("2015-01-01", periods=10, freq="D", tz="UTC")
    store = _FakeStore(_frame(sim_days, np.ones(10), obs_days, np.ones(10)))

    with caplog.at_level("WARNING"):
        assert write_fit_metrics("sim", store) == 0

    assert store.metrics == []
    # Silence would read as "this run has no observation", which is not the case.
    assert "share 0 period" in " ".join(r.getMessage() for r in caplog.records)


def test_a_steady_run_is_not_scored_and_does_not_cry_wolf(caplog) -> None:
    # One period, one value: there is no series to score. Warning on every
    # steady phase would drown the transient case that IS an anomaly.
    day = pd.Timestamp("2001-01-01", tz="UTC")
    obs_days = pd.date_range("2001-01-01", periods=10, freq="D", tz="UTC")
    store = _FakeStore(_frame([day], [1.0], obs_days, np.ones(10)))

    with caplog.at_level("WARNING"):
        assert write_fit_metrics("sim", store) == 0

    assert store.metrics == []
    assert caplog.records == []


def test_a_run_without_observations_writes_nothing() -> None:
    days = pd.date_range("2001-01-01", periods=10, freq="D", tz="UTC")
    frame = pd.DataFrame(
        [
            {"station_id": "_catchment", "variable": "discharge", "time": t, "value": 1.0}
            for t in days
        ]
    )
    store = _FakeStore(frame)

    assert write_fit_metrics("sim", store) == 0
    assert store.metrics == []


def test_a_monthly_run_is_scored_on_the_monthly_means_of_a_daily_gauge() -> None:
    # Each month of the gauge is constant, the run reproduces it exactly. The
    # old join on equal stamps compared each month with the first day of the
    # next one, a month late.
    days = pd.date_range("2001-01-01", "2001-12-31", freq="D", tz="UTC")
    gauge = days.month.to_numpy(dtype=float)
    month_ends = pd.date_range("2001-02-01", periods=12, freq="MS", tz="UTC")
    store = _FakeStore(_frame(month_ends, np.arange(1.0, 13.0), days, gauge))

    write_fit_metrics("sim", store)

    by_name = {m["name"]: m["value"] for m in store.metrics}
    assert by_name["nse"] == pytest.approx(1.0)
    assert {m["n_samples"] for m in store.metrics} == {12}


def test_a_lake_level_is_scored_on_the_reading_at_its_stamp() -> None:
    # A lake level is the state AT its stamp, so a daily run pairs each stage
    # with the reading taken at that instant, not the day its stamp closes.
    days = pd.date_range("2001-01-01", periods=30, freq="D", tz="UTC")
    stages = np.linspace(80.0, 90.0, 30)
    rows = [
        {"station_id": "lake:lac0", "variable": "lake_level", "time": t, "value": v}
        for t, v in zip(days, stages, strict=True)
    ]
    rows += [
        {"station_id": "lac0", "variable": "lake_level_obs", "time": t, "value": v}
        for t, v in zip(days, stages, strict=True)
    ]
    store = _FakeStore(pd.DataFrame(rows))

    write_fit_metrics("sim", store)

    by_name = {m["name"]: m["value"] for m in store.metrics}
    assert by_name["rmse"] == pytest.approx(0.0)
    assert {m["n_samples"] for m in store.metrics} == {30}
