"""An observed gauge meets the series of its own name and no other.

A run that simulates discharge at one station (the catchment outlet) used to
score every observed gauge against that series, an upstream gauge included,
and wrote rows at its name. The rule station lost that fallback last, once the
run wrote a series under its name. A gauge without a simulated series of its
name is not scored, and the log and the sealed README say so.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.fit_metrics import score_run_under_its_rule, score_timeseries
from hydromodpy.results.metric_rule import DateWindow, MetricRule
from hydromodpy.results.readme import render_run_readme
from hydromodpy.results.storage.sealing import build_record
from hydromodpy.results.validity_rules import LabelResult

OUTLET = "J0014010"
UPSTREAM = "J0013010"
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


def _outlet_and_upstream(simulated_at: str = OUTLET) -> pd.DataFrame:
    days = pd.date_range("2001-01-01", "2001-12-31", freq="D", tz="UTC")
    values = np.linspace(1.0, 4.0, len(days))
    return pd.DataFrame(
        _rows(simulated_at, "discharge", days.shift(1, freq="D"), values)
        + _rows(OUTLET, "discharge", days, values, source="observed")
        + _rows(UPSTREAM, "discharge", days, values * 0.3, source="observed")
    )


def test_an_upstream_gauge_gets_no_row_and_the_log_says_why(caplog) -> None:
    rule = MetricRule(station=OUTLET, window=YEAR_2001)

    with caplog.at_level(logging.WARNING, logger="hydromodpy.results.fit_metrics"):
        scores = score_timeseries(_outlet_and_upstream(), rule=rule)

    assert {row.station for row in scores.rows} == {OUTLET}
    assert scores.score.station == OUTLET and scores.score.value is not None
    assert [(item.station, item.variable) for item in scores.unscored] == [(UPSTREAM, "discharge")]
    warned = [record.getMessage() for record in caplog.records]
    assert any(UPSTREAM in message and "not scored" in message for message in warned)


@pytest.mark.parametrize("station", [None, OUTLET, UPSTREAM])
def test_no_gauge_borrows_the_catchment_series(station) -> None:
    frame = _outlet_and_upstream(simulated_at="catchment")

    scores = score_timeseries(frame, rule=MetricRule(station=station, window=YEAR_2001))

    assert scores.rows == ()
    assert scores.score.value is None
    assert {item.station for item in scores.unscored} == {OUTLET, UPSTREAM}
    assert {item.simulated_at for item in scores.unscored} == {("catchment",)}


def test_the_sealed_readme_names_the_gauge_that_was_not_scored(tmp_path) -> None:
    from hydromodpy.core.site import SiteConfig
    from hydromodpy.results.fit_metrics import UNSCORED_OBSERVATIONS_CHECK
    from hydromodpy.results.metric_rule import MetricsConfig, MetricsWindow
    from tests._helpers.run_stores import open_run_store

    index = pd.date_range("2020-01-02", periods=10, freq="D")
    observed = pd.Series(np.linspace(1.0, 2.0, 10), index=index)
    cfg = SimpleNamespace(
        site=SiteConfig(name="nancon", gauge=OUTLET),
        metrics=MetricsConfig(window=MetricsWindow(start="2020-01-01", end="2020-01-31")),
    )
    with open_run_store(tmp_path / "demo", "upstream", n_cells=4, n_timesteps=10) as store:
        sid = store.sim_id
        store.facts.period_start = pd.Timestamp("2020-01-01", tz="UTC").to_pydatetime()
        store.write_timeseries(sid, OUTLET, "discharge", observed * 1.0)
        store.write_timeseries(sid, OUTLET, "discharge", observed, source="observed")
        store.write_timeseries(sid, UPSTREAM, "discharge", observed * 0.3, source="observed")

        score_run_under_its_rule(cfg, store=store)

        assert {row.station for row in store.facts.metrics} == {OUTLET}
        failed = [v for v in store.facts.validities if not v.passed]
        assert [v.name for v in failed] == [UNSCORED_OBSERVATIONS_CHECK]
        assert not failed[0].fatal
        record = build_record(store, ended_at=datetime.now(UTC))

    label = LabelResult("unchecked", "2", (), ())
    text = render_run_readme(record, None, label, manifest_sha256="0" * 64)
    assert UPSTREAM in text and "not scored" in text
