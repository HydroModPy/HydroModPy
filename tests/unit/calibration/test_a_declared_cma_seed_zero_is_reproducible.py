"""A seed written as 0 reproduces the same CMA-ES path.

``cma`` reads a seed of 0 as "seed from the clock". The adapter maps that one
value to a fixed seed and leaves every other seed on its own path.
"""

from __future__ import annotations

import pytest

pytest.importorskip("cma")

from hydromodpy.calibration.optim.optimizer import build_optimizer  # noqa: E402
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace  # noqa: E402


def _space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(name="x", lower=0.0, upper=1.0),
            CalibParameter(name="y", lower=-2.0, upper=2.0),
        ]
    )


def _first_batch(seed: int | None) -> list[dict[str, float]]:
    opt = build_optimizer("cma_es", _space(), popsize=5, max_trials=30, seed=seed)
    return [s.values for s in opt.ask(n=5)]


def test_seed_zero_gives_the_same_first_batch_twice() -> None:
    assert _first_batch(0) == _first_batch(0)


def test_seed_zero_is_not_the_path_of_another_seed() -> None:
    assert _first_batch(0) != _first_batch(1)


def _seed_handed_to_cma(monkeypatch, seed: int, restarts_used: int = 0) -> int:
    import cma

    seen: list[int] = []
    real = cma.CMAEvolutionStrategy

    def spy(x0, sigma0, options=None):
        seen.append(options["seed"])
        return real(x0, sigma0, options)

    monkeypatch.setattr(cma, "CMAEvolutionStrategy", spy)
    opt = build_optimizer("cma_es", _space(), popsize=5, max_trials=30, seed=seed)
    opt._restarts_used = restarts_used
    opt._make_strategy(opt._x0_t)
    return seen[-1]


def test_another_seed_keeps_its_path(monkeypatch) -> None:
    assert _seed_handed_to_cma(monkeypatch, 7) == 7
    assert _seed_handed_to_cma(monkeypatch, 1) == 1
    assert _seed_handed_to_cma(monkeypatch, 6, restarts_used=1) == 7


def test_seed_zero_reaches_cma_as_a_nonzero_seed(monkeypatch) -> None:
    assert _seed_handed_to_cma(monkeypatch, 0) > 1
    assert _seed_handed_to_cma(monkeypatch, 0, restarts_used=1) == 1
