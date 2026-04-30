"""Tests for adapter aliasing + cma_es adapter construction.

Covers Phase 4 of the calibration integration:

- ``grid`` resolves to the GridAdapter class.
- ``simplex`` / ``nelder_mead`` / ``scipy_nelder_mead`` all resolve to the
  scipy Nelder-Mead adapter.
- ``random_search`` matches the legacy numpy default_rng sampling path.
- ``cma_es`` instantiates cleanly and respects ``seed`` reproducibility.
- Adapters return suggestions whose parameter values fall within
  transformed bounds.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.optimizer import build_optimizer
from hydromodpy.calibration.parameters import CalibParameter, ParameterSpace


def _two_dim_space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(name="x", lower=0.0, upper=1.0),
            CalibParameter(name="y", lower=-2.0, upper=2.0),
        ]
    )


# ---------------------------------------------------------------------------
# Alias resolution
# ---------------------------------------------------------------------------


class TestAdapterAliases:
    def test_grid_resolves(self):
        opt = build_optimizer("grid", _two_dim_space())
        assert opt.name == "grid"

    @pytest.mark.parametrize("alias", ["simplex", "nelder_mead", "scipy_nelder_mead"])
    def test_nelder_mead_aliases(self, alias: str):
        opt = build_optimizer(alias, _two_dim_space())
        assert opt.name == "scipy_nelder_mead"

    def test_random_search_resolves(self):
        opt = build_optimizer("random_search", _two_dim_space(), seed=0)
        assert opt.name == "random_search"

    def test_cma_es_resolves(self):
        opt = build_optimizer(
            "cma_es",
            _two_dim_space(),
            sigma0=0.25,
            popsize=4,
            max_evaluations=8,
            seed=42,
        )
        assert opt.name == "cma_es"


# ---------------------------------------------------------------------------
# Grid adapter with legacy n_per_dim kwarg
# ---------------------------------------------------------------------------


class TestGridLegacyKwargs:
    def test_n_per_dim_alias(self):
        opt = build_optimizer("grid", _two_dim_space(), n_per_dim=3)
        suggestions = opt.ask(n=9)  # 3 x 3 grid
        values_x = [s.values["x"] for s in suggestions]
        values_y = [s.values["y"] for s in suggestions]
        assert len(suggestions) == 9
        assert min(values_x) == pytest.approx(0.0)
        assert max(values_x) == pytest.approx(1.0)
        assert min(values_y) == pytest.approx(-2.0)
        assert max(values_y) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Optuna random seeded reproducibility
# ---------------------------------------------------------------------------


class TestRandomSearchSeeding:
    def test_same_seed_yields_same_suggestions(self):
        opt_a = build_optimizer("random_search", _two_dim_space(), seed=7)
        opt_b = build_optimizer("random_search", _two_dim_space(), seed=7)
        sugg_a = opt_a.ask(n=4)
        sugg_b = opt_b.ask(n=4)
        for a, b in zip(sugg_a, sugg_b, strict=True):
            assert a.values["x"] == pytest.approx(b.values["x"])
            assert a.values["y"] == pytest.approx(b.values["y"])

    def test_sampled_points_within_bounds(self):
        opt = build_optimizer("random_search", _two_dim_space(), seed=11)
        sugg = opt.ask(n=5)
        for s in sugg:
            assert 0.0 <= s.values["x"] <= 1.0
            assert -2.0 <= s.values["y"] <= 2.0


# ---------------------------------------------------------------------------
# CMA-ES adapter seeded ask/tell roundtrip
# ---------------------------------------------------------------------------


class TestCmaEsAdapter:
    def test_ask_tell_converges_on_convex(self):
        """Optimise a convex quadratic: best value must be close to origin."""
        space = _two_dim_space()
        opt = build_optimizer(
            "cma_es",
            space,
            sigma0=0.3,
            popsize=6,
            max_evaluations=60,
            seed=42,
        )
        trial_to_vec: dict[int, dict[str, float]] = {}
        while not opt.converged():
            try:
                sugg = opt.ask(n=6)
            except Exception:
                break
            if not sugg:
                break
            results = []
            from hydromodpy.calibration.optimizer import EvaluationResult

            for s in sugg:
                trial_to_vec[s.trial_id] = dict(s.values)
                cost = float((s.values["x"] - 0.3) ** 2 + (s.values["y"] - 0.5) ** 2)
                results.append(
                    EvaluationResult(
                        trial_id=s.trial_id,
                        sim_id=None,
                        objective_value=cost,
                        status="completed",
                    )
                )
            opt.tell(results)

        best = opt.best()
        assert best is not None
        best_vec = trial_to_vec[best.trial_id]
        assert abs(best_vec["x"] - 0.3) < 0.1
        assert abs(best_vec["y"] - 0.5) < 0.1

    def test_ask_returns_values_within_bounds(self):
        space = _two_dim_space()
        opt = build_optimizer(
            "cma_es",
            space,
            sigma0=0.25,
            popsize=4,
            max_evaluations=8,
            seed=1,
        )
        sugg = opt.ask(n=4)
        assert len(sugg) == 4
        for s in sugg:
            assert 0.0 <= s.values["x"] <= 1.0
            assert -2.0 <= s.values["y"] <= 2.0


# ---------------------------------------------------------------------------
# Scipy Nelder-Mead accepts legacy kwargs (max_iter / max_fun / xtol / ftol)
# ---------------------------------------------------------------------------


class TestScipyLegacyKwargs:
    def test_legacy_kwargs_accepted(self):
        opt = build_optimizer(
            "simplex",
            _two_dim_space(),
            max_iter=5,
            max_fun=10,
            xtol=1e-3,
            ftol=1e-3,
        )
        # Just confirm construction does not raise and first ask works.
        sugg = opt.ask(n=1)
        assert sugg


# ---------------------------------------------------------------------------
# CMA-ES legacy ``restarts`` kwarg
# ---------------------------------------------------------------------------


class TestCmaRestarts:
    def test_cma_adapter_accepts_restarts_kwarg(self):
        opt = build_optimizer(
            "cma_es",
            _two_dim_space(),
            sigma0=0.25,
            popsize=4,
            max_evaluations=8,
            seed=1,
            restarts=2,
        )
        assert opt.name == "cma_es"
        sugg = opt.ask(n=1)
        assert sugg

    def test_cma_adapter_restarts_actually_restarts(self):
        """A restart must re-instantiate the strategy when CMA stops early."""
        space = _two_dim_space()
        opt = build_optimizer(
            "cma_es",
            space,
            sigma0=0.25,
            popsize=4,
            max_evaluations=12,
            seed=2,
            restarts=1,
        )
        first_es_id = id(opt._es)
        # Force an early stop on the active strategy without exhausting the
        # evaluation budget. The next ask() must trigger a restart and swap
        # the underlying strategy instance.
        original_stop = opt._es.stop
        forced_stops = {"count": 0}

        def _fake_stop():
            if forced_stops["count"] < 1:
                forced_stops["count"] += 1
                return {"forced": True}
            return original_stop()

        opt._es.stop = _fake_stop
        opt.ask(n=1)
        assert opt._restarts_used == 1
        assert id(opt._es) != first_es_id
