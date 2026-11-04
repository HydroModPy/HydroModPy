"""A run is scored under its rule: the declared window, at the declared station, never an overlap.

A simulated stamp closes its stress period and an observation is stamped at the
start of what it measures, so a daily record pairs with the simulated stamp one
day after it. Only the periods inside ``[metrics] window`` count; without a
window nothing is scored and the headline NSE is empty.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from hydromodpy.core import metrics as kernels
from hydromodpy.results.fit_metrics import UnscoredObservation, fit_metrics, score_timeseries
from hydromodpy.results.metric_rule import METRIC_NAMES, DateWindow, MetricRule
from hydromodpy.results.storage.parquet_io import write_table_atomic
from hydromodpy.results.storage.parquet_schemas import PARQUET_SCHEMA_VERSION

GAUGE = "J0014010"
YEAR_2001 = DateWindow(start=date(2001, 1, 1), end=date(2001, 12, 31))


def _rows(station: str, variable: str, times, values, source: str = "simulated") -> list[dict]:
    return [
        {
            "station_id": station,
            "variable": variable,
            "source": source,
            "time": t,
            "value": float(v),
        }
        for t, v in zip(times, values, strict=True)
    ]


def _frame(sim_times, sim_values, obs_times, obs_values, *, gauge: str = GAUGE) -> pd.DataFrame:
    return pd.DataFrame(
        _rows(gauge, "discharge", sim_times, sim_values)
        + _rows(gauge, "discharge", obs_times, obs_values, source="observed")
    )


def _closing(days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The simulated stamps that close the days of ``days``."""
    return days.shift(1, freq="D")


def _by_metric(scores) -> dict[str, float | None]:
    return {row.metric: row.value for row in scores.rows}


def test_a_perfect_run_scores_one_on_the_whole_panel() -> None:
    days = pd.date_range("2001-01-01", "2001-12-31", freq="D", tz="UTC")
    values = np.linspace(1.0, 4.0, len(days))
    rule = MetricRule(station=GAUGE, window=YEAR_2001)

    scores = score_timeseries(_frame(_closing(days), values, days, values), rule=rule)

    by_metric = _by_metric(scores)
    assert set(by_metric) == set(METRIC_NAMES)
    assert by_metric["nse"] == pytest.approx(1.0)
    assert by_metric["kge"] == pytest.approx(1.0)
    assert by_metric["rmse"] == pytest.approx(0.0, abs=1e-12)
    assert scores.score.value == pytest.approx(1.0)
    assert (scores.score.station, scores.score.variable) == (GAUGE, "discharge")
    assert scores.score.n_samples == 365


def test_the_spin_up_does_not_count() -> None:
    days = pd.date_range("2000-01-01", "2001-12-31", freq="D", tz="UTC")
    observed = np.sin(np.arange(len(days)) / 30.0) + 3.0
    simulated = observed.copy()
    simulated[days < "2001-01-01"] = 50.0
    rule = MetricRule(station=GAUGE, window=YEAR_2001)

    scores = score_timeseries(_frame(_closing(days), simulated, days, observed), rule=rule)

    assert scores.score.value == pytest.approx(1.0)
    assert scores.score.n_samples == 365
    assert (scores.score.window_start, scores.score.window_end) == (
        YEAR_2001.start,
        YEAR_2001.end,
    )


def test_without_a_window_nothing_is_scored() -> None:
    days = pd.date_range("2001-01-01", periods=40, freq="D", tz="UTC")
    values = np.linspace(1.0, 4.0, 40)

    scores = score_timeseries(
        _frame(_closing(days), values, days, values), rule=MetricRule(station=GAUGE)
    )

    assert scores.rows == ()
    assert scores.score.value is None
    assert scores.score.window_start is None
    assert scores.score.n_samples == 0
    assert scores.score.metric_rule_version == "2"


def test_without_a_station_the_rows_exist_but_the_headline_is_empty() -> None:
    days = pd.date_range("2001-01-01", "2001-12-31", freq="D", tz="UTC")
    values = np.linspace(1.0, 4.0, len(days))
    frame = pd.DataFrame(
        _rows(GAUGE, "discharge", _closing(days), values)
        + _rows(GAUGE, "discharge", days, values, source="observed")
    )

    scores = score_timeseries(frame, rule=MetricRule(window=YEAR_2001))

    assert {row.station for row in scores.rows} == {GAUGE}
    assert scores.score.value is None
    assert scores.score.window_start == YEAR_2001.start


def test_the_headline_is_read_at_the_rule_station_only() -> None:
    days = pd.date_range("2001-01-01", "2001-12-31", freq="D", tz="UTC")
    values = np.linspace(1.0, 4.0, len(days))
    frame = pd.DataFrame(
        _rows("OTHER", "discharge", _closing(days), values)
        + _rows("OTHER", "discharge", days, values, source="observed")
        + _rows(GAUGE, "discharge", _closing(days), values)
        + _rows(GAUGE, "discharge", days, values * 2.0, source="observed")
    )

    scores = score_timeseries(frame, rule=MetricRule(station=GAUGE, window=YEAR_2001))

    nse = {row.station: row.value for row in scores.rows if row.metric == "nse"}
    assert nse["OTHER"] == pytest.approx(1.0)
    assert scores.score.station == GAUGE
    assert scores.score.value == pytest.approx(nse[GAUGE])
    assert scores.score.value < 0.0


def test_a_monthly_period_counts_only_when_it_lies_in_the_window() -> None:
    # Each month of the gauge is constant and the run reproduces it, except
    # January, which is wrong but starts before the window.
    days = pd.date_range("2001-01-01", "2001-12-31", freq="D", tz="UTC")
    gauge = days.month.to_numpy(dtype=float)
    month_ends = pd.date_range("2001-02-01", periods=12, freq="MS", tz="UTC")
    simulated = np.arange(1.0, 13.0)
    simulated[0] = 99.0
    window = DateWindow(start=date(2001, 2, 1), end=date(2001, 11, 30))

    scores = score_timeseries(
        _frame(month_ends, simulated, days, gauge),
        rule=MetricRule(station=GAUGE, window=window),
        period_start="2001-01-01",
    )

    # February to November: ten months, January and December left out.
    assert scores.score.n_samples == 10
    assert scores.score.value == pytest.approx(1.0)


def test_a_lake_level_is_read_at_its_stamp() -> None:
    days = pd.date_range("2001-01-01", "2001-01-30", freq="D", tz="UTC")
    stages = np.linspace(80.0, 90.0, len(days))
    frame = pd.DataFrame(
        _rows("lac0", "lake_level", days, stages)
        + _rows("lac0", "lake_level", days, stages, source="observed")
    )
    window = DateWindow(start=date(2001, 1, 1), end=date(2001, 1, 10))

    scores = score_timeseries(frame, rule=MetricRule(station="lac0", window=window))

    rmse = [row for row in scores.rows if row.metric == "rmse"]
    assert [row.value for row in rmse] == [pytest.approx(0.0)]
    assert rmse[0].n_samples == 10
    assert (scores.score.variable, scores.score.n_samples) == ("lake_level", 10)


def test_an_observed_station_meets_the_simulated_series_of_the_same_station(caplog) -> None:
    days = pd.date_range("2001-01-01", "2001-12-31", freq="D", tz="UTC")
    heads = np.linspace(10.0, 12.0, len(days))
    frame = pd.DataFrame(
        _rows("P1", "head", days, heads)
        + _rows("P2", "head", days, heads + 5.0)
        + _rows("P1", "head", days, heads, source="observed")
        + _rows("P3", "head", days, heads, source="observed")
    )

    with caplog.at_level("WARNING"):
        scores = score_timeseries(frame, rule=MetricRule(window=YEAR_2001))

    rmse = {row.station: row.value for row in scores.rows if row.metric == "rmse"}
    assert caplog.messages == [UnscoredObservation("P3", "head", ("P1", "P2")).sentence() + "."]
    # P3 is simulated nowhere and two head stations exist: no guess is made.
    assert rmse == {"P1": pytest.approx(0.0)}
    assert scores.unscored == (UnscoredObservation("P3", "head", ("P1", "P2")),)


def test_a_variable_the_run_does_not_simulate_is_skipped_station_by_station(caplog) -> None:
    days = pd.date_range("2001-01-01", "2001-12-31", freq="D", tz="UTC")
    heads = np.linspace(10.0, 12.0, len(days))
    frame = pd.DataFrame(
        _rows(7, "head", days, heads)
        + _rows(7, "head", days, heads, source="observed")
        + _rows(8, "lake_level", days, heads, source="observed")
        + _rows(9, "lake_level", days, heads, source="observed")
    )

    with caplog.at_level("DEBUG"):
        scores = score_timeseries(frame, rule=MetricRule(window=YEAR_2001))

    # Station ids are read as text, as a table of strings gives them.
    assert {row.station for row in scores.rows} == {"7"}
    assert scores.unscored == ()
    skipped = [r.getMessage() for r in caplog.records if r.levelname == "DEBUG"]
    assert [m for m in skipped if m.startswith("Not scoring")] == [
        f"Not scoring lake_level at {station}: the run does not simulate it." for station in "89"
    ]


def test_series_that_never_meet_the_window_leave_no_row() -> None:
    sim_days = pd.date_range("2001-01-01", periods=10, freq="D", tz="UTC")
    obs_days = pd.date_range("2015-01-01", periods=10, freq="D", tz="UTC")

    scores = score_timeseries(
        _frame(sim_days, np.ones(10), obs_days, np.ones(10)),
        rule=MetricRule(station=GAUGE, window=YEAR_2001),
    )

    assert scores.rows == ()
    assert scores.score.value is None and scores.score.n_samples == 0


def test_a_steady_value_is_not_scored() -> None:
    # One simulated period of one day, which the gauge fully covers.
    day = pd.DatetimeIndex([pd.Timestamp("2001-06-01", tz="UTC")])
    obs_days = pd.date_range("2001-01-01", "2001-12-31", freq="D", tz="UTC")

    scores = score_timeseries(
        _frame(day, [1.0], obs_days, np.linspace(1.0, 2.0, len(obs_days))),
        rule=MetricRule(station=GAUGE, window=YEAR_2001),
        period_start="2001-05-31",
    )

    assert scores.rows == ()
    assert scores.score.value is None
    assert scores.score.n_samples == 0


def test_a_daily_gap_before_the_window_keeps_the_next_period_in_it() -> None:
    days = pd.date_range("2001-01-01", "2001-12-31", freq="D", tz="UTC")
    values = np.sin(np.arange(len(days)) / 25.0) + 3.0
    observed = values.copy()
    observed[(days >= "2001-02-20") & (days <= "2001-03-04")] = np.nan
    window = DateWindow(start=date(2001, 3, 1), end=date(2001, 12, 31))

    scores = score_timeseries(
        _frame(_closing(days), values, days, observed),
        rule=MetricRule(station=GAUGE, window=window),
        period_start="2001-01-01",
    )

    # 5 March to 31 December: every day the gauge measured inside the window.
    assert scores.score.n_samples == 302
    assert scores.score.value == pytest.approx(1.0)


def test_a_monthly_gap_before_the_window_keeps_the_next_month_in_it() -> None:
    days = pd.date_range("2001-01-01", "2001-12-31", freq="D", tz="UTC")
    gauge = days.month.to_numpy(dtype=float)
    gauge[days.month == 2] = np.nan
    month_ends = pd.date_range("2001-02-01", periods=12, freq="MS", tz="UTC")
    window = DateWindow(start=date(2001, 3, 1), end=date(2001, 11, 30))

    scores = score_timeseries(
        _frame(month_ends, np.arange(1.0, 13.0), days, gauge),
        rule=MetricRule(station=GAUGE, window=window),
        period_start="2001-01-01",
    )

    # March to November: nine months, February unmeasured, January before the window.
    assert scores.score.n_samples == 9
    assert scores.score.value == pytest.approx(1.0)


def test_the_log_nse_is_written_under_its_calibration_name() -> None:
    days = pd.date_range("2001-01-01", "2001-12-31", freq="D", tz="UTC")
    values = np.linspace(1.0, 3.0, len(days))

    scores = score_timeseries(
        _frame(_closing(days), values, days, values),
        rule=MetricRule(station=GAUGE, window=YEAR_2001),
    )

    names = {row.metric for row in scores.rows}
    assert "nse_log" in names
    assert "log_nse" not in names


def test_the_run_directory_is_read_without_the_index(tmp_path, monkeypatch) -> None:
    from hydromodpy.results.catalog import Catalog

    def _refuse(*_args, **_kwargs):
        raise AssertionError("scoring a run opened the index")

    monkeypatch.setattr(Catalog, "__init__", _refuse)
    days = pd.date_range("2001-01-01", "2001-12-31", freq="D", tz="UTC")
    observed = np.cos(np.arange(len(days)) / 20.0) + 2.0
    simulated = observed * 1.1
    frame = _frame(_closing(days), simulated, days, observed).assign(component=None)
    component = frame.iloc[:5].assign(component="baseflow", value=1e6)
    tables = tmp_path / "tables.parquet"
    tables.mkdir()
    write_table_atomic(
        pa.Table.from_pandas(pd.concat([frame, component])),
        tables / "timeseries.parquet",
        kv_metadata={"hmp.schema_version": PARQUET_SCHEMA_VERSION},
    )

    scores = fit_metrics(tmp_path, rule=MetricRule(station=GAUGE, window=YEAR_2001))

    expected = kernels.nse(simulated, observed)
    assert scores.score.value == pytest.approx(expected)
    assert scores.score.n_samples == 365


def test_a_run_without_series_has_an_empty_score(tmp_path) -> None:
    scores = fit_metrics(tmp_path, rule=MetricRule(station=GAUGE, window=YEAR_2001))
    assert scores.rows == ()
    assert scores.score.value is None
