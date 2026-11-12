"""Gaussian-process surrogate (`optim.adapters.gp_mapping_adapter`).
Latin-hypercube start, then Expected-Improvement steps on a dimensionless
quadratic cost.
"""

from __future__ import annotations

import numpy as np
import pytest
import sklearn  # noqa: F401

from hydromodpy.calibration.optim.adapters import gp_mapping_adapter as gp_module
from hydromodpy.calibration.optim.optimizer import EvaluationResult, build_optimizer
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from tests.unit.calibration._factories_search import result_of


def box_space() -> ParameterSpace:
    # Two parameters, bounds -2 to 2 around the origin.
    return ParameterSpace(
        [
            CalibParameter(name="x", lower=-2.0, upper=2.0),
            CalibParameter(name="y", lower=-2.0, upper=2.0),
        ]
    )


def line_space(lower: float = -2.0, upper: float = 2.0) -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="x", lower=lower, upper=upper)])


def bowl(values: dict) -> float:
    # Convex quadratic with its minimum of 0 at the origin.
    return float(values["x"]) ** 2 + float(values["y"]) ** 2


def tell_design(opt, n: int, cost=lambda s: s.values["x"] ** 2) -> None:
    opt.tell([result_of(s, cost(s)) for s in opt.ask(n=n)])


def test_best_is_lowest_cost():
    opt = build_optimizer("gp_mapping", box_space(), seed=7, n_init=4, max_trials=6)
    scripted = [2.0, 0.5, 3.0, 1.0]
    for cost in scripted:
        (sugg,) = opt.ask(n=1)
        opt.tell(
            [
                EvaluationResult(
                    trial_id=sugg.trial_id,
                    sim_id=f"sim-{sugg.trial_id}",
                    cost=cost,
                    status="completed",
                )
            ]
        )

    assert opt.best().cost == pytest.approx(min(scripted))


def test_converges_near_origin():
    opt = build_optimizer("gp_mapping", box_space(), seed=123, n_init=8, max_trials=30)

    for _ in range(30):
        got = opt.ask(n=1)
        if not got:
            break
        opt.tell([result_of(got[0], bowl(got[0].values))])
        if opt.converged():
            break

    assert opt.best().cost < 0.1


def test_failed_trial_fitted_at_worst_cost():
    opt = build_optimizer("gp_mapping", box_space(), seed=3, n_init=4, max_trials=8)
    costs = [(1.0, "completed"), (np.nan, "failed"), (2.0, "completed"), (np.inf, "completed")]
    design = opt.ask(n=4)
    opt.tell([result_of(s, c, status=st) for s, (c, st) in zip(design, costs, strict=True)])
    assert opt._y_history == [1.0, 2.0]
    assert len(opt._failed_x) == 2
    fitted = []
    fit = opt._fit_gp
    opt._fit_gp = lambda x, y: fitted.append((x, y)) or fit(x, y)

    # Four are served, so the design is done and the GP proposes the next point.
    assert len(opt.ask(n=1)) == 1
    assert np.isfinite(opt._last_ei)
    assert fitted[0][0].shape[0] == 4
    assert fitted[0][1].tolist() == [1.0, 2.0, 2.0, 2.0]


def test_batch_stops_at_pending_point(monkeypatch):
    opt = build_optimizer("gp_mapping", line_space(), seed=3, n_init=2, max_trials=12)
    tell_design(opt, 2)
    monkeypatch.setattr(opt, "_propose_next", lambda: np.array([0.5]))

    batch = opt.ask(n=3)

    assert [s.values["x"] for s in batch] == [0.5]


def test_exhausted_search(monkeypatch):
    opt = build_optimizer("gp_mapping", line_space(), seed=3, n_init=2, max_trials=2)
    tell_design(opt, 2)
    assert opt.ask(n=1) == []

    fresh = build_optimizer("gp_mapping", line_space(), seed=3, n_init=2, max_trials=9)
    tell_design(fresh, 2)
    monkeypatch.setattr(fresh, "_propose_next", lambda: None)

    assert fresh.ask(n=2) == []
    assert fresh.ask(n=1) == []
    assert fresh.converged()
    with pytest.raises(StopIteration, match="gp_mapping exhausted"):
        fresh.suggest_next()


def test_unasked_trial_ignored():
    opt = build_optimizer("gp_mapping", box_space(), seed=3, n_init=2)

    (asked,) = opt.ask(n=1)
    stray = EvaluationResult(trial_id=99, sim_id=None, cost=1.0, status="completed")
    opt.tell([stray, result_of(asked, 2.0)])

    assert opt.best().cost == 2.0


def test_budget_counts_pending_points():
    opt = build_optimizer("gp_mapping", line_space(), seed=3, n_init=2, max_trials=2)

    got = opt.ask(n=3)

    assert [(s.trial_id, s.source) for s in got] == [(1, "ask"), (2, "ask")]
    assert opt._exhausted is True
    assert len(build_optimizer("gp_mapping", line_space(), seed=3, n_init=2).ask()) == 1


def test_no_completed_trial_draws_in_bounds():
    opt = build_optimizer("gp_mapping", line_space(5.0, 10.0), seed=3, n_init=2, max_trials=6)
    opt.tell([result_of(s, np.nan, status="failed") for s in opt.ask(n=2)])
    fitted = []
    opt._fit_gp = lambda x, y: fitted.append(x.size)

    (x,) = opt._propose_next()

    assert fitted == [0]
    assert 5.0 <= x < 10.0


# Costs 1 and 2 make y_best 1, and the tolerance 0.25 separates 0.2 from 0.3.
LOW_IMPROVEMENT = [
    pytest.param(0.0, [0.5], 0.5, 0, id="above tolerance"),
    pytest.param(0.0, [0.1, 0.2], 0.2, 2, id="two low in a row"),
    pytest.param(0.0, [0.1, 0.2, 0.3], 0.3, 0, id="streak reset"),
    pytest.param(0.0, [0.25], 0.25, 0, id="at tolerance"),
    pytest.param(0.0, [-3.0], 0.0, 1, id="negative clipped"),
    pytest.param(1.5, [0.5], 1.5, 0, id="kappa adds"),
]


@pytest.mark.parametrize(("kappa", "scores", "last_ei", "streak"), LOW_IMPROVEMENT)
def test_low_improvement_streak(monkeypatch, kappa, scores, last_ei, streak):
    opt = build_optimizer("gp_mapping", box_space(), seed=3, n_init=2, kappa=kappa, ei_tol=0.25)
    opt.tell([result_of(s, c) for s, c in zip(opt.ask(n=2), (1.0, 2.0), strict=True)])
    queue = [[(np.zeros(2), score)] for score in scores]
    monkeypatch.setattr(opt, "_fit_gp", lambda x, y: object())
    monkeypatch.setattr(opt, "_maximise_acquisition", lambda gp, y_best: queue.pop(0))

    for _ in scores:
        opt._propose_next()

    assert (opt._last_ei, opt._low_ei_streak) == (pytest.approx(last_ei), streak)


@pytest.mark.parametrize(("batch_size", "queued"), [(3, 2), (2, 1)])
def test_batch_served_from_one_fit(batch_size, queued):
    opt = build_optimizer(
        "gp_mapping", box_space(), seed=3, n_init=4, batch_size=batch_size, max_trials=12
    )
    opt.tell([result_of(s, bowl(s.values)) for s in opt.ask(n=4)])

    first = opt.ask(n=1)[0]
    assert len(opt._batch_queue) == queued
    head = opt._batch_queue[0].copy()
    second = opt.ask(n=1)[0]

    assert len(opt._batch_queue) == queued - 1
    assert np.array_equal(opt._pending[second.trial_id], head)
    assert first.values != second.values


def explode(*args, **kwargs):
    raise RuntimeError("broken")


@pytest.mark.parametrize("broken", ["fit", "minimize"])
def test_search_survives_broken_surrogate(monkeypatch, broken):
    if broken == "fit":
        real = gp_module._get_sklearn()
        broken_sklearn = dict(real)
        broken_sklearn["GaussianProcessRegressor"] = type(
            "BrokenGP", (real["GaussianProcessRegressor"],), {"fit": explode}
        )
        monkeypatch.setattr(gp_module, "_get_sklearn", lambda: broken_sklearn)
    else:
        monkeypatch.setattr(gp_module, "_scipy_minimize", explode)
    opt = build_optimizer("gp_mapping", box_space(), seed=3, n_init=3, max_trials=8)
    opt.tell([result_of(s, bowl(s.values)) for s in opt.ask(n=3)])

    (proposal,) = opt.ask(n=1)

    assert set(proposal.values) == {"x", "y"}


def test_missing_scikit_learn(monkeypatch):
    monkeypatch.setattr(gp_module, "_SKLEARN_AVAILABLE", False)

    with pytest.raises(ImportError, match="scikit-learn is required"):
        build_optimizer("gp_mapping", box_space())


def test_canonical_options():
    opt = build_optimizer(
        "gp_mapping",
        box_space(),
        seed=7,
        n_init=4,
        n_refine=3,
        batch_size=2,
        n_restarts=12,
        kappa=2.0,
        alpha=1.0e-6,
        jitter=1.0e-8,
    )
    assert opt.name == "gp_mapping"
    assert opt._max_trials >= 4 + 3 * 2
    assert opt._batch_size == 2
    assert opt._n_restarts >= 12
    assert opt._kappa == pytest.approx(2.0)
    assert opt._alpha_eff == pytest.approx(1.0e-6 + 1.0e-8)
