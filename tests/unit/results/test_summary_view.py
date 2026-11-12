"""The summary views carry the headline score of a run under its metric rule.

``v_simulation_summary.nse`` is the NSE the run sealed at the declared station
over the declared window, with that window beside it; a run sealed without a
window has no score and the view says NULL.
"""

from __future__ import annotations

from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from tests._helpers.sealed_runs import make_project, seal_run


def _summary(root, name: str) -> tuple:
    with Catalog(root) as cat:
        return cat.backend.fetch_one(
            "SELECT nse, score_window_start, score_window_end, n_samples, metric_rule_version "
            "FROM v_simulation_summary WHERE name = ?",
            [name],
        )


def test_a_run_without_a_window_has_no_score(tmp_path) -> None:
    root = make_project(tmp_path / "demo")
    seal_run(root, "unscored", nse=None, window=None)
    rebuild_index(root)

    assert _summary(root, "unscored") == (None, None, None, None, None)
