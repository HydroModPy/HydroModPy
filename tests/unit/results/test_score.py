"""A run is scored under its rule, by the one pairing a calibration trial uses too.

A simulated stamp closes its stress period and an observation is stamped at the
start of what it measures, so a daily record pairs with the simulated stamp one
day after it. Only the periods inside the window count; without a window nothing
is scored and the headline NSE is empty. A trial and the run it promotes pair the
same series alike, bit for bit, and a promoted run is also scored on each
calibration period of its seal.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from hydromodpy.calibration.metrics.observed_pairing import pair_outputs_with_observations
from hydromodpy.core.fields.precision import MAX_RELATIVE_ERROR, to_storage_precision
from hydromodpy.core.scoring import metrics as kernels
from hydromodpy.core.scoring.metric_table import RUN_METRIC_NAMES
from hydromodpy.results.metric_rule import (
    CALIBRATION_ROLE,
    EVALUATION_ROLE,
    HEADLINE_WINDOW,
    METRIC_RULE_VERSION,
    VALIDATION_ROLE,
    DateWindow,
    MetricRule,
    MetricsConfig,
    MetricScore,
    MetricsWindow,
    PeriodWindow,
)
from hydromodpy.results.record.checks import CalibratedBy
from hydromodpy.results.score import (
    UnscoredObservation,
    calibration_rules,
    pair,
    read_timeseries,
    score_metric,
    score_run_under_its_rule,
    score_timeseries,
)
from hydromodpy.results.storage.parquet_io import write_table_atomic
from hydromodpy.results.storage.parquet_schemas import PARQUET_SCHEMA_VERSION

GAUGE = "J0014010"
YEAR_2001 = DateWindow(start=date(2001, 1, 1), end=date(2001, 12, 31))
INDEX = pd.date_range("2015-01-01", "2016-12-31", freq="D")
WINDOW_2016 = DateWindow(start=date(2016, 1, 1), end=date(2016, 12, 31))
RULE_2016 = MetricRule(station=GAUGE, window=WINDOW_2016)


def _rows(station, variable: str, times, values, source: str = "simulated") -> list[dict]:
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


def _series(seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.uniform(0.5, 5.0, len(INDEX)), index=INDEX)


# The three cases of the pairing: a daily discharge, a monthly discharge and a
# daily head, each with NaN simulated values and gaps in the record.
CASES = {
    "daily_discharge": ("discharge", "mean", "D", 0.5),
    "monthly_discharge": ("discharge", "mean", "ME", 0.5),
    "daily_head": ("head", "point", "D", 120.0),
}
CASE_WINDOW = DateWindow(start=date(2016, 1, 1), end=date(2017, 12, 31))


def _cases() -> dict[str, tuple[str, str, pd.Series, pd.Series, pd.Timestamp]]:
    """Build the three cases in order from one generator, as the measure did."""
    rng = np.random.default_rng(11)
    built = {}
    for name, (variable, method, freq, base) in CASES.items():
        first = "2015-01-31" if freq == "ME" else "2015-01-02"
        stamps = pd.date_range(first, "2017-12-31", freq=freq, tz="UTC")
        n = len(stamps)
        simulated = pd.Series(
            base + np.cumsum(rng.normal(0, 0.01, n)) + 0.1 * np.sin(np.arange(n) / 20),
            index=stamps,
        )
        simulated.iloc[rng.choice(n, 4, replace=False)] = np.nan
        observed = simulated.dropna() * (1 + rng.normal(0, 0.05, simulated.dropna().size))
        dropped = rng.choice(observed.size, observed.size // 10, replace=False)
        observed = observed.drop(observed.index[dropped])
        built[name] = (variable, method, simulated, observed, stamps[0] - (stamps[1] - stamps[0]))
    return built


def _case(name: str) -> tuple[str, str, pd.Series, pd.Series, pd.Timestamp]:
    return _cases()[name]


def _trial(method: str, simulated: pd.Series, observed: pd.Series, start: pd.Timestamp):
    return pair_outputs_with_observations(
        observed={"q": observed},
        simulated={"q": simulated},
        window=(pd.Timestamp(CASE_WINDOW.start), pd.Timestamp(CASE_WINDOW.end)),
        time_methods={"q": method},
        period_starts={"q": start},
    )


def _run_nse(variable: str, simulated: pd.Series, observed: pd.Series, start) -> MetricScore:
    rows = _rows("s", variable, simulated.index, simulated.to_numpy()) + _rows(
        "s", variable, observed.index, observed.to_numpy(), source="observed"
    )
    scores = score_timeseries(
        pd.DataFrame(rows), rule=MetricRule(station="s", window=CASE_WINDOW), period_start=start
    )
    return scores.score


@pytest.mark.parametrize(
    ("case", "n_pairs"),
    [("daily_discharge", 647), ("monthly_discharge", 19), ("daily_head", 727)],
)
def test_a_trial_and_its_run_pair_the_same_series_bit_for_bit(case: str, n_pairs: int) -> None:
    variable, method, simulated, observed, start = _case(case)

    trial = _trial(method, simulated, observed, start)
    run = _run_nse(variable, simulated, observed, start)

    trial_nse = kernels.nse(np.asarray(trial.simulated["q"]), np.asarray(trial.observed["q"]))
    assert trial.n_paired["q"] == run.n_samples == n_pairs
    assert run.value == trial_nse
    assert trial.n_simulated_nan["q"] > 0


@pytest.mark.parametrize("case", sorted(CASES))
def test_a_run_read_compact_keeps_the_simulated_values_of_its_trial(case: str) -> None:
    variable, method, simulated, observed, start = _case(case)
    compact = pd.Series(to_storage_precision(simulated.to_numpy(), "compact"), simulated.index)

    trial = _trial(method, simulated, observed, start)
    sealed = pair(
        simulated=compact, observed=observed, method=method, window=CASE_WINDOW, period_start=start
    )

    assert MAX_RELATIVE_ERROR == 2.0**-17
    np.testing.assert_array_equal(sealed.frame["obs"].to_numpy(), trial.observed["q"])
    np.testing.assert_allclose(
        sealed.frame["sim"].to_numpy(), trial.simulated["q"], rtol=MAX_RELATIVE_ERROR, atol=0.0
    )


@pytest.mark.parametrize(("period_start", "kept"), [(None, 0), ("2020-05-31", 1)])
def test_a_steady_mean_is_dated_only_by_its_period_start(period_start, kept) -> None:
    stamp = pd.DatetimeIndex([pd.Timestamp("2020-06-01")])
    observed = pd.Series(1.0, index=pd.date_range("2020-05-01", "2020-06-30", freq="D"))

    paired = pair(
        pd.Series([1.0], stamp), observed, method="mean", window=None, period_start=period_start
    )

    assert len(paired.frame) == 1
    assert len(paired.dated()) == kept
    if kept:
        assert paired.dated().index[0] == pd.Timestamp(period_start)


def test_nse_is_computed_on_the_declared_window_only() -> None:
    observed = _series(1)
    simulated = observed * 1.1
    # A spin-up year that disagrees wildly must not count.
    simulated[INDEX < "2016-01-01"] = 100.0

    result = score_metric(simulated, observed, RULE_2016, "nse")

    inside = INDEX >= "2016-01-01"
    expected = kernels.nse(simulated[inside].to_numpy(), observed[inside].to_numpy())
    assert result.value == pytest.approx(expected)
    assert result.value > 0.5
    assert (result.window_start, result.window_end) == (WINDOW_2016.start, WINDOW_2016.end)
    assert result.n_samples == 366
    assert result.metric_rule_version == METRIC_RULE_VERSION == "2"
    assert (result.window_name, result.window_role) == (HEADLINE_WINDOW, EVALUATION_ROLE)


def test_nse_n_counts_the_instants_both_series_carry_a_finite_value_at() -> None:
    observed = _series(1)
    simulated = observed.copy()
    observed[INDEX[-10:]] = np.nan
    simulated = simulated.drop(INDEX[366:371])

    result = score_metric(simulated, observed, RULE_2016, "nse")

    assert result.n_samples == 366 - 10 - 5
    assert result.value == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("index", "window", "n"),
    [
        (
            pd.date_range("2016-12-30 00:00", "2017-01-01 00:00", freq="6h"),
            DateWindow(start=date(2016, 12, 31), end=date(2016, 12, 31)),
            4,
        ),
        (
            pd.date_range("2016-01-01", "2016-01-10", freq="D", tz="UTC"),
            DateWindow(start=date(2016, 1, 3), end=date(2016, 1, 5)),
            3,
        ),
    ],
    ids=["last_day_included", "timezone_aware"],
)
def test_the_window_counts_its_own_days(index, window, n) -> None:
    series = pd.Series(np.arange(len(index), dtype=float), index=index)
    assert score_metric(series, series, MetricRule(window=window), "rmse").n_samples == n


def test_a_window_outside_the_data_gives_no_value_and_zero_samples() -> None:
    rule = MetricRule(window=DateWindow(start=date(2030, 1, 1), end=date(2030, 12, 31)))
    result = score_metric(_series(1), _series(2), rule, "nse")
    assert result.value is None and result.n_samples == 0
    assert result.window_start == date(2030, 1, 1)


def test_constant_observations_give_no_value_rather_than_nan() -> None:
    result = score_metric(_series(1), pd.Series(1.0, index=INDEX), RULE_2016, "nse")
    assert result.value is None and result.n_samples == 366


@pytest.mark.parametrize(
    ("simulated", "observed", "metric", "error", "match"),
    [
        (None, None, "r2", ValueError, "nse, kge, rmse, nse_log"),
        (pd.Series([1.0, 2.0]), pd.Series([1.0, 2.0]), "nse", TypeError, "indexed by time"),
    ],
)
def test_a_metric_that_cannot_be_read_is_refused(simulated, observed, metric, error, match):
    simulated = _series(1) if simulated is None else simulated
    observed = _series(2) if observed is None else observed
    with pytest.raises(error, match=match):
        score_metric(simulated, observed, RULE_2016, metric)


def test_a_configuration_without_metrics_nor_site_scores_nothing() -> None:
    from types import SimpleNamespace

    rule = MetricRule.from_config(SimpleNamespace(metrics=None, site=None))
    assert score_metric(_series(1), _series(2), rule, "nse").value is None


def test_a_perfect_run_scores_one_on_the_whole_panel() -> None:
    days = pd.date_range("2001-01-01", "2001-12-31", freq="D", tz="UTC")
    values = np.linspace(1.0, 4.0, len(days))
    rule = MetricRule(station=GAUGE, window=YEAR_2001)

    scores = score_timeseries(_frame(_closing(days), values, days, values), rule=rule)

    by_metric = _by_metric(scores)
    assert set(by_metric) == set(RUN_METRIC_NAMES)
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


@pytest.mark.parametrize(
    ("sim_days", "values", "period_start"),
    [
        (pd.date_range("2001-01-01", periods=10, freq="D", tz="UTC"), np.ones(10), None),
        (pd.DatetimeIndex([pd.Timestamp("2001-06-01", tz="UTC")]), [1.0], "2001-05-31"),
    ],
    ids=["never_meet_the_window", "a_steady_value"],
)
def test_a_pair_the_window_cannot_score_leaves_no_row(sim_days, values, period_start) -> None:
    obs_days = (
        pd.date_range("2015-01-01", periods=10, freq="D", tz="UTC")
        if period_start is None
        else pd.date_range("2001-01-01", "2001-12-31", freq="D", tz="UTC")
    )
    observed = np.linspace(1.0, 2.0, len(obs_days))

    scores = score_timeseries(
        _frame(sim_days, values, obs_days, observed),
        rule=MetricRule(station=GAUGE, window=YEAR_2001),
        period_start=period_start,
    )

    assert scores.rows == ()
    assert scores.score.value is None and scores.score.n_samples == 0


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


def test_the_run_directory_is_read_without_the_index(tmp_path, monkeypatch) -> None:
    from hydromodpy.results.catalog.facade import Catalog

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

    scores = score_timeseries(
        read_timeseries(tmp_path), rule=MetricRule(station=GAUGE, window=YEAR_2001)
    )

    assert scores.score.value == pytest.approx(kernels.nse(simulated, observed))
    assert scores.score.n_samples == 365


def test_a_run_without_series_has_an_empty_score(tmp_path) -> None:
    frame = read_timeseries(tmp_path)
    scores = score_timeseries(frame, rule=MetricRule(station=GAUGE, window=YEAR_2001))
    assert frame.empty
    assert scores.rows == ()
    assert scores.score.value is None


def _by(**windows: PeriodWindow) -> CalibratedBy:
    return CalibratedBy(
        session_id="sess0001", trial=3, session_status="completed", cost=0.2, windows=windows
    )


SEARCHED = PeriodWindow(role=CALIBRATION_ROLE, start=date(2020, 1, 5), end=date(2020, 1, 20))
KEPT_APART = PeriodWindow(role=VALIDATION_ROLE, start=date(2020, 1, 21), end=date(2020, 1, 31))


@pytest.mark.parametrize(
    ("by", "names"),
    [
        (None, []),
        (_by(), []),
        (_by(calibration=SEARCHED, validation=KEPT_APART), ["calibration"]),
        (_by(early=SEARCHED, late=SEARCHED), ["early", "late"]),
        (_by(**{HEADLINE_WINDOW: SEARCHED}), []),
    ],
    ids=["not_promoted", "no_window", "validation_left_out", "two_periods", "headline_name"],
)
def test_a_promoted_run_is_scored_on_each_calibration_period(by, names) -> None:
    headline = MetricRule(station=GAUGE, window=YEAR_2001)

    rules = calibration_rules(headline, by)

    assert [rule.window_name for rule in rules] == names
    for rule in rules:
        assert (rule.station, rule.window_role) == (GAUGE, CALIBRATION_ROLE)
        assert rule.window == DateWindow(start=SEARCHED.start, end=SEARCHED.end)


def _promoted_store(tmp_path, by: CalibratedBy | None):
    from tests._helpers.run_stores import open_run_store

    store = open_run_store(tmp_path / "demo", "promoted", n_cells=4, n_timesteps=30)
    store.facts.period_start = pd.Timestamp("2020-01-01", tz="UTC").to_pydatetime()
    store.facts.calibrated_by = by
    return store


@pytest.mark.parametrize("promoted", [False, True], ids=["headline_only", "promoted"])
def test_the_run_writes_one_row_set_per_calibration_period(tmp_path, promoted) -> None:
    from hydromodpy.core.site.config import SiteConfig

    days = pd.date_range("2020-01-01", periods=30, freq="D")
    observed = pd.Series(np.linspace(1.0, 2.0, 30), index=days)
    simulated = pd.Series(observed.to_numpy() * 1.05, index=days.shift(1, freq="D"))
    cfg = type(
        "Cfg",
        (),
        {
            "site": SiteConfig(name="nancon", gauge=GAUGE),
            "metrics": MetricsConfig(window=MetricsWindow(start="2020-01-01", end="2020-01-31")),
        },
    )()
    by = _by(calibration=SEARCHED, validation=KEPT_APART) if promoted else None
    with _promoted_store(tmp_path, by) as store:
        sid = store.sim_id
        store.write_timeseries(sid, GAUGE, "discharge", simulated)
        store.write_timeseries(sid, GAUGE, "discharge", observed, source="observed")

        score_run_under_its_rule(cfg, store=store)

        rows = store.facts.metrics
        headline = store.facts.score

    by_window = {(row.window_name, row.window_role) for row in rows}
    expected = {(HEADLINE_WINDOW, EVALUATION_ROLE)}
    if promoted:
        expected.add(("calibration", CALIBRATION_ROLE))
    assert by_window == expected
    assert headline.window_name == HEADLINE_WINDOW and headline.n_samples == 30
    searched = [row for row in rows if row.window_role == CALIBRATION_ROLE]
    assert {row.n_samples for row in searched} == ({16} if promoted else set())
    assert {row.metric_rule_version for row in rows} == {METRIC_RULE_VERSION}
    assert len(searched) == (len(RUN_METRIC_NAMES) if promoted else 0)
