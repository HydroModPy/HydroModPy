"""Unit tests for the ported ``groundwater_1d`` calibration case."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.cases.groundwater_1d import (
    MODEL_PARAMETER_ORDER,
    build_noisy_groundwater_chronicle,
    calibrate_groundwater,
    default_parameter_space,
    make_groundwater_simulator,
)

# Compact chronicle config tuned for a fast calibration test (<5s).
_FAST_CONFIG = {
    "n_days": 40,
    "dt_days": 1.0,
    "L_m": 500.0,
    "xi_true_m": 220.0,
    "nx": 21,
    "formulation_true": "linearized",
    "H_linearized_m": 12.0,
    "Kam_true_m_per_day": 5.0,
    "Kav_true_m_per_day": 1.2,
    "Syam_true": 0.18,
    "Syav_true": 0.10,
    "h0_m": 6.0,
    "recharge_mode": "hydro_step",
    "obs_t_stride": 3,
    "obs_noise_std_m": 0.01,
    "obs_seed": 123,
}


def _relative_error(best: float, true: float) -> float:
    return abs(best - true) / abs(true)


class TestSyntheticChronicle:
    def test_deterministic_with_same_seed(self):
        """Same seed => identical noisy observation vector."""
        a = build_noisy_groundwater_chronicle(_FAST_CONFIG)
        b = build_noisy_groundwater_chronicle(_FAST_CONFIG)
        np.testing.assert_array_equal(a["obs_vector"], b["obs_vector"])
        np.testing.assert_array_equal(a["h_true"], b["h_true"])

    def test_different_seeds_differ(self):
        cfg1 = dict(_FAST_CONFIG, obs_seed=123)
        cfg2 = dict(_FAST_CONFIG, obs_seed=999)
        a = build_noisy_groundwater_chronicle(cfg1)
        b = build_noisy_groundwater_chronicle(cfg2)
        # True heads are identical; only the noisy observations differ.
        np.testing.assert_array_equal(a["h_true"], b["h_true"])
        assert not np.array_equal(a["obs_vector"], b["obs_vector"])

    def test_shapes_and_true_params(self):
        chronicle = build_noisy_groundwater_chronicle(_FAST_CONFIG)
        assert chronicle["t"].ndim == 1
        assert chronicle["h_true"].shape == (chronicle["t"].size, _FAST_CONFIG["nx"])
        assert chronicle["obs_noisy_matrix"].shape[0] == chronicle["obs_time_indices"].size
        assert chronicle["obs_noisy_matrix"].shape[1] == chronicle["obs_node_indices"].size
        assert chronicle["obs_vector"].size == chronicle["obs_noisy_matrix"].size
        assert set(chronicle["true_params"]) == set(MODEL_PARAMETER_ORDER)

    def test_simulator_reproduces_true_heads(self):
        """With the true parameter set, the simulator output ~ noiseless obs."""
        chronicle = build_noisy_groundwater_chronicle(_FAST_CONFIG)
        simulator = make_groundwater_simulator(chronicle)
        sim_vec = simulator(chronicle["true_params"])
        truth_vec = chronicle["obs_true_matrix"].ravel(order="C")
        np.testing.assert_allclose(sim_vec, truth_vec, rtol=1e-8, atol=1e-8)


class TestCalibrate:
    def test_default_parameter_space(self):
        space = default_parameter_space()
        assert space.names == MODEL_PARAMETER_ORDER
        assert space.dim == len(MODEL_PARAMETER_ORDER)

    def test_optuna_converges_near_truth(self):
        """Optuna/TPE should locate a neighbourhood of the true parameters."""
        pytest.importorskip("optuna")
        chronicle = build_noisy_groundwater_chronicle(_FAST_CONFIG)
        result = calibrate_groundwater(
            method="optuna",
            chronicle=chronicle,
            max_iter=30,
            seed=42,
        )
        assert result["best"] is not None
        assert result["best"].status == "completed"
        assert set(result["params_best"]) == set(MODEL_PARAMETER_ORDER)
        # The noise floor in the observation vector is ~1 cm; the optimizer
        # should push RMSE below a loose ceiling after 30 iterations.
        assert result["rmse_best"] < 1.5

    def test_grid_runs_and_returns_best(self):
        """Grid search should enumerate points and report the best."""
        chronicle = build_noisy_groundwater_chronicle(_FAST_CONFIG)
        # Small bounds + 2 points/dim => 2**5 = 32 grid points.
        result = calibrate_groundwater(
            method="grid",
            chronicle=chronicle,
            bounds={
                "Kam": (4.0, 6.0),
                "Kav": (0.8, 1.6),
                "Syam": (0.15, 0.22),
                "Syav": (0.08, 0.12),
                "xi": (200.0, 240.0),
            },
            max_iter=32,
            optimizer_kwargs={"points_per_dim": 2},
        )
        assert result["best"] is not None
        assert result["params_best"]
        # Best point in the tight grid must be reasonably close to the truth.
        params_true = result["params_true"]
        rel_err_xi = _relative_error(result["params_best"]["xi"], params_true["xi"])
        assert rel_err_xi < 0.20

    def test_calibrate_uses_default_chronicle_when_none_given(self):
        """Calling calibrate_groundwater without a chronicle builds one."""
        result = calibrate_groundwater(
            method="grid",
            max_iter=8,
            optimizer_kwargs={"points_per_dim": 2},
        )
        assert result["best"] is not None
        # The returned chronicle is usable downstream.
        assert "obs_vector" in result["chronicle"]
