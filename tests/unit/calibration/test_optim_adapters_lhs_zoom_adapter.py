"""Zoomed Latin hypercube adapter (`optim.adapters.lhs_zoom_adapter`) on one log parameter.

Each level is a Latin hypercube in the zone the trials so far leave open. The cost is
a bowl in decades with its minimum at 1e-3.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.calibration.optim.adapters.lhs_zoom_adapter import LhsZoomAdapter
from hydromodpy.calibration.optim.cost_margin import IntervalWidth
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.method_config import LhsZoomMethodConfig
from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    build_optimizer,
    engine_traits,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from tests.unit.calibration._factories_search import make_space, result_of

BOUNDS = (1e-6, 1.0)


def _space() -> ParameterSpace:
    return ParameterSpace(
        [CalibParameter("x", *BOUNDS, search_space="log", sampling="log_uniform")]
    )


def _bowl(values) -> float:
    return (math.log10(values["x"]) + 3.0) ** 2 + 1.0


def _play(opt, cost=_bowl, *, batch: int = 100) -> list[list[float]]:
    """Ask, evaluate and tell until it converges. Return the values of each batch."""
    batches: list[list[float]] = []
    while not opt.converged():
        asked = opt.ask(batch)
        assert asked
        batches.append([s.values["x"] for s in asked])
        opt.tell([result_of(s, cost(s.values)) for s in asked])
    return batches


def test_traits_state_what_a_check_reads_before_a_solve() -> None:
    traits = engine_traits("lhs_zoom")

    assert traits.max_parameters == 1
    assert traits.fixed_plan
    assert traits.takes_interval_width
    assert traits.precision_option is None
    assert not traits.draws_a_normal


def test_the_budget_is_the_sum_of_the_levels() -> None:
    opt = build_optimizer("lhs_zoom", _space(), levels=[10, 6, 4], seed=1)

    assert opt.counted_budget.counts == (20,)
    assert build_optimizer("lhs_zoom", _space(), seed=1).counted_budget.counts == (40,)


def test_levels_are_served_one_after_the_other() -> None:
    opt = build_optimizer("lhs_zoom", _space(), levels=[12, 8], seed=3)

    first, second = _play(opt)

    assert (len(first), len(second)) == (12, 8)
    assert opt.converged()
    assert opt.ask(5) == []


def test_ask_is_never_empty_before_the_last_level_and_converged_waits_for_it() -> None:
    opt = build_optimizer("lhs_zoom", _space(), levels=[4, 3], seed=3)
    served = []
    while not opt.converged():
        asked = opt.ask(1)
        assert asked
        assert not opt.converged()
        served.extend(asked)
        opt.tell([result_of(asked[0], _bowl(asked[0].values))])

    assert len(served) == 7
    assert [s.trial_id for s in served] == list(range(1, 8))


def test_the_next_level_is_drawn_after_the_batch_is_told() -> None:
    opt = build_optimizer("lhs_zoom", _space(), levels=[4, 3], seed=3)
    asked = opt.ask(4)

    assert len(asked) == 4
    assert opt.ask(4) == []
    assert not opt.converged()


def test_every_point_of_a_level_is_in_the_zone_read_for_it() -> None:
    opt = build_optimizer("lhs_zoom", _space(), levels=[24, 16, 10], seed=5)

    batches = _play(opt)

    records = opt.zone_record()
    assert [r["size"] for r in records] == [24, 16, 10]
    assert (records[0]["low"], records[0]["high"]) == BOUNDS
    for batch, record in zip(batches, records, strict=True):
        assert all(record["low"] <= v <= record["high"] for v in batch)
    for earlier, later in zip(records, records[1:], strict=False):
        assert later["low"] >= earlier["low"]
        assert later["high"] <= earlier["high"]
    last = records[-1]
    assert last["narrowed"]
    assert last["low"] < 1e-3 < last["high"]
    assert math.log10(last["high"] / last["low"]) < 1.0


def test_each_level_is_a_latin_hypercube_of_its_zone() -> None:
    opt = build_optimizer("lhs_zoom", _space(), levels=[20, 10], seed=2)

    batches = _play(opt)

    for batch, record in zip(batches, opt.zone_record(), strict=True):
        edges = np.linspace(math.log10(record["low"]), math.log10(record["high"]), len(batch) + 1)
        strata = np.searchsorted(edges, np.log10(batch), side="right") - 1
        assert sorted(np.clip(strata, 0, len(batch) - 1)) == list(range(len(batch)))


def test_the_same_seed_draws_the_same_points_and_zones() -> None:
    first, second = (build_optimizer("lhs_zoom", _space(), seed=11) for _ in range(2))

    assert _play(first) == _play(second)
    assert first.zone_record() == second.zone_record()


def test_another_seed_draws_other_points() -> None:
    first = _play(build_optimizer("lhs_zoom", _space(), levels=[8, 6], seed=1))
    second = _play(build_optimizer("lhs_zoom", _space(), levels=[8, 6], seed=2))

    assert first[0] != second[0]


def test_a_lost_trial_counts_neither_in_the_margin_nor_as_a_neighbor() -> None:
    opt = build_optimizer("lhs_zoom", _space(), levels=[10, 5], seed=4)
    asked = opt.ask(10)
    told = []
    for i, s in enumerate(asked):
        if i % 3 == 0:
            told.append(
                EvaluationResult(trial_id=s.trial_id, sim_id=None, cost=math.nan, status="crashed")
            )
        else:
            told.append(result_of(s, _bowl(s.values)))
    opt.tell(told)

    opt.ask(5)

    second = opt.zone_record()[1]
    assert second["n_lost"] == 4
    assert second["best_cost"] == pytest.approx(
        min(t.cost for t in told if t.status == "completed")
    )


def test_a_flat_cost_leaves_the_box_and_says_it_was_not_narrowed() -> None:
    opt = build_optimizer("lhs_zoom", _space(), levels=[8, 6], seed=1)

    _play(opt, cost=lambda values: 0.4)

    second = opt.zone_record()[1]
    assert (second["low"], second["high"]) == pytest.approx(BOUNDS)
    assert second["narrowed"] is False
    assert (second["low_end"], second["high_end"]) == ("bound", "bound")


def test_a_search_with_no_solved_trial_keeps_the_box() -> None:
    opt = build_optimizer("lhs_zoom", _space(), levels=[4, 3], seed=1)
    asked = opt.ask(4)
    opt.tell(
        [
            EvaluationResult(trial_id=s.trial_id, sim_id=None, cost=math.nan, status="crashed")
            for s in asked
        ]
    )

    opt.ask(3)

    second = opt.zone_record()[1]
    assert second["narrowed"] is False
    assert second["best_cost"] is None
    assert opt.best() is None


def test_the_margin_is_the_one_the_phase_reads_its_interval_with() -> None:
    wide = IntervalWidth(10.0, "relative", "phase", False)
    narrow = IntervalWidth(0.01, "relative", "phase", False)
    zones = []
    for width in (narrow, wide):
        opt = build_optimizer("lhs_zoom", _space(), levels=[24, 8], seed=6, interval_width=width)
        _play(opt)
        zones.append(opt.zone_record()[1])

    assert zones[0]["margin"] == 0.01
    assert zones[0]["n_within"] < zones[1]["n_within"]
    assert zones[0]["high"] / zones[0]["low"] < zones[1]["high"] / zones[1]["low"]


def test_a_mesh_cell_margin_is_measured_on_the_first_level() -> None:
    cell = IntervalWidth(None, "absolute", "default", True, "one mesh cell")
    opt = build_optimizer("lhs_zoom", _space(), levels=[10, 5], seed=6, interval_width=cell)
    asked = opt.ask(10)
    opt.tell([result_of(s, _bowl(s.values), components={"net.cell_spacing_m": 0.5}) for s in asked])

    opt.ask(5)

    second = opt.zone_record()[1]
    assert (second["margin"], second["margin_kind"]) == (0.5, "absolute")
    assert second["narrowed"]


def test_a_mesh_cell_never_measured_leaves_the_box() -> None:
    cell = IntervalWidth(None, "absolute", "default", True, "one mesh cell")
    opt = build_optimizer("lhs_zoom", _space(), levels=[10, 5], seed=6, interval_width=cell)
    asked = opt.ask(10)
    opt.tell([result_of(s, _bowl(s.values)) for s in asked])

    opt.ask(5)

    assert opt.zone_record()[1]["narrowed"] is False


def test_the_engine_spends_the_sum_of_the_levels_and_exhausts_its_plan() -> None:
    space = _space()
    opt = build_optimizer("lhs_zoom", space, seed=9)

    session = CalibrationEngine(
        space=space,
        optimizer=opt,
        evaluator=lambda s: result_of(s, _bowl(s.values)),
        max_trials="auto",
        parallel=4,
    ).run()

    assert len(session.history) == 40
    assert session.max_trials == 40
    assert session.stop_state == "plan_exhausted"
    assert session.settled
    assert session.best.cost < 1.05


def test_progress_label_says_the_level() -> None:
    opt = build_optimizer("lhs_zoom", _space(), levels=[4, 3], seed=1)

    assert opt.progress_label() == "level 1 of 2"
    asked = opt.ask(4)
    opt.tell([result_of(s, 2.0) for s in asked])
    opt.ask(1)

    assert opt.progress_label() == "level 2 of 2, best 2"


@pytest.mark.parametrize("levels", [[24], [], [24, 1], [0, 8], [24, -3]])
def test_levels_that_are_no_zoom_are_refused(levels) -> None:
    with pytest.raises(ValueError, match="levels"):
        build_optimizer("lhs_zoom", _space(), levels=levels)
    with pytest.raises(ValidationError):
        LhsZoomMethodConfig(levels=levels)


def test_one_level_is_refused_with_the_advice_to_write_lhs() -> None:
    with pytest.raises(ValidationError, match="write method = 'lhs'"):
        LhsZoomMethodConfig(levels=[24])


def test_two_parameters_are_refused() -> None:
    with pytest.raises(ValueError, match="moves one parameter, got 2"):
        LhsZoomAdapter(make_space(("x", 0.0, 1.0), ("y", 0.0, 1.0)))


def test_the_defaults_are_two_levels_of_24_and_16() -> None:
    assert LhsZoomMethodConfig().levels == [24, 16]
