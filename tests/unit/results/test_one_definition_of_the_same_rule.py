"""Two scores are comparable under one rule, defined once, refused with one exception.

The rule was written twice: ``project/summary.py`` over the columns of the
index (``score_station``, ``score_variable``) and ``results/run/sealed.py`` over
those of a headline row, with two exceptions (``MixedWindowsError`` and a bare
``ValueError``). The summary left the station out of the rule when no ``by``
was given, so ``hmp catalog ls --best`` ranked runs scored at different
stations together.
"""

from __future__ import annotations

import pandas as pd
import pytest

from hydromodpy.core.exceptions import DataError
from hydromodpy.results.run import ranking
from hydromodpy.results.run.sealed import MixedWindowsError

pytestmark = pytest.mark.unit


def _rows(*scored: tuple[str, str, str, float]) -> pd.DataFrame:
    """One row per run: ``(site, station, variable, nse)``, one window and one rule version."""
    return pd.DataFrame(
        [
            {
                "name": f"run{index}",
                "site": site,
                "score_station": station,
                "score_variable": variable,
                "window_start": "2016-01-01",
                "window_end": "2020-12-31",
                "metric_rule_version": "1",
                "nse": nse,
            }
            for index, (site, station, variable, nse) in enumerate(scored)
        ]
    )


def test_the_exception_is_one_class_of_the_data_errors() -> None:
    assert issubclass(MixedWindowsError, DataError)
    assert not hasattr(ranking, "MixedWindowsError")


def test_runs_scored_at_different_stations_are_not_ranked_together() -> None:
    frame = _rows(("a", "J001", "discharge", 0.8), ("b", "J002", "discharge", 0.6))

    with pytest.raises(MixedWindowsError, match="J001") as refused:
        ranking.rank_rows(frame, "nse")
    assert "J002" in str(refused.value)
    assert list(ranking.rank_rows(frame, "nse", mixed_windows=True)["name"]) == ["run0", "run1"]


def test_each_site_keeps_its_own_station_when_ranked_by_site() -> None:
    frame = _rows(
        ("a", "J001", "discharge", 0.8),
        ("a", "J001", "discharge", 0.9),
        ("b", "J002", "discharge", 0.6),
    )

    best = ranking.rank_rows(frame, "nse", by="site")

    assert list(best["name"]) == ["run1", "run2"]


def test_two_stations_inside_one_site_are_refused() -> None:
    frame = _rows(("a", "J001", "discharge", 0.8), ("a", "J002", "discharge", 0.9))

    with pytest.raises(MixedWindowsError, match="site a"):
        ranking.rank_rows(frame, "nse", by="site")


def test_two_variables_are_refused_across_the_whole_cohort() -> None:
    frame = _rows(("a", "J001", "discharge", 0.8), ("b", "P002", "groundwater_level", 0.9))

    with pytest.raises(MixedWindowsError, match="groundwater_level"):
        ranking.rank_rows(frame, "nse", by="site")


def test_the_direction_of_a_metric_is_ranked_by_one_key() -> None:
    from hydromodpy.project.launch import summary
    from hydromodpy.results.run import group

    assert ranking.rank_key is group.rank_key
    assert not hasattr(summary, "rank_key")
