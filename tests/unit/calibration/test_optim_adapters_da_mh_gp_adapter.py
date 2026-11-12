"""Tests of `optim.adapters.da_mh_gp_adapter`."""

from __future__ import annotations

import numpy as np
import pytest
import sklearn  # noqa: F401

from hydromodpy.calibration.optim.adapters import da_mh_gp_adapter as da_module
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, build_optimizer
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
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

    def test_best_returns_none_when_nothing_evaluated(self):
        """``best()`` must return ``None`` before any ``tell()``."""
        opt = build_optimizer("da_mh_gp", _quadratic_space(), chain_length=5, n_init=3, seed=0)
        assert opt.best() is None


class TestDaMhGpChain:
    def test_a_result_is_fed_to_the_chain_once_and_a_failed_one_as_nan(self):
        opt = build_optimizer("da_mh_gp", _quadratic_space(), chain_length=10, n_init=3, seed=0)
        fed: list[float] = []
        opt._bridge.feed = fed.append
        try:
            (first,) = opt.ask()
            assert first.source == "ask"
            stray = EvaluationResult(trial_id=99, sim_id=None, cost=1.0)
            opt.tell([stray, result_of(first, 5.0, status="failed")])
            # The stray result is passed over and the next one is still read.
            assert len(fed) == 1 and np.isnan(fed[0])
            assert not opt._pending
        finally:
            opt.close()

    def test_a_failed_trial_is_no_likelihood_value(self):
        """A failed trial is rejected by the chain and never trains the surrogate."""
        evaluate = _make_quadratic_evaluator()

        def _eval(sugg):
            if sugg.trial_id == 1:
                return EvaluationResult(trial_id=1, sim_id=None, cost=float("nan"), status="failed")
            return evaluate(sugg)

        opt, session = _fit(_eval, max_trials=30, chain_length=10, n_init=4, burn_in=2, seed=1)
        completed = [r for r in session.history if r.status == "completed"]
        assert len(completed) < len(session.history)
        assert len(opt._y_train) == len(completed) >= 3
        assert np.isfinite(opt._y_train).all()

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
        ({"proposal_sigma": [1.0, 2.0, 3.0]}, "proposal_sigma must have length 2"),
        ({"gp_alpha": 0.0}, "gp_alpha must be > 0"),
        ({"prior_mean": [0.0, 0.0]}, "must both be set or both None"),
    ],
    ids=["sigma_noise", "full_mh_prob", "proposal_sigma", "sigma_length", "gp_alpha", "prior"],
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

    def test_cache_decimals_dedupes_repeated_proposals(self):
        """A re-evaluation at the same rounded location must hit the cache."""
        opt = build_optimizer(
            "da_mh_gp", _quadratic_space(), chain_length=4, n_init=2, seed=0, cache_decimals=3
        )
        x = np.array([0.123456, -0.654321], dtype=float)
        opt._eval_cache[opt._cache_key(x)] = -1.234
        cached = opt._eval_cache[opt._cache_key(x + 1e-6)]
        assert cached == pytest.approx(-1.234)


class TestDaMhGpInternals:
    def test_a_normal_parameter_brings_its_prior_and_its_log_density(self):
        space = ParameterSpace(
            [CalibParameter(name=n, lower=-4.0, upper=4.0, sampling="normal") for n in "xy"]
        )
        opt = build_optimizer("da_mh_gp", space, seed=1)

        # Mean 0 and std (8 / 6) on each axis, so x = 8 / 6 is one sigma away.
        assert opt._log_prior(np.array([8.0 / 6.0, 0.0])) == pytest.approx(-0.5)

    def test_a_fresh_sampler_has_no_surrogate_chain_or_best(self):
        opt = build_optimizer("da_mh_gp", _quadratic_space(), seed=1)

        assert opt._fit_gp() is None
        assert opt._gp_mean(None, np.zeros(2)) == 0.0
        assert opt.chain.shape == (0, 2)
        assert opt.posterior_samples.size == 0
        assert opt.best() is None

    def test_a_point_outside_the_bounds_scores_minus_infinity_and_a_repeat_is_cached(self):
        opt = build_optimizer("da_mh_gp", _quadratic_space(), seed=1, cache_decimals=3)
        inside = np.array([0.5, 0.5])
        opt._eval_cache[opt._cache_key(inside)] = -2.0

        assert opt._evaluate_true(np.array([9.0, 0.0])) == -np.inf
        assert opt._evaluate_true(inside) == -2.0

    def test_the_bridge_refuses_a_submission_once_the_engine_aborted(self):
        bridge = da_module._EngineBridge()
        bridge.terminate()

        with pytest.raises(RuntimeError, match="sampler aborted by engine"):
            bridge.submit(np.zeros(2))

    def test_it_says_when_scikit_learn_is_missing(self, monkeypatch):
        monkeypatch.setattr(da_module, "_SKLEARN_AVAILABLE", False)

        with pytest.raises(ImportError, match="scikit-learn is required"):
            build_optimizer("da_mh_gp", _quadratic_space())

    def test_a_chain_with_wide_proposals_stays_in_bounds_and_fills_its_length(self):
        opt, _ = _fit(
            chain_length=40,
            n_init=4,
            burn_in=0,
            seed=3,
            proposal_sigma=6.0,
            full_mh_prob=0.5,
            cache_decimals=4,
        )

        assert opt.chain.shape == (40, 2)
        assert np.all(np.abs(opt.chain) <= 4.0)
        assert opt._eval_cache
        assert opt.best().metadata["posterior_mode"].keys() == {"x", "y"}
        with pytest.raises(StopIteration, match="da_mh_gp exhausted"):
            opt.suggest_next()

    def test_a_run_whose_design_scores_nothing_ends_without_a_chain(self):
        opt, _ = _fit(evaluator=lambda sugg: result_of(sugg, float("nan")), n_init=3, seed=0)

        assert opt.chain.shape == (0, 2)
        assert opt.converged()

    def test_a_result_for_a_trial_nobody_asked_is_ignored(self):
        opt, _ = _fit(chain_length=10, n_init=3, burn_in=0, seed=0)
        stranger = EvaluationResult(trial_id=999, sim_id=None, cost=0.0, status="completed")
        before = len(opt._results)

        opt.tell([stranger])
        opt._results.append(stranger)

        assert len(opt._results) == before + 1
        assert opt.best().trial_id != 999


def test_without_a_chain_the_best_trial_is_the_cheapest_completed_one():
    opt = build_optimizer("da_mh_gp", _quadratic_space(), seed=1)
    opt._results = [
        EvaluationResult(trial_id=1, sim_id=None, cost=3.0, status="completed"),
        EvaluationResult(trial_id=2, sim_id=None, cost=2.0, status="completed"),
        EvaluationResult(trial_id=3, sim_id=None, cost=0.1, status="failed"),
    ]

    assert opt.best().trial_id == 2
