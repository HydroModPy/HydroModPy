"""The rule of a run: its station, its window, its periods and its version."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from hydromodpy.results.metric_rule import (
    CALIBRATION_ROLE,
    EVALUATION_ROLE,
    HEADLINE_WINDOW,
    METRIC_RULE_VERSION,
    DateWindow,
    MetricRule,
    MetricScore,
    PeriodWindow,
    calibration_extent,
)

WINDOW = DateWindow(start=date(2016, 1, 1), end=date(2016, 12, 31))
RULE = MetricRule(station="J0014010", window=WINDOW)


def test_the_window_is_ordered_and_the_rule_refuses_unknown_keys():
    with pytest.raises(ValidationError, match="before it starts"):
        DateWindow(start=date(2020, 1, 1), end=date(2016, 1, 1))
    with pytest.raises(ValidationError, match="stations"):
        MetricRule.model_validate({"stations": ["J0014010"]})
    assert WINDOW.contains(date(2016, 6, 1)) and not WINDOW.contains(date(2015, 12, 31))


def test_the_score_columns_are_the_ones_of_the_simulation_table():
    from hydromodpy.results.storage.parquet_schemas import SIMULATION_SCHEMA

    # The table of a run keeps the one headline period: its name and role are constants.
    columns = set(MetricScore.model_fields) - {"metric", "value", "window_name", "window_role"}
    assert columns == {
        "station",
        "variable",
        "window_start",
        "window_end",
        "n_samples",
        "n_clipped",
        "metric_rule_version",
    }
    carried = {"score_station", "score_variable", "score_window_start", "score_window_end"}
    assert carried | {"n_samples", "metric_rule_version"} <= set(SIMULATION_SCHEMA.names)
    assert not {"window_name", "n_clipped"} & set(SIMULATION_SCHEMA.names)


def test_a_period_gives_each_case_its_own_days_and_the_search_the_span_of_its_calibration():
    own = DateWindow(start=date(2010, 1, 1), end=date(2012, 12, 31))
    period = PeriodWindow(
        role=CALIBRATION_ROLE, start=date(2010, 1, 1), end=date(2014, 12, 31), by_case={"a": own}
    )
    other = PeriodWindow(role="validation", start=date(2000, 1, 1), end=date(2001, 12, 31))

    assert period.of("a") == own
    assert period.of("b") == DateWindow(start=period.start, end=period.end)
    assert calibration_extent({"calibration": period, "check": other}) == DateWindow(
        start=period.start, end=period.end
    )
    assert calibration_extent({"check": other}) is None
    assert calibration_extent({}) is None
    with pytest.raises(ValidationError, match="before it starts"):
        PeriodWindow(role=CALIBRATION_ROLE, start=date(2014, 1, 1), end=date(2010, 1, 1))


def _config(**sections):
    """The two sections a rule is read from, as a configuration exposes them."""
    from types import SimpleNamespace

    return SimpleNamespace(metrics=sections.get("metrics"), site=sections.get("site"))


def test_the_rule_of_a_configuration_takes_the_gauge_of_the_site():
    from hydromodpy.core.site.config import SiteConfig
    from hydromodpy.results.metric_rule import MetricsConfig

    config = _config(
        site=SiteConfig(name="nancon", gauge="J0014010"),
        metrics=MetricsConfig(window={"start": "2016-01-01", "end": "2016-12-31"}),
    )

    assert MetricRule.from_config(config) == MetricRule(station="J0014010", window=WINDOW)


def test_the_metrics_station_wins_over_the_gauge_of_the_site():
    from hydromodpy.core.site.config import SiteConfig
    from hydromodpy.results.metric_rule import MetricsConfig

    config = _config(
        site=SiteConfig(name="nancon", gauge="J0014010"),
        metrics=MetricsConfig(station="J0014020"),
    )

    rule = MetricRule.from_config(config)
    assert rule.station == "J0014020"
    assert rule.window is None


def test_a_configuration_without_metrics_nor_site_scores_nothing():
    rule = MetricRule.from_config(_config())
    assert rule == MetricRule()
    assert rule.window is None


def test_a_rule_reads_the_headline_window_under_the_current_version():
    assert (RULE.version, RULE.window_name, RULE.window_role) == (
        METRIC_RULE_VERSION,
        HEADLINE_WINDOW,
        EVALUATION_ROLE,
    )
    assert METRIC_RULE_VERSION == "2"
