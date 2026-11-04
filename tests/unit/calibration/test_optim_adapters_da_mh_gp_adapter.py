"""Tests of `optim.adapters.da_mh_gp_adapter`."""

from __future__ import annotations

import numpy as np
import pytest
import sklearn  # noqa: F401

from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, build_optimizer
from tests.unit.calibration._factories_search import make_space, result_of

# From test_da_mh_gp_adapter.py
# Unit tests for :class:`hydromodpy.calibration.optim.adapters.da_mh_gp_adapter.DaMhGpOptimizer`.
#
# The DA-MH-GP sampler exposes the ask/tell Protocol. These tests exercise the
# high-level behavior - smoke run, posterior-mode recovery, chain length - on
# a cheap 2D quadratic RMSE surface. Heavier scientific checks live in
# ``tests/regression/fast/calibration/test_brutsaert_methods.py``.


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _quadratic_space():
    """A 2D parameter space with symmetric bounds centered on the origin."""
    return make_space(("x", -4.0, 4.0), ("y", -4.0, 4.0))


def _make_quadratic_evaluator(target: tuple[float, float] = (1.0, -2.0)):
    """Return an evaluator closure whose optimum sits at ``target``."""
    tx, ty = target

    def _eval(sugg):
        x = float(sugg.values["x"])
        y = float(sugg.values["y"])
        rmse = float(np.sqrt((x - tx) ** 2 + (y - ty) ** 2))
        return result_of(sugg, rmse, metadata={"values": dict(sugg.values)})

    return _eval


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def _fit(evaluator=None, max_trials=200, **options):
    """Build a DA-MH-GP sampler on the quadratic space and run it. Return it and its session."""
    space = _quadratic_space()
    opt = build_optimizer("da_mh_gp", space, **options)
    engine = CalibrationEngine(
        space=space,
        optimizer=opt,
        evaluator=evaluator or _make_quadratic_evaluator(),
        max_trials=max_trials,
    )
    return opt, engine.run()


class TestDaMhGpSmoke:
    def test_registered_and_builds(self):
        """``build_optimizer`` must return a valid DA-MH-GP instance."""
        opt = build_optimizer("da_mh_gp", _quadratic_space(), chain_length=20, n_init=4, seed=42)
        assert opt.name == "da_mh_gp"

    def test_runs_and_accepts_samples(self):
        """DA-MH-GP should complete a small run on a convex RMSE surface."""
        opt, session = _fit(max_trials=100, chain_length=30, n_init=6, burn_in=10, seed=42)
        completed = [r for r in session.history if r.status == "completed"]
        # At least the initial design must be evaluated.
        assert len(completed) >= 6
        assert opt.converged(), "optimizer must flag convergence after its thread exits"


class TestDaMhGpBest:
    def test_posterior_mode_recovers_optimum(self):
        """``best()`` should surface a posterior mode close to the RMSE minimum."""
        opt, _ = _fit(max_trials=100, chain_length=40, n_init=6, burn_in=10, seed=42)
        best = opt.best()
        assert best is not None
        # best is an EvaluationResult enriched with the posterior mode.
        assert best.metadata is not None and "posterior_mode" in best.metadata
        mode = best.metadata["posterior_mode"]
        assert np.isclose(mode["x"], 1.0, atol=0.6)
        assert np.isclose(mode["y"], -2.0, atol=0.6)

    def test_best_picks_the_trial_nearest_the_mode_without_values_metadata(self):
        """``best()`` must not rely on ``metadata["values"]``.

        The real engine (``optim/engine.py``) never writes a ``values`` key
        into ``EvaluationResult.metadata``; only the evaluator above does, as a
        convenience. Reproduce the production shape here so the picked trial
        cannot be found through that key, and check it is still the evaluated
        point nearest the posterior mode in transformed space.
        """
        transformed_by_trial: dict[int, np.ndarray] = {}

        def _eval(sugg):
            transformed_by_trial[sugg.trial_id] = np.array(
                [
                    p.to_transformed(float(sugg.values[p.name]))
                    for p in _quadratic_space().parameters
                ],
                dtype=float,
            )
            result = _make_quadratic_evaluator()(sugg)
            return EvaluationResult(trial_id=sugg.trial_id, sim_id=None, cost=result.cost)

        opt, _ = _fit(_eval, max_trials=100, chain_length=40, n_init=6, burn_in=10, seed=42)
        best = opt.best()
        assert best is not None
        assert "values" not in (best.metadata or {})

        idx_mode = int(np.argmax(opt._chain_logpost))
        x_mode_t = np.asarray(opt._chain[idx_mode], dtype=float)
        expected_trial_id = min(
            transformed_by_trial,
            key=lambda tid: float(np.linalg.norm(transformed_by_trial[tid] - x_mode_t)),
        )
        assert best.trial_id == expected_trial_id

    def test_best_returns_none_when_nothing_evaluated(self):
        """``best()`` must return ``None`` before any ``tell()``."""
        opt = build_optimizer("da_mh_gp", _quadratic_space(), chain_length=5, n_init=3, seed=0)
        assert opt.best() is None


class TestDaMhGpChain:
    def test_chain_length_matches_the_option(self):
        """Full chain length should equal the requested ``chain_length`` MCMC budget."""
        opt, _ = _fit(chain_length=25, n_init=4, burn_in=5, seed=7)
        assert opt.chain.shape == (25, 2)

    def test_posterior_samples_excludes_burn_in(self):
        """``posterior_samples`` drops the burn-in prefix and is in physical units."""
        opt, _ = _fit(chain_length=30, n_init=4, burn_in=7, seed=0)
        samples = opt.posterior_samples
        assert samples.shape == (30 - 7, 2)
        assert np.all((samples >= -4.0) & (samples <= 4.0))

    def test_thin_reduces_posterior_sample_count(self):
        """thin>1 must reduce posterior_samples length proportionally."""
        opt, _ = _fit(chain_length=30, n_init=4, burn_in=6, seed=0, thin=3)
        assert opt.posterior_samples.shape == (int(np.ceil((30 - 6) / 3)), 2)


@pytest.mark.parametrize(
    ("options", "match"),
    [
        ({"sigma_noise": 0.0}, "sigma_noise must be > 0"),
        ({"full_mh_prob": 1.5}, "full_mh_prob"),
        ({"proposal_sigma": 0.0}, "proposal_sigma"),
    ],
    ids=["sigma_noise", "full_mh_prob", "proposal_sigma"],
)
def test_the_sampler_refuses_an_out_of_range_option(options, match):
    with pytest.raises(ValueError, match=match):
        build_optimizer("da_mh_gp", _quadratic_space(), **options)


class TestDaMhGpAdvancedKwargs:
    def test_accepts_full_canonical_kwargs(self):
        """Adapter must construct with thin, gp_alpha and cache_decimals."""
        opt = build_optimizer(
            "da_mh_gp",
            _quadratic_space(),
            sigma_noise=0.1,
            n_init=4,
            chain_length=64,
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
        assert opt._chain_length == 64
        assert opt._proposal_std[0] == pytest.approx(0.4)
        assert opt._gp_alpha == pytest.approx(1.0e-6)
        assert opt._thin == 2
        assert opt._cache_decimals == 10

    @pytest.mark.parametrize("kwarg", ["proposal_scale", "n_samples", "gp_noise"])
    def test_removed_compatibility_kwargs_are_rejected(self, kwarg: str):
        """Removed compatibility kwargs are not accepted."""
        with pytest.raises(TypeError, match=kwarg):
            build_optimizer("da_mh_gp", _quadratic_space(), sigma_noise=0.5, **{kwarg: 1})

    def test_cache_decimals_dedupes_repeated_proposals(self):
        """A re-evaluation at the same rounded location must hit the cache."""
        opt = build_optimizer(
            "da_mh_gp", _quadratic_space(), chain_length=4, n_init=2, seed=0, cache_decimals=3
        )
        x = np.array([0.123456, -0.654321], dtype=float)
        opt._eval_cache[opt._cache_key(x)] = -1.234
        cached = opt._eval_cache[opt._cache_key(x + 1e-6)]
        assert cached == pytest.approx(-1.234)
