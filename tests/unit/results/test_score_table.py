"""A run is scored again after the fact, on any window, month mask and metric.

The pairing is the one of the seal, so a table with the seal's window holds the
sealed numbers, and a trial kernel that reads dates gives the same value here.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.criteria.series import METRICS, SAMPLED_BY_DATE
from hydromodpy.core.scoring.metric_table import (
    NETWORK_METRIC_NAMES,
    RUN_METRIC_NAMES,
    SERIES_METRIC_NAMES,
    TRIAL_METRIC_NAMES,
)
from hydromodpy.core.scoring.metrics import DATED_KERNELS
from hydromodpy.core.time.period_aggregation import check_months, periods_in_months
from hydromodpy.results.metric_rule import DateWindow, MetricRule
from hydromodpy.results.score import _KERNELS, score_timeseries
from hydromodpy.results.score_table import (
    SCORE_COLUMNS,
    check_metrics,
    resolve_windows,
    score_table,
)

GAUGE = "J0014010"


def _timeseries(freq: str = "D", seed: int = 4) -> pd.DataFrame:
    """Simulated stamps close their period, observations stamp its start."""
    rng = np.random.default_rng(seed)
    days = pd.date_range("2015-01-01", "2017-12-31", freq="D", tz="UTC")
    obs = pd.Series(
        2.0 + np.sin(np.arange(days.size) / 58.0) + rng.normal(0, 0.1, days.size), index=days
    )
    sim = obs * 1.05 + rng.normal(0, 0.1, days.size)
    sim.index = sim.index.shift(1, freq="D")
    if freq == "ME":
        obs = obs.resample("MS").mean()
        sim = obs * 1.05
        sim.index = sim.index + pd.offsets.MonthBegin(1)

    def rows(series: pd.Series, source: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "station_id": GAUGE,
                "variable": "discharge",
                "source": source,
                "time": series.index,
                "value": series.to_numpy(),
            }
        )

    return pd.concat([rows(sim, "simulated"), rows(obs, "observed")], ignore_index=True)


def _table(series, windows, **kwargs) -> pd.DataFrame:
    metrics = kwargs.pop("metrics", ("nse", "rmse"))
    start = pd.Timestamp("2015-01-01")
    return score_table(series, windows, metrics=metrics, period_start=start, **kwargs)


def test_columns_and_one_row_per_metric_and_window() -> None:
    series = _timeseries()
    windows = resolve_windows(
        {"a": ("2015-01-01", "2015-12-31"), "b": ("2016-01-01", None)}, series, "2015-01-01"
    )
    table = _table(series, windows)
    assert tuple(table.columns) == SCORE_COLUMNS
    assert len(table) == 4
    assert set(table["window_name"]) == {"a", "b"}


def test_open_bounds_read_the_series() -> None:
    series = _timeseries()
    ((name, window),) = resolve_windows({"all": (None, None)}, series, "2015-01-01")
    assert window.start == date(2015, 1, 1)
    assert window.end == date(2018, 1, 1)
    assert name == "all"


def test_window_list_is_named_by_its_days() -> None:
    series = _timeseries()
    window = DateWindow(start=date(2016, 1, 1), end=date(2016, 12, 31))
    assert resolve_windows([window], series)[0][0] == "2016-01-01/2016-12-31"


def test_equals_the_seal_rule() -> None:
    series = _timeseries()
    window = DateWindow(start=date(2016, 1, 1), end=date(2016, 12, 31))
    sealed = score_timeseries(
        series,
        rule=MetricRule(station=GAUGE, window=window),
        period_start=pd.Timestamp("2015-01-01"),
    )
    table = _table(series, [("metrics", window)], metrics=RUN_METRIC_NAMES)
    expected = {row.metric: row.value for row in sealed.rows}
    got = dict(zip(table["metric"], table["value"], strict=True))
    assert set(got) == set(expected)
    for name, value in expected.items():
        assert got[name] == value or (pd.isna(value) and pd.isna(got[name]))


def test_one_period_late_trap() -> None:
    """The day 2016-12-31 is read at the stamp 2017-01-01, so a window ending that day keeps it."""
    series = _timeseries()
    window = DateWindow(start=date(2016, 1, 1), end=date(2016, 12, 31))
    table = _table(series, [("y", window)])
    assert set(table["n_samples"]) == {366}
    shifted = DateWindow(start=date(2016, 1, 1), end=date(2016, 12, 30))
    assert set(_table(series, [("y", shifted)])["n_samples"]) == {365}


def test_months_keep_whole_months_of_the_window() -> None:
    series = _timeseries()
    window = DateWindow(start=date(2015, 1, 1), end=date(2017, 12, 31))
    table = _table(series, [("s", window)], months=[6, 7, 8])
    assert set(table["n_samples"]) == {92 * 3}
    assert set(table["months"]) == {"6,7,8"}


def test_months_on_a_monthly_series() -> None:
    series = _timeseries("ME")
    window = DateWindow(start=date(2015, 1, 1), end=date(2018, 1, 1))
    table = _table(series, [("jan", window)], months=[1])
    assert set(table["n_samples"]) == {3}


def test_months_keep_a_period_only_if_every_day_is_in() -> None:
    stamps = pd.DatetimeIndex(["2015-02-01", "2015-03-01", "2015-04-01"])
    kept = periods_in_months(stamps, method="mean", months=[2, 4], period_start="2015-01-01")
    assert kept.tolist() == [False, True, False]
    point = periods_in_months(stamps, method="point", months=[2, 4])
    assert point.tolist() == [True, False, True]


@pytest.mark.parametrize("bad", [[], [0], [13], [1.5, 20]])
def test_months_outside_the_calendar_are_refused(bad) -> None:
    with pytest.raises(ValueError, match="calendar months"):
        check_months(bad)


def test_station_filter() -> None:
    series = _timeseries()
    window = DateWindow(start=date(2016, 1, 1), end=date(2016, 12, 31))
    assert len(_table(series, [("y", window)], station="other")) == 0
    assert len(_table(series, [("y", window)], station=GAUGE)) == 2


def test_the_callable_set_is_the_table_minus_network() -> None:
    assert set(SERIES_METRIC_NAMES) == set(METRIC_NAMES_OF_TABLE()) - set(NETWORK_METRIC_NAMES)
    kernels = set(_KERNELS) | set(DATED_KERNELS)
    assert set(SERIES_METRIC_NAMES) <= kernels


def METRIC_NAMES_OF_TABLE() -> tuple[str, ...]:
    from hydromodpy.core.scoring.metric_table import METRIC_SPECS

    return tuple(METRIC_SPECS)


def test_the_seal_set_is_unchanged() -> None:
    assert RUN_METRIC_NAMES == (
        "nse",
        "kge",
        "rmse",
        "nse_log",
        "mae",
        "bias",
        "pbias",
        "correlation",
        "kge_r",
        "kge_alpha",
        "kge_beta",
        "bfi_gap",
    )
    assert SAMPLED_BY_DATE == {"nse_delta", "nse_seasonal", "reservoir", "bfi_error"}


@pytest.mark.parametrize("name", sorted(set(TRIAL_METRIC_NAMES) - set(NETWORK_METRIC_NAMES)))
def test_trial_kernel_value_is_the_table_value(name) -> None:
    """A metric a trial scores gives, on the same pairs and dates, the trial's own score."""
    series = _timeseries()
    window = DateWindow(start=date(2015, 1, 1), end=date(2018, 1, 1))
    table = _table(series, [("w", window)], metrics=(name,))
    obs = series[series["source"] == "observed"]["value"].to_numpy()
    sim = series[series["source"] == "simulated"]["value"].to_numpy()
    days = np.arange(obs.size, dtype=float)
    kernel = METRICS[name]
    kwargs = {"sample_days": 1.0, "times_days": days} if name in SAMPLED_BY_DATE else {}
    direct = float(kernel(sim, obs, **kwargs))
    value = table["value"].iloc[0]
    assert value == pytest.approx(direct, rel=1e-9, abs=1e-12) or (
        pd.isna(value) and pd.isna(direct)
    )


def test_network_metric_is_refused_with_its_function() -> None:
    with pytest.raises(ValueError, match="score_network"):
        check_metrics(["distance_gap"], None)


def test_consecutive_metric_is_refused_on_months() -> None:
    with pytest.raises(ValueError, match="consecutive days"):
        check_metrics(["bfi_gap"], [6])
    assert "bfi_error" not in check_metrics(None, [6])
    assert "bfi_error" in check_metrics(None, None)


def test_unknown_metric_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown metric"):
        check_metrics(["nse_x"], None)


def test_sealed_run_scores_as_its_seal(tmp_path) -> None:
    """``run.score()`` with no argument holds the values the seal wrote, and a set stacks runs."""
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from hydromodpy.core.site.config import SiteConfig
    from hydromodpy.results.metric_rule import MetricsConfig, MetricsWindow
    from hydromodpy.results.run.view import open_run_dir
    from hydromodpy.results.score import score_run_under_its_rule
    from hydromodpy.results.storage.attempt import close_sealed_attempt
    from hydromodpy.results.storage.sealing import seal_completed
    from tests._helpers.run_stores import open_run_store

    series = _timeseries()
    cfg = SimpleNamespace(
        site=SiteConfig(name="nancon", gauge=GAUGE),
        metrics=MetricsConfig(window=MetricsWindow(start="2016-01-01", end="2016-12-31")),
    )
    with open_run_store(tmp_path / "demo", "one", n_cells=4, n_timesteps=3) as store:
        store.facts.period_start = datetime(2015, 1, 1, tzinfo=UTC)
        for source in ("simulated", "observed"):
            rows = series[series["source"] == source]
            store.write_timeseries(
                store.sim_id,
                GAUGE,
                "discharge",
                pd.Series(rows["value"].to_numpy(), index=pd.DatetimeIndex(rows["time"])),
                source=source,
            )
        score_run_under_its_rule(cfg, store=store)
        run_dir = store.run_dir
        seal_completed(store)
    close_sealed_attempt(run_dir)
    run = open_run_dir(run_dir)
    sealed = run.metrics
    sealed = sealed[sealed["window_name"] == "metrics"].set_index("metric")["value"]
    table = run.score().set_index("metric")["value"]
    assert set(sealed.index) == set(RUN_METRIC_NAMES)
    for name in RUN_METRIC_NAMES:
        assert table[name] == sealed[name] or (pd.isna(table[name]) and pd.isna(sealed[name]))
    assert set(table.index) == set(SERIES_METRIC_NAMES)
    assert run.score(months=[6])["months"].eq("6").all()


def test_open_window_bounds_close_on_the_simulated_rows_only() -> None:
    from hydromodpy.results.score_table import close_window, resolve_windows

    rows = pd.DataFrame(
        {
            "station_id": ["s", "s", "g", "g"],
            "variable": ["q"] * 4,
            "source": ["simulated", "simulated", "observed", "observed"],
            "time": pd.to_datetime(
                ["2001-02-01", "2001-03-01", "1990-01-01", "2020-01-01"], utc=True
            ),
            "value": [1.0, 2.0, 1.0, 2.0],
        }
    )

    ((_, window),) = resolve_windows({"all": (None, None)}, rows)

    assert (window.start, window.end) == (date(2001, 2, 1), date(2001, 3, 1))
    assert close_window(None, date(2002, 1, 1), date(2001, 1, 1), date(2003, 1, 1)) == (
        date(2001, 1, 1),
        date(2002, 1, 1),
    )
