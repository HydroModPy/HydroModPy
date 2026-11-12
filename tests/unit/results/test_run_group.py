"""A RunSet reads, ranks and tabulates several sealed runs together.

Scores are NSE values (-), and the best run of a set is the one with the highest NSE.
"""

from __future__ import annotations

from hydromodpy.results.run.group import RunSet
from hydromodpy.results.run.view import Run
from tests._helpers.run_builders import populate, runs, score

__all__ = ["runs"]


def test_iteration_yields_runs(runs):
    sids = [runs.open().sim_id for _ in range(2)]

    sims = list(RunSet(sids, runs.catalog()))

    assert len(sims) == 2
    assert all(isinstance(s, Run) for s in sims)


def test_best_and_worst_follow_the_score(runs):
    low, high = runs.open(), runs.open()
    score(low, 0.6)
    score(high, 0.9)

    group = RunSet([low.sim_id, high.sim_id], runs.catalog())

    assert group.best("nse").sim_id == high.sim_id
    assert group.worst("nse").sim_id == low.sim_id


def test_sort_by_score(runs):
    stores = [runs.open() for _ in range(3)]
    for store, value in zip(stores, (0.5, 0.9, 0.7), strict=True):
        score(store, value)
    group = RunSet([store.sim_id for store in stores], runs.catalog())

    ordered = group.sort_by("nse", ascending=False)

    assert ordered.sim_ids == [stores[1].sim_id, stores[2].sim_id, stores[0].sim_id]


def test_to_dataframe(runs):
    first, second = runs.open(), runs.open()
    populate(first)
    populate(second)

    df = RunSet([first.sim_id, second.sim_id], runs.catalog()).to_dataframe()

    assert len(df) == 2
    assert "sim_id" in df.columns


def test_an_empty_set(runs):
    runs.open()

    group = RunSet([], runs.catalog())

    assert group.count == 0
    assert group.parameters.empty
    assert group.metrics.empty
    assert group.to_dataframe().empty
