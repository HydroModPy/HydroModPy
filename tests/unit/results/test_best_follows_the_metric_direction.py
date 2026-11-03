"""``@best:<metric>`` picks the best fit whatever the direction of the metric.

It used to take the highest value, so ``@best:rmse`` named the worst run. Best
is now the highest ``nse``, the lowest ``rmse`` and the ``pbias`` closest to
zero, for the selector and ``Catalog.best`` alike. ``RunSet.best`` is covered
by ``test_group.py``.
"""

from __future__ import annotations

import pytest

from hydromodpy.results.catalog import Catalog, SimulationNotFoundError
from hydromodpy.results.catalog.constants import UnrankedMetricError
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.metric_rows import headline_row, headline_score
from tests._helpers.run_stores import open_run_store


@pytest.fixture
def scored(tmp_path):
    """Three sealed runs: a, b, c, scored under the rule on nse, rmse and pbias.

    The derive step records one row per metric and the headline NSE in
    ``facts.score``. The rank under the rule reads that headline.
    """
    scores = {
        "a": {"nse": 0.6, "rmse": 2.0, "pbias": -20.0},
        "b": {"nse": 0.9, "rmse": 0.5, "pbias": 5.0},
        "c": {"nse": 0.3, "rmse": 3.0, "pbias": 30.0},
    }
    project = tmp_path / "p"
    ids = {}
    for name, metrics in scores.items():
        store = open_run_store(project, name, create_zarr=False)
        sid = store.sim_id
        for metric, value in {**metrics, "unknown_score": 1.0}.items():
            store.facts.put_metric(headline_row(metric, value, n_samples=1827))
        store.facts.score = headline_score(metrics["nse"], n_samples=1827)
        seal_completed(store)
        ids[name] = sid
    rebuild_index(project)
    with Catalog(project) as cat:
        yield cat, ids


@pytest.mark.parametrize(
    ("metric", "best", "worst"),
    [("nse", "b", "c"), ("rmse", "b", "c"), ("pbias", "b", "c")],
)
def test_the_selector_follows_the_metric(scored, metric, best, worst) -> None:
    cat, ids = scored
    assert cat.resolve(f"@best:{metric}") == ids[best]
    assert cat.resolve(f"@worst:{metric}") == ids[worst]
    assert cat.best("p", metric).sim_id == ids[best]
    assert cat.worst("p", metric).sim_id == ids[worst]


def test_rank_lists_best_first(scored) -> None:
    cat, ids = scored
    assert cat.rank("p", "rmse", n=3).sim_ids == [ids["b"], ids["a"], ids["c"]]
    # The raw order stays reachable for a metric with no direction.
    assert cat.rank("p", "rmse", n=3, ascending=False).sim_ids == [ids["c"], ids["a"], ids["b"]]


def test_a_metric_without_direction_is_refused(scored) -> None:
    cat, _ids = scored
    with pytest.raises(SimulationNotFoundError, match="no declared direction"):
        cat.resolve("@best:unknown_score")
    with pytest.raises(UnrankedMetricError):
        cat.best("p", "unknown_score")
