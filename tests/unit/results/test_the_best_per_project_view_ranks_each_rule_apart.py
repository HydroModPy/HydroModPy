"""``v_best_per_project`` ranks each rule apart: it never makes two windows compete."""

from __future__ import annotations

from datetime import date

import pytest

from hydromodpy.results.catalog import Catalog, rebuild_index
from hydromodpy.results.metric_rule import DateWindow
from tests._helpers.sealed_runs import make_project, seal_run

pytestmark = pytest.mark.unit

FIVE_YEARS = DateWindow(start=date(2016, 1, 1), end=date(2020, 12, 31))
NINETY_DAYS = DateWindow(start=date(2020, 10, 1), end=date(2020, 12, 29))


@pytest.fixture
def windows(tmp_path):
    """One site, one gauge, two windows: a short good score and a long poor one."""
    root = make_project(tmp_path / "demo")
    ids = {
        "short": seal_run(root, "short", nse=0.97, window=NINETY_DAYS),
        "long": seal_run(root, "long", nse=0.60, window=FIVE_YEARS),
        "long2": seal_run(root, "long2", nse=0.55, window=FIVE_YEARS),
    }
    rebuild_index(root)
    with Catalog(root) as cat:
        yield cat, ids


def test_each_rule_has_its_own_best_run(windows) -> None:
    cat, ids = windows
    rows = cat.backend.fetch_all(
        "SELECT CAST(sim_id AS VARCHAR), nse, score_window_start FROM v_best_per_project "
        "ORDER BY score_window_start"
    )
    assert rows == [
        (ids["long"], 0.60, FIVE_YEARS.start),
        (ids["short"], 0.97, NINETY_DAYS.start),
    ]
