"""Unit tests for the Gaussian-process surrogate optimizer adapter.

The adapter lives at
:mod:`hydromodpy.calibration.adapters.gp_mapping_adapter` and implements
the :class:`~hydromodpy.calibration.optimizer.Optimizer` Protocol with
Latin-hypercube initial sampling and Expected-Improvement refinement.

Tests cover three slices:

- a 2D quadratic convergence smoke test within 30 evaluations,
- ``best()`` returning the lowest-objective completed trial,
- ``ask(n=1)`` returning exactly one :class:`ParamSuggestion`.
"""

from __future__ import annotations

import pytest
import sklearn  # noqa: F401

from hydromodpy.calibration.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.parameters import CalibParameter, ParameterSpace


def _quadratic_space() -> ParameterSpace:
    """Return a 2D box space centred on the origin."""
    return ParameterSpace(
        [
            CalibParameter(name="x", lower=-2.0, upper=2.0),
            CalibParameter(name="y", lower=-2.0, upper=2.0),
        ]
    )


def _quadratic(values: dict) -> float:
    """Simple convex quadratic with unique minimum at the origin."""
    x = float(values["x"])
    y = float(values["y"])
    return x * x + y * y


class TestGPMappingAdapter:
    def test_ask_one_returns_single_suggestion(self):
        """``ask(n=1)`` must produce exactly one ``ParamSuggestion``."""
        space = _quadratic_space()
        opt = build_optimizer("gp_mapping", space, seed=42, n_init=4, max_iter=10)
        got = opt.ask(n=1)
        assert len(got) == 1
        assert isinstance(got[0], ParamSuggestion)
        assert set(got[0].values) == {"x", "y"}

    def test_best_returns_lowest_objective(self):
        """``best()`` must surface the trial with the smallest objective."""
        space = _quadratic_space()
        opt = build_optimizer("gp_mapping", space, seed=7, n_init=4, max_iter=6)

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
                        objective_value=target,
                        status="completed",
                    )
                ]
            )

        best = opt.best()
        assert best is not None
        assert best.objective_value == pytest.approx(min(scripted))

    def test_converges_near_minimum_on_2d_quadratic(self):
        """GP-EI must approach the origin within 30 evaluations."""
        space = _quadratic_space()
        opt = build_optimizer(
            "gp_mapping",
            space,
            seed=123,
            n_init=8,
            max_iter=30,
        )

        for _ in range(30):
            got = opt.ask(n=1)
            if not got:
                break
            sugg = got[0]
            result = EvaluationResult(
                trial_id=sugg.trial_id,
                sim_id=f"sim-{sugg.trial_id}",
                objective_value=_quadratic(sugg.values),
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
        assert best.objective_value < 0.1


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
        assert opt._max_iter >= 4 + 3 * 2
        assert opt._batch_size == 2
        assert opt._n_restarts >= 12
        assert opt._kappa == pytest.approx(2.0)
        assert opt._alpha_eff == pytest.approx(1.0e-6 + 1.0e-8)

    @pytest.mark.parametrize(
        "kwarg",
        ["n_candidates", "log_transform", "n_posterior_pool", "n_posterior_samples"],
    )
    def test_removed_compatibility_kwargs_are_rejected(self, kwarg: str):
        """Removed compatibility kwargs are not accepted."""
        space = _quadratic_space()
        with pytest.raises(TypeError, match=kwarg):
            build_optimizer(
                "gp_mapping",
                space,
                **{kwarg: 1},
            )

    def test_kappa_switches_to_lcb_acquisition(self):
        """A non-zero kappa drives the LCB acquisition path end-to-end."""
        space = _quadratic_space()
        opt = build_optimizer(
            "gp_mapping",
            space,
            seed=11,
            n_init=4,
            max_iter=10,
            kappa=1.5,
        )
        for _ in range(10):
            got = opt.ask(n=1)
            if not got:
                break
            sugg = got[0]
            opt.tell(
                [
                    EvaluationResult(
                        trial_id=sugg.trial_id,
                        sim_id=None,
                        objective_value=_quadratic(sugg.values),
                        status="completed",
                    )
                ]
            )
        best = opt.best()
        assert best is not None
        assert best.status == "completed"
        assert isinstance(best.objective_value, float)
        assert best.trial_id >= 0
