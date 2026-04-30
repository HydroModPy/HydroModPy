"""Unit tests for :class:`hydromodpy.calibration.adapters.da_mh_gp_adapter.DaMhGpOptimizer`.

The DA-MH-GP sampler exposes the ask/tell Protocol. These tests exercise the
high-level behaviour - smoke run, posterior-mode recovery, chain length - on
a cheap 2D quadratic RMSE surface. Heavier scientific checks live in
``tests/regression/fast/calibration/test_brutsaert_methods.py``.
"""

from __future__ import annotations

import numpy as np
import pytest

sklearn = pytest.importorskip("sklearn")  # noqa: F841 - skip gracefully if missing

from hydromodpy.calibration.engine import CalibrationEngine
from hydromodpy.calibration.optimizer import (
    EvaluationResult,
    build_optimizer,
)
from hydromodpy.calibration.parameters import CalibParameter, ParameterSpace

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _quadratic_space() -> ParameterSpace:
    """A 2D parameter space with symmetric bounds centred on the origin."""
    return ParameterSpace(
        [
            CalibParameter(name="x", lower=-4.0, upper=4.0),
            CalibParameter(name="y", lower=-4.0, upper=4.0),
        ]
    )


def _make_quadratic_evaluator(target: tuple[float, float] = (1.0, -2.0)):
    """Return an evaluator closure whose optimum sits at ``target``."""
    tx, ty = target

    def _eval(sugg):
        x = float(sugg.values["x"])
        y = float(sugg.values["y"])
        rmse = float(np.sqrt((x - tx) ** 2 + (y - ty) ** 2))
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=None,
            objective_value=rmse,
            status="completed",
            metadata={"values": dict(sugg.values)},
        )

    return _eval


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDaMhGpSmoke:
    def test_registered_and_builds(self):
        """``build_optimizer`` must return a valid DA-MH-GP instance."""
        space = _quadratic_space()
        opt = build_optimizer(
            "da_mh_gp",
            space,
            max_iter=20,
            n_init=4,
            burn_in=5,
            proposal_sigma=0.5,
            seed=42,
            sigma_noise=0.5,
        )
        assert opt.name == "da_mh_gp"

    def test_runs_and_accepts_samples(self):
        """DA-MH-GP should complete a small run on a convex RMSE surface."""
        space = _quadratic_space()
        opt = build_optimizer(
            "da_mh_gp",
            space,
            max_iter=30,
            n_init=6,
            burn_in=10,
            proposal_sigma=0.5,
            seed=42,
            sigma_noise=0.3,
        )
        engine = CalibrationEngine(
            space=space,
            optimizer=opt,
            evaluator=_make_quadratic_evaluator(),
            max_iter=100,
        )
        session = engine.run()
        completed = [r for r in session.history if r.status == "completed"]
        # At least the initial design must be evaluated.
        assert len(completed) >= 6
        assert opt.converged(), "optimizer must flag convergence after its thread exits"


class TestDaMhGpBest:
    def test_posterior_mode_recovers_optimum(self):
        """``best()`` should surface a posterior mode close to the RMSE minimum."""
        space = _quadratic_space()
        opt = build_optimizer(
            "da_mh_gp",
            space,
            max_iter=40,
            n_init=6,
            burn_in=10,
            proposal_sigma=0.4,
            seed=42,
            sigma_noise=0.3,
        )
        engine = CalibrationEngine(
            space=space,
            optimizer=opt,
            evaluator=_make_quadratic_evaluator(target=(1.0, -2.0)),
            max_iter=100,
        )
        engine.run()
        best = opt.best()
        assert best is not None
        # best is an EvaluationResult enriched with the posterior mode.
        assert best.metadata is not None and "posterior_mode" in best.metadata
        mode = best.metadata["posterior_mode"]
        assert np.isclose(mode["x"], 1.0, atol=0.6)
        assert np.isclose(mode["y"], -2.0, atol=0.6)

    def test_best_returns_none_when_nothing_evaluated(self):
        """``best()`` must return ``None`` before any ``tell()``."""
        space = _quadratic_space()
        opt = build_optimizer(
            "da_mh_gp",
            space,
            max_iter=5,
            n_init=3,
            burn_in=0,
            proposal_sigma=0.2,
            seed=0,
            sigma_noise=1.0,
        )
        assert opt.best() is None


class TestDaMhGpChain:
    def test_chain_length_matches_max_iter(self):
        """Full chain length should equal the requested ``max_iter`` MCMC budget."""
        space = _quadratic_space()
        max_iter = 25
        opt = build_optimizer(
            "da_mh_gp",
            space,
            max_iter=max_iter,
            n_init=4,
            burn_in=5,
            proposal_sigma=0.5,
            seed=7,
            sigma_noise=0.3,
        )
        engine = CalibrationEngine(
            space=space,
            optimizer=opt,
            evaluator=_make_quadratic_evaluator(),
            max_iter=200,
        )
        engine.run()
        assert opt.chain.shape == (max_iter, 2)

    def test_posterior_samples_excludes_burn_in(self):
        """``posterior_samples`` drops the burn-in prefix and is in physical units."""
        space = _quadratic_space()
        max_iter = 30
        burn_in = 7
        opt = build_optimizer(
            "da_mh_gp",
            space,
            max_iter=max_iter,
            n_init=4,
            burn_in=burn_in,
            proposal_sigma=0.3,
            seed=0,
            sigma_noise=0.3,
        )
        engine = CalibrationEngine(
            space=space,
            optimizer=opt,
            evaluator=_make_quadratic_evaluator(),
            max_iter=200,
        )
        engine.run()
        samples = opt.posterior_samples
        assert samples.shape == (max_iter - burn_in, 2)
        assert np.all((samples[:, 0] >= -4.0) & (samples[:, 0] <= 4.0))
        assert np.all((samples[:, 1] >= -4.0) & (samples[:, 1] <= 4.0))


class TestDaMhGpValidation:
    def test_rejects_non_positive_sigma_noise(self):
        space = _quadratic_space()
        with pytest.raises(ValueError, match="sigma_noise must be > 0"):
            build_optimizer("da_mh_gp", space, sigma_noise=0.0)

    def test_rejects_out_of_range_full_mh_prob(self):
        space = _quadratic_space()
        with pytest.raises(ValueError, match="full_mh_prob"):
            build_optimizer("da_mh_gp", space, full_mh_prob=1.5)

    def test_rejects_non_positive_proposal_sigma(self):
        space = _quadratic_space()
        with pytest.raises(ValueError, match="proposal_sigma"):
            build_optimizer("da_mh_gp", space, proposal_sigma=0.0)


class TestDaMhGpAdvancedKwargs:
    def test_accepts_full_canonical_kwargs(self):
        """Adapter must construct with thin, gp_alpha and cache_decimals."""
        space = _quadratic_space()
        opt = build_optimizer(
            "da_mh_gp",
            space,
            sigma_noise=0.1,
            n_init=4,
            max_iter=64,
            burn_in=10,
            thin=2,
            proposal_sigma=0.4,
            retrain_interval=5,
            gp_alpha=1.0e-6,
            full_mh_prob=0.05,
            seed=13,
            cache_decimals=10,
        )
        assert opt.name == "da_mh_gp"
        assert opt._max_iter == 64
        assert opt._proposal_std[0] == pytest.approx(0.4)
        assert opt._gp_alpha == pytest.approx(1.0e-6)
        assert opt._thin == 2
        assert opt._cache_decimals == 10

    @pytest.mark.parametrize("kwarg", ["proposal_scale", "n_samples", "gp_noise"])
    def test_removed_compatibility_kwargs_are_rejected(self, kwarg: str):
        """Removed compatibility kwargs are not accepted."""
        space = _quadratic_space()
        with pytest.raises(TypeError, match=kwarg):
            build_optimizer("da_mh_gp", space, sigma_noise=0.5, **{kwarg: 1})

    def test_thin_reduces_posterior_sample_count(self):
        """thin>1 must reduce posterior_samples length proportionally."""
        space = _quadratic_space()
        max_iter = 30
        burn_in = 6
        thin = 3
        opt = build_optimizer(
            "da_mh_gp",
            space,
            max_iter=max_iter,
            n_init=4,
            burn_in=burn_in,
            proposal_sigma=0.3,
            seed=0,
            sigma_noise=0.3,
            thin=thin,
        )
        engine = CalibrationEngine(
            space=space,
            optimizer=opt,
            evaluator=_make_quadratic_evaluator(),
            max_iter=200,
        )
        engine.run()
        samples = opt.posterior_samples
        expected_len = int(np.ceil((max_iter - burn_in) / thin))
        assert samples.shape == (expected_len, 2)

    def test_cache_decimals_dedupes_repeated_proposals(self):
        """A re-evaluation at the same rounded location must hit the cache."""
        space = _quadratic_space()
        opt = build_optimizer(
            "da_mh_gp",
            space,
            max_iter=4,
            n_init=2,
            proposal_sigma=0.1,
            sigma_noise=0.5,
            seed=0,
            cache_decimals=3,
        )
        x = np.array([0.123456, -0.654321], dtype=float)
        # Pre-fill the cache directly to avoid spinning up the engine.
        key = opt._cache_key(x)
        opt._eval_cache[key] = -1.234
        # A second probe at the *same rounded* location returns the cached value
        # without going through the bridge (which would block the test thread).
        cached = opt._eval_cache[opt._cache_key(x + 1e-6)]
        assert cached == pytest.approx(-1.234)
