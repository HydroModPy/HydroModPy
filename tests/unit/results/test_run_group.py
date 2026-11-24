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


def _fake_set(monkeypatch, outcomes):
    class Fake:
        def __init__(self, sim_id, outcome):
            self.sim_id, self._outcome = sim_id, outcome

        def score(self, *args, **kwargs):
            if isinstance(self._outcome, Exception):
                raise self._outcome
            return self._outcome

    fakes = [Fake(f"s{i}", o) for i, o in enumerate(outcomes)]
    monkeypatch.setattr(RunSet, "__iter__", lambda self: iter(fakes))
    monkeypatch.setattr(RunSet, "_with_parameters", lambda self, table: table)
    return RunSet([], None)


def test_score_skips_a_run_that_raises_value_error_and_an_empty_frame(monkeypatch, caplog):
    import pandas as pd
    import pytest

    from hydromodpy.core.exceptions import NothingThereError

    good = pd.DataFrame({"sim_id": ["s0"], "value": [1.0]})
    group = _fake_set(monkeypatch, [good, ValueError("open window"), pd.DataFrame()])

    table = group.score()

    assert list(table["sim_id"]) == ["s0"]
    assert "s1" in caplog.text
    group = _fake_set(monkeypatch, [ValueError("bad"), pd.DataFrame()])
    with pytest.raises(NothingThereError):
        group.score()
