"""Tests of `optim.adapters.optuna_adapter` and `optim.adapters.random_search_adapter`."""

from __future__ import annotations

import pytest

from hydromodpy.calibration.optim.optimizer import EvaluationResult, build_optimizer
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from tests.unit.calibration._factories import two_dim_space
from tests.unit.calibration._factories_search import result_of

pytest.importorskip("optuna")

_METHODS = [
    ("random_search", {}),
    ("optuna", {"sampler": "random"}),
    ("optuna", {"sampler": "tpe"}),
]
_IDS = ["random_search", "optuna_random", "optuna_tpe"]


def _bowl(values: dict[str, float]) -> float:
    return (values["x"] - 0.3) ** 2 + (values["y"] + 1.0) ** 2


def _run(method: str, options: dict, *, seed: int, trials: int = 12) -> list[EvaluationResult]:
    optimizer = build_optimizer(method, two_dim_space(), seed=seed, **options)
    results = []
    for _ in range(trials):
        (suggestion,) = optimizer.ask(1)
        results.append(result_of(suggestion, _bowl(suggestion.values)))
        optimizer.tell(results[-1:])
    assert optimizer.best() is not None
    assert optimizer.best().cost == min(r.cost for r in results)
    assert not optimizer.converged()
    return results


@pytest.mark.parametrize(("method", "options"), _METHODS, ids=_IDS)
def test_an_ask_tell_loop_on_a_bowl_stays_in_bounds_and_keeps_the_best(method, options) -> None:
    optimizer = build_optimizer(method, two_dim_space(), seed=3, **options)
    batch = optimizer.ask(4)

    assert [s.trial_id for s in batch] == [1, 2, 3, 4]
    for suggestion in batch:
        assert 0.0 <= suggestion.values["x"] <= 1.0
        assert -2.0 <= suggestion.values["y"] <= 2.0
    optimizer.tell([result_of(s, _bowl(s.values)) for s in batch])
    assert optimizer.best().cost == min(_bowl(s.values) for s in batch)
    assert optimizer.suggest_next().trial_id == 5


@pytest.mark.parametrize(("method", "options"), _METHODS, ids=_IDS)
def test_a_seed_gives_the_same_costs_twice_and_another_seed_does_not(method, options) -> None:
    first = [r.cost for r in _run(method, options, seed=5)]

    assert first == [r.cost for r in _run(method, options, seed=5)]
    assert first != [r.cost for r in _run(method, options, seed=6)]


@pytest.mark.parametrize(("method", "options"), _METHODS, ids=_IDS)
def test_a_failed_trial_is_never_the_best(method, options) -> None:
    optimizer = build_optimizer(method, two_dim_space(), seed=1, **options)
    good, bad = optimizer.ask(2)
    failed = EvaluationResult(trial_id=bad.trial_id, sim_id=None, cost=0.0, status="crashed")
    optimizer.tell([result_of(good, 2.0), failed])

    assert optimizer.best().trial_id == good.trial_id


def test_optuna_refuses_a_sampler_it_does_not_know() -> None:
    with pytest.raises(ValueError, match="Unknown Optuna sampler 'grid'"):
        build_optimizer("optuna", two_dim_space(), sampler="grid")


def test_optuna_asks_a_log_uniform_parameter_on_its_log_scale() -> None:
    space = ParameterSpace(
        [CalibParameter(name="k", lower=1e-6, upper=1e-2, sampling="log_uniform")]
    )
    optimizer = build_optimizer("optuna", space, sampler="random", seed=2)

    values = [s.values["k"] for s in optimizer.ask(30)]

    assert all(1e-6 <= v <= 1e-2 for v in values)
    assert sum(v < 1e-4 for v in values) > 5
