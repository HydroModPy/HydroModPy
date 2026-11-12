"""Unit tests for the ported ``groundwater_1d`` calibration case."""

from __future__ import annotations

import numpy as np

from tests._helpers.tolerances import tol
from validation_cases.calibration.unconfined_interface_1d.experiment import (
    build_noisy_groundwater_chronicle,
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
    def test_simulator_reproduces_true_heads(self):
        """With the true parameter set, the simulator output ~ noiseless obs."""
        chronicle = build_noisy_groundwater_chronicle(_FAST_CONFIG)
        simulator = make_groundwater_simulator(chronicle)
        sim_vec = simulator(chronicle["true_params"])
        truth_vec = chronicle["obs_true_matrix"].ravel(order="C")
        # Well-posed direct simulator output: rtol from TOLERANCES.md row 18.
        # atol matches rtol at the float64 noise floor (machine-epsilon companion).
        direct_rtol = tol("direct_solver_outputs__rtol")
        np.testing.assert_allclose(sim_vec, truth_vec, rtol=direct_rtol, atol=direct_rtol)
