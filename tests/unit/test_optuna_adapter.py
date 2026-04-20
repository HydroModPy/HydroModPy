"""Unit tests for the Optuna optimizer adapter.

Gated with ``pytest.importorskip`` so the test module is skipped if optuna
is not available in the active environment (it is a core dependency, but
this keeps the test robust to lightweight installs).
"""

from __future__ import annotations

import pytest

optuna = pytest.importorskip("optuna")

from hydromodpy.calibration.optimizer import EvaluationResult, build_optimizer
from hydromodpy.calibration.parameters import CalibParameter, ParameterSpace


def _space_2d():
    return ParameterSpace(
        [
            CalibParameter(name="K", lower=1e-6, upper=1e-3, transform="log"),
            CalibParameter(name="Sy", lower=0.02, upper=0.30),
        ]
    )


class TestOptunaAdapter:
    def test_build_via_registry(self):
        opt = build_optimizer("optuna", _space_2d(), sampler="tpe", seed=42)
        assert opt.name == "optuna"

    def test_ask_returns_values_within_bounds(self):
        opt = build_optimizer("optuna", _space_2d(), sampler="tpe", seed=0)
        suggs = opt.ask(1)
        assert len(suggs) == 1
        s = suggs[0]
        assert set(s.values) == {"K", "Sy"}
        assert 1e-6 <= s.values["K"] <= 1e-3
        assert 0.02 <= s.values["Sy"] <= 0.30

    def test_tell_drains_pending(self):
        opt = build_optimizer("optuna", _space_2d(), sampler="random", seed=0)
        suggs = opt.ask(3)
        results = [
            EvaluationResult(
                trial_id=s.trial_id,
                sim_id=None,
                objective_value=float(i),
                status="completed",
            )
            for i, s in enumerate(suggs)
        ]
        opt.tell(results)
        # Asking again must work (pending dict should be empty).
        new_suggs = opt.ask(1)
        assert len(new_suggs) == 1

    def test_best_returns_lowest_cost(self):
        opt = build_optimizer("optuna", _space_2d(), sampler="random", seed=0)
        suggs = opt.ask(5)
        results = [
            EvaluationResult(
                trial_id=s.trial_id,
                sim_id=None,
                objective_value=float(5 - i),  # descending
                status="completed",
            )
            for i, s in enumerate(suggs)
        ]
        opt.tell(results)
        best = opt.best()
        assert best is not None
        assert best.objective_value == 1.0

    def test_converges_toward_minimum(self):
        """TPE finds a lower cost than random guessing after a handful of trials."""
        space = _space_2d()
        opt = build_optimizer("optuna", space, sampler="tpe", seed=42)

        def obj(values):
            # Quadratic bowl in log10(K) and Sy centered at (-4.0, 0.15)
            import math

            k_log = math.log10(values["K"])
            return (k_log + 4.0) ** 2 + (values["Sy"] - 0.15) ** 2

        n = 30
        for _ in range(n):
            s = opt.ask(1)[0]
            cost = obj(s.values)
            opt.tell(
                [
                    EvaluationResult(
                        trial_id=s.trial_id,
                        sim_id=None,
                        objective_value=cost,
                        status="completed",
                    )
                ]
            )

        assert opt.best() is not None
        assert opt.best().objective_value < 0.01

    def test_fail_status_reported_to_optuna(self):
        opt = build_optimizer("optuna", _space_2d(), sampler="random", seed=0)
        s = opt.ask(1)[0]
        r = EvaluationResult(
            trial_id=s.trial_id,
            sim_id=None,
            objective_value=float("inf"),
            status="crashed",
        )
        opt.tell([r])  # should not raise

    def test_rejects_unknown_sampler(self):
        with pytest.raises(ValueError, match="sampler"):
            build_optimizer("optuna", _space_2d(), sampler="not-a-sampler")
