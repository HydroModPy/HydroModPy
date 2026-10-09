"""``@best:<metric>`` picks the best fit whatever the direction of the metric.

It used to take the highest value, so ``@best:rmse`` named the worst run. Best
is now the highest ``nse``, the lowest ``rmse`` and the ``pbias`` closest to
zero, for the selector, ``Catalog.best`` and ``RunSet.best`` alike.
"""

from __future__ import annotations

import uuid

import pytest

from hydromodpy.results.catalog import SimulationNotFoundError
from hydromodpy.results.catalog.constants import (
    METRIC_SENSE,
    OUTLET_STATION,
    UnrankedMetricError,
)
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def scored(tmp_path):
    """Three completed runs: a, b, c, scored on nse, rmse and pbias."""
    scores = {
        "a": {"nse": 0.6, "rmse": 2.0, "pbias": -20.0},
        "b": {"nse": 0.9, "rmse": 0.5, "pbias": 5.0},
        "c": {"nse": 0.3, "rmse": 3.0, "pbias": 30.0},
    }
    with simulation_catalog(tmp_path / "ws") as cat:
        ids = {}
        for name, metrics in scores.items():
            sid = str(uuid.uuid4())
            cat.register_simulation(sid, project="p", solver="modflow6", name=name)
            for metric, value in metrics.items():
                cat.write_metric(sid, OUTLET_STATION, metric, value)
            cat.write_metric(sid, OUTLET_STATION, "unknown_score", 1.0)
            cat.finalize(sid, "completed")
            ids[name] = sid
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
    group = cat.find(project="p")
    assert group.best(metric).sim_id == ids[best]
    assert group.worst(metric).sim_id == ids[worst]


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
    with pytest.raises(UnrankedMetricError):
        cat.find(project="p").best("unknown_score")


def test_the_table_agrees_with_the_seeded_definitions(tmp_path) -> None:
    """The catalog seeds ``metric_definitions``; the two never disagree."""
    sense_of = {True: "max", False: "min", None: "zero"}
    with simulation_catalog(tmp_path / "ws") as cat:
        rows = cat.backend.fetch_all("SELECT metric_name, higher_is_better FROM metric_definitions")
    assert rows
    for name, higher in rows:
        assert METRIC_SENSE[name] == sense_of[higher], name
