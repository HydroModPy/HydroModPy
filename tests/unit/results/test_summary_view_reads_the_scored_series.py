"""The summary views carry the headline score of a run under its metric rule.

``v_simulation_summary.nse`` is the NSE the run sealed at the declared station
over the declared window, with that window beside it; a run sealed without a
window has no score and the view says NULL.
"""

from __future__ import annotations

from datetime import date

from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.metric_rule import DateWindow
from tests._helpers.sealed_runs import make_project, seal_run


def _summary(root, name: str) -> tuple:
    with Catalog(root) as cat:
        return cat.backend.fetch_one(
            "SELECT nse, score_window_start, score_window_end, n_samples, metric_rule_version "
            "FROM v_simulation_summary WHERE name = ?",
            [name],
        )


def test_a_scored_run_shows_its_score_and_its_window(tmp_path) -> None:
    root = make_project(tmp_path / "demo")
    window = DateWindow(start=date(2018, 1, 1), end=date(2019, 12, 31))
    seal_run(root, "scored", nse=0.7, window=window)
    rebuild_index(root)

    assert _summary(root, "scored") == (0.7, window.start, window.end, 1827, "1")


def test_a_run_without_a_window_has_no_score(tmp_path) -> None:
    root = make_project(tmp_path / "demo")
    seal_run(root, "unscored", nse=None, window=None)
    rebuild_index(root)

    assert _summary(root, "unscored") == (None, None, None, None, None)


def test_the_best_per_project_follows_the_headline_score(tmp_path) -> None:
    root = make_project(tmp_path / "demo")
    seal_run(root, "low", nse=0.3)
    best = seal_run(root, "high", nse=0.9)
    rebuild_index(root)

    with Catalog(root) as cat:
        row = cat.backend.fetch_one("SELECT CAST(sim_id AS VARCHAR), nse FROM v_best_per_project")
    assert row == (best, 0.9)
