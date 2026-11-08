"""Tests of `optim.adapters.gp_mapping_adapter`."""

from __future__ import annotations

import itertools

import numpy as np
import pytest
import sklearn  # noqa: F401

from hydromodpy.calibration.optim.adapters import gp_mapping_adapter as gp_module
from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from tests.unit.calibration._factories_search import result_of

# From test_gp_mapping_adapter.py
# Unit tests for the Gaussian-process surrogate optimizer adapter.
#
# The adapter lives at
# :mod:`hydromodpy.calibration.optim.adapters.gp_mapping_adapter` and implements
# the :class:`~hydromodpy.calibration.optim.optimizer.Optimizer` Protocol with
# Latin-hypercube initial sampling and Expected-Improvement refinement.
#
# Tests cover three slices:
#
# - a 2D quadratic convergence smoke test within 30 evaluations,
# - ``best()`` returning the lowest-objective completed trial,
# - ``ask(n=1)`` returning exactly one :class:`ParamSuggestion`.


def _quadratic_space() -> ParameterSpace:
    """Return a 2D box space centered on the origin."""
    return ParameterSpace(
        [
            CalibParameter(name="x", lower=-2.0, upper=2.0),
            CalibParameter(name="y", lower=-2.0, upper=2.0),
        ]
    )


def _space_of(lower: float, upper: float) -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="x", lower=lower, upper=upper)])


def _quadratic(values: dict) -> float:
    """Simple convex quadratic with unique minimum at the origin."""
    x = float(values["x"])
    y = float(values["y"])
    return x * x + y * y


class TestGPMappingAdapter:
    def test_ask_one_returns_single_suggestion(self):
        """``ask(n=1)`` must produce exactly one ``ParamSuggestion``."""
        space = _quadratic_space()
        opt = build_optimizer("gp_mapping", space, seed=42, n_init=4, max_trials=10)
        got = opt.ask(n=1)
        assert len(got) == 1
        assert isinstance(got[0], ParamSuggestion)
        assert set(got[0].values) == {"x", "y"}

    def test_best_returns_lowest_objective(self):
        """``best()`` must surface the trial with the smallest objective."""
        space = _quadratic_space()
        opt = build_optimizer("gp_mapping", space, seed=7, n_init=4, max_trials=6)

        # Feed a known sequence: ascending objective values.
        scripted = [2.0, 0.5, 3.0, 1.0]
        for target in scripted:
            sugg = opt.ask(n=1)
            assert len(sugg) == 1
            opt.tell(
                [
                    EvaluationResult(
                        trial_id=sugg[0].trial_id,
                        sim_id=f"sim-{sugg[0].trial_id}",
                        cost=target,
                        status="completed",
                    )
                ]
            )

        best = opt.best()
        assert best is not None
        assert best.cost == pytest.approx(min(scripted))

    def test_converges_near_minimum_on_2d_quadratic(self):
        """GP-EI must approach the origin within 30 evaluations."""
        space = _quadratic_space()
        opt = build_optimizer("gp_mapping", space, seed=123, n_init=8, max_trials=30)

        for _ in range(30):
            got = opt.ask(n=1)
            if not got:
                break
            sugg = got[0]
            result = EvaluationResult(
                trial_id=sugg.trial_id,
                sim_id=f"sim-{sugg.trial_id}",
                cost=_quadratic(sugg.values),
                status="completed",
            )
            opt.tell([result])
            if opt.converged():
                break

        best = opt.best()
        assert best is not None
        # Recover the best-ever parameter vector via ``ask`` history.
        # Since the evaluator deterministically mirrors x, y, the minimum
        # cost is bounded by the distance-to-origin squared.
        assert best.cost < 0.1


class TestGPMappingFailuresAndBatches:
    def test_a_failed_trial_is_fitted_at_the_worst_cost_and_counts_as_served(self):
        opt = build_optimizer("gp_mapping", _quadratic_space(), seed=3, n_init=4, max_trials=8)
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

    def test_a_batch_names_no_point_twice(self):
        space = ParameterSpace([CalibParameter(name="x", lower=-2.0, upper=2.0)])
        opt = build_optimizer("gp_mapping", space, seed=3, n_init=4, max_trials=12)
        design = opt.ask(n=4)
        opt.tell([result_of(s, s.values["x"] ** 2) for s in design])

        xs = [s.values["x"] for s in opt.ask(n=3)]

        assert xs
        assert all(abs(a - b) > 4.0e-3 for a, b in itertools.combinations(xs, 2))

    def test_a_batch_stops_at_a_point_already_pending(self, monkeypatch):
        space = ParameterSpace([CalibParameter(name="x", lower=-2.0, upper=2.0)])
        opt = build_optimizer("gp_mapping", space, seed=3, n_init=2, max_trials=12)
        opt.tell([result_of(s, s.values["x"] ** 2) for s in opt.ask(n=2)])
        monkeypatch.setattr(opt, "_propose_next", lambda: np.array([0.5]))

        batch = opt.ask(n=3)

        assert [s.values["x"] for s in batch] == [0.5]

    def test_a_search_with_no_proposal_or_no_budget_left_stays_exhausted(self, monkeypatch):
        space = ParameterSpace([CalibParameter(name="x", lower=-2.0, upper=2.0)])
        opt = build_optimizer("gp_mapping", space, seed=3, n_init=2, max_trials=2)
        opt.tell([result_of(s, s.values["x"] ** 2) for s in opt.ask(n=2)])
        assert opt.ask(n=1) == []

        fresh = build_optimizer("gp_mapping", space, seed=3, n_init=2, max_trials=9)
        fresh.tell([result_of(s, s.values["x"] ** 2) for s in fresh.ask(n=2)])
        monkeypatch.setattr(fresh, "_propose_next", lambda: None)

        assert fresh.ask(n=2) == []
        assert fresh.ask(n=1) == []
        assert fresh.converged()
        with pytest.raises(StopIteration, match="gp_mapping exhausted"):
            fresh.suggest_next()

    def test_a_result_for_a_trial_nobody_asked_is_ignored(self):
        opt = build_optimizer("gp_mapping", _quadratic_space(), seed=3, n_init=2)

        (asked,) = opt.ask(n=1)
        stray = EvaluationResult(trial_id=99, sim_id=None, cost=1.0, status="completed")
        opt.tell([stray, result_of(asked, 2.0)])

        assert opt.best().cost == 2.0

    def test_the_budget_counts_the_pending_points_and_serves_the_ids_in_order(self):
        space = ParameterSpace([CalibParameter(name="x", lower=-2.0, upper=2.0)])
        opt = build_optimizer("gp_mapping", space, seed=3, n_init=2, max_trials=2)

        got = opt.ask(n=3)

        assert [(s.trial_id, s.source) for s in got] == [(1, "ask"), (2, "ask")]
        assert opt._exhausted is True
        assert len(build_optimizer("gp_mapping", space, seed=3, n_init=2).ask()) == 1

    def test_two_points_a_thousandth_of_the_span_apart_are_one_point(self):
        opt = build_optimizer("gp_mapping", _quadratic_space(), seed=3)
        origin = np.zeros(2)

        assert not opt._distinct(np.array([0.004, 0.0]), [origin])
        assert opt._distinct(np.array([0.0, 0.008]), [origin])
        # Below one unit the span is the bounds' own, here a hundredth.
        narrow = build_optimizer("gp_mapping", _space_of(0.0, 0.01), seed=3)
        assert narrow._distinct(np.array([0.0005]), [np.zeros(1)])

    def test_a_search_with_no_completed_trial_fits_nothing_and_draws_inside_the_bounds(self):
        space = ParameterSpace([CalibParameter(name="x", lower=5.0, upper=10.0)])
        opt = build_optimizer("gp_mapping", space, seed=3, n_init=2, max_trials=6)
        opt.tell([result_of(s, np.nan, status="failed") for s in opt.ask(n=2)])
        fitted = []
        opt._fit_gp = lambda x, y: fitted.append(x.size)

        (x,) = opt._propose_next()

        assert fitted == [0]
        assert 5.0 <= x < 10.0

    @pytest.mark.parametrize(
        ("kappa", "scores", "last_ei", "streak"),
        [
            (0.0, [0.5], 0.5, 0),
            (0.0, [0.1, 0.2], 0.2, 2),
            (0.0, [0.1, 0.2, 0.3], 0.3, 0),
            (0.0, [0.25], 0.25, 0),
            (0.0, [-3.0], 0.0, 1),
            (1.5, [0.5], 1.5, 0),
        ],
    )
    def test_the_improvement_a_proposal_promises_counts_a_low_streak(
        self, monkeypatch, kappa, scores, last_ei, streak
    ):
        # Costs 1 and 2 make y_best 1, and the tolerance 0.25 separates 0.2 from 0.3.
        opt = build_optimizer(
            "gp_mapping", _quadratic_space(), seed=3, n_init=2, kappa=kappa, ei_tol=0.25
        )
        opt.tell([result_of(s, c) for s, c in zip(opt.ask(n=2), (1.0, 2.0), strict=True)])
        queue = [[(np.zeros(2), score)] for score in scores]
        monkeypatch.setattr(opt, "_fit_gp", lambda x, y: object())
        monkeypatch.setattr(opt, "_maximise_acquisition", lambda gp, y_best: queue.pop(0))

        for _ in scores:
            opt._propose_next()

        assert (opt._last_ei, opt._low_ei_streak) == (pytest.approx(last_ei), streak)

    @pytest.mark.parametrize(("batch_size", "queued"), [(3, 2), (2, 1)])
    def test_a_batch_is_served_from_one_fit(self, batch_size, queued):
        opt = build_optimizer(
            "gp_mapping", _quadratic_space(), seed=3, n_init=4, batch_size=batch_size, max_trials=12
        )
        opt.tell([result_of(s, _quadratic(s.values)) for s in opt.ask(n=4)])

        first = opt.ask(n=1)[0]
        assert len(opt._batch_queue) == queued
        head = opt._batch_queue[0].copy()
        second = opt.ask(n=1)[0]

        assert len(opt._batch_queue) == queued - 1
        assert np.array_equal(opt._pending[second.trial_id], head)
        assert first.values != second.values

    @pytest.mark.parametrize("broken", ["fit", "minimize"])
    def test_a_search_goes_on_when_the_surrogate_or_its_maximiser_breaks(self, monkeypatch, broken):
        def explode(*args, **kwargs):
            raise RuntimeError("broken")

        real = gp_module._get_sklearn()
        if broken == "fit":
            # The surrogate's fit explodes mid-search; the adapter falls back.
            broken_fit = dict(real)
            broken_fit["GaussianProcessRegressor"] = type(
                "BrokenGP", (real["GaussianProcessRegressor"],), {"fit": explode}
            )
            monkeypatch.setattr(gp_module, "_get_sklearn", lambda: broken_fit)
        else:
            monkeypatch.setattr(gp_module, "_scipy_minimize", explode)
        opt = build_optimizer("gp_mapping", _quadratic_space(), seed=3, n_init=3, max_trials=8)
        opt.tell([result_of(s, _quadratic(s.values)) for s in opt.ask(n=3)])

        (proposal,) = opt.ask(n=1)

        assert set(proposal.values) == {"x", "y"}

    def test_it_says_when_scikit_learn_is_missing(self, monkeypatch):
        monkeypatch.setattr(gp_module, "_SKLEARN_AVAILABLE", False)

        with pytest.raises(ImportError, match="scikit-learn is required"):
            build_optimizer("gp_mapping", _quadratic_space())


class TestGPMappingAdvancedKwargs:
    def test_accepts_full_canonical_kwargs(self):
        """Adapter must construct cleanly with the full canonical option set."""
        space = _quadratic_space()
        opt = build_optimizer(
            "gp_mapping",
            space,
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

    @pytest.mark.parametrize(
        "kwarg", ["n_candidates", "log_transform", "n_posterior_pool", "n_posterior_samples"]
    )
    def test_removed_compatibility_kwargs_are_rejected(self, kwarg: str):
        """Removed compatibility kwargs are not accepted."""
        space = _quadratic_space()
        with pytest.raises(TypeError, match=kwarg):
            build_optimizer("gp_mapping", space, **{kwarg: 1})

    def test_kappa_switches_to_lcb_acquisition(self):
        """A non-zero kappa drives the LCB acquisition path end-to-end."""
        space = _quadratic_space()
        opt = build_optimizer("gp_mapping", space, seed=11, n_init=4, max_trials=10, kappa=1.5)
        for _ in range(10):
            got = opt.ask(n=1)
            if not got:
                break
            sugg = got[0]
            opt.tell([result_of(sugg, _quadratic(sugg.values))])
        best = opt.best()
        assert best is not None
        assert best.status == "completed"
        assert isinstance(best.cost, float)
        assert best.trial_id >= 0
