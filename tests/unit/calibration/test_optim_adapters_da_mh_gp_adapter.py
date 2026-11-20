"""DA-MH-GP sampler (`optim.adapters.da_mh_gp_adapter`) on a cheap 2-D quadratic RMSE.
Costs are dimensionless. The sampler follows the ask/tell protocol and
returns the posterior mode as best().
"""

from __future__ import annotations

import numpy as np
import pytest
import sklearn  # noqa: F401

from hydromodpy.calibration.optim.adapters import da_mh_gp_adapter as da_module
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, build_optimizer
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from tests.unit.calibration._factories_search import make_space, result_of

OPTIMUM = (1.0, -2.0)


def box_space():
    # Two parameters, bounds -4 to 4 around the origin.
    return make_space(("x", -4.0, 4.0), ("y", -4.0, 4.0))


def rmse_evaluator(sugg):
    x, y = float(sugg.values["x"]), float(sugg.values["y"])
    rmse = float(np.sqrt((x - OPTIMUM[0]) ** 2 + (y - OPTIMUM[1]) ** 2))
    return result_of(sugg, rmse, metadata={"values": dict(sugg.values)})


def run_sampler(evaluator=rmse_evaluator, max_trials=200, **options):
    """Build the sampler on the box space, run it, return it and its session."""
    space = box_space()
    opt = build_optimizer("da_mh_gp", space, **options)
    engine = CalibrationEngine(
        space=space, optimizer=opt, evaluator=evaluator, max_trials=max_trials
    )
    return opt, engine.run()


def failing_first_trial(sugg):
    if sugg.trial_id == 1:
        return EvaluationResult(trial_id=1, sim_id=None, cost=float("nan"), status="failed")
    return rmse_evaluator(sugg)


def test_posterior_mode_near_optimum():
    opt, _ = run_sampler(max_trials=100, chain_length=40, n_init=6, burn_in=10, seed=42)

    mode = opt.best().metadata["posterior_mode"]
    np.testing.assert_allclose([mode["x"], mode["y"]], OPTIMUM, atol=0.6)


def test_result_fed_once_failure_as_nan():
    opt = build_optimizer("da_mh_gp", box_space(), chain_length=10, n_init=3, seed=0)
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


def test_failed_trial_skips_surrogate():
    opt, session = run_sampler(
        failing_first_trial, max_trials=30, chain_length=10, n_init=4, burn_in=2, seed=1
    )

    completed = [r for r in session.history if r.status == "completed"]
    assert len(completed) < len(session.history)
    assert len(opt._y_train) == len(completed) >= 3
    assert np.isfinite(opt._y_train).all()


# (options, number of posterior samples kept)
POSTERIOR_SIZES = [
    pytest.param({"chain_length": 30, "burn_in": 7}, 30 - 7, id="burn-in dropped"),
    pytest.param({"chain_length": 30, "burn_in": 6, "thin": 3}, 8, id="thinned by 3"),
]


@pytest.mark.parametrize(("options", "n_samples"), POSTERIOR_SIZES)
def test_posterior_sample_count(options, n_samples):
    opt, _ = run_sampler(n_init=4, seed=0, **options)

    samples = opt.posterior_samples
    assert samples.shape == (n_samples, 2)
    assert np.all((samples >= -4.0) & (samples <= 4.0))


def test_canonical_options():
    opt = build_optimizer(
        "da_mh_gp",
        box_space(),
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


def test_rounded_location_hits_cache():
    opt = build_optimizer(
        "da_mh_gp", box_space(), chain_length=4, n_init=2, seed=0, cache_decimals=3
    )
    x = np.array([0.123456, -0.654321])
    opt._eval_cache[opt._cache_key(x)] = -1.234

    assert opt._eval_cache[opt._cache_key(x + 1e-6)] == pytest.approx(-1.234)


def test_normal_prior_log_density():
    space = ParameterSpace(
        [CalibParameter(name=n, lower=-4.0, upper=4.0, sampling="normal") for n in "xy"]
    )
    opt = build_optimizer("da_mh_gp", space, seed=1)

    # Mean 0 and std (8 / 6) on each axis, so x = 8 / 6 is one sigma away.
    assert opt._log_prior(np.array([8.0 / 6.0, 0.0])) == pytest.approx(-0.5)


def test_fresh_sampler_is_empty():
    opt = build_optimizer("da_mh_gp", box_space(), seed=1)

    assert opt._fit_gp() is None
    assert opt._gp_mean(None, np.zeros(2)) == 0.0
    assert opt.chain.shape == (0, 2)
    assert opt.posterior_samples.size == 0
    assert opt.best() is None


def test_outside_bounds_scores_minus_infinity():
    opt = build_optimizer("da_mh_gp", box_space(), seed=1, cache_decimals=3)
    inside = np.array([0.5, 0.5])
    opt._eval_cache[opt._cache_key(inside)] = -2.0

    assert opt._evaluate_true(np.array([9.0, 0.0])) == -np.inf
    assert opt._evaluate_true(inside) == -2.0


def test_wide_proposals_stay_in_bounds():
    opt, _ = run_sampler(
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


def test_design_scoring_nothing_has_no_chain():
    opt, _ = run_sampler(evaluator=lambda sugg: result_of(sugg, float("nan")), n_init=3, seed=0)

    assert opt.chain.shape == (0, 2)
    assert opt.converged()


def test_unasked_trial_ignored():
    opt, _ = run_sampler(chain_length=10, n_init=3, burn_in=0, seed=0)
    stranger = EvaluationResult(trial_id=999, sim_id=None, cost=0.0, status="completed")
    before = len(opt._results)

    opt.tell([stranger])
    opt._results.append(stranger)

    assert len(opt._results) == before + 1
    assert opt.best().trial_id != 999


def test_best_without_chain_is_cheapest():
    opt = build_optimizer("da_mh_gp", box_space(), seed=1)
    opt._results = [
        EvaluationResult(trial_id=1, sim_id=None, cost=3.0, status="completed"),
        EvaluationResult(trial_id=2, sim_id=None, cost=2.0, status="completed"),
        EvaluationResult(trial_id=3, sim_id=None, cost=0.1, status="failed"),
    ]

    assert opt.best().trial_id == 2


def test_missing_scikit_learn(monkeypatch):
    monkeypatch.setattr(da_module, "_SKLEARN_AVAILABLE", False)

    with pytest.raises(ImportError, match="scikit-learn is required"):
        build_optimizer("da_mh_gp", box_space())


def test_bridge_refuses_after_abort():
    bridge = da_module._EngineBridge()
    bridge.terminate()

    with pytest.raises(RuntimeError, match="sampler aborted by engine"):
        bridge.submit(np.zeros(2))


REFUSALS = [
    pytest.param({"sigma_noise": 0.0}, "sigma_noise must be > 0", id="sigma_noise"),
    pytest.param({"full_mh_prob": 1.5}, "full_mh_prob", id="full_mh_prob"),
    pytest.param({"proposal_sigma": 0.0}, "proposal_sigma", id="proposal_sigma"),
    pytest.param(
        {"proposal_sigma": [1.0, 2.0, 3.0]}, "proposal_sigma must have length 2", id="sigma_length"
    ),
    pytest.param({"gp_alpha": 0.0}, "gp_alpha must be > 0", id="gp_alpha"),
    pytest.param({"prior_mean": [0.0, 0.0]}, "must both be set or both None", id="prior"),
]


@pytest.mark.parametrize(("options", "match"), REFUSALS)
def test_refusals(options, match):
    with pytest.raises(ValueError, match=match):
        build_optimizer("da_mh_gp", box_space(), **options)
