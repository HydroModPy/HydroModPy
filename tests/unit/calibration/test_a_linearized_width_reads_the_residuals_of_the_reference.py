"""The residuals of a linearized width belong to the reference point.

The runner captures the simulated vector of the last model run and reads its
residuals once the Jacobian is built. That last run used to be the last
perturbed trial, a point 1 % away from the calibrated answer.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.optim.fosm import forward_difference_jacobian

REFERENCE = {"K": 2.0, "Sy": 0.5}


def _model(values) -> np.ndarray:
    k, sy = float(values["K"]), float(values["Sy"])
    return np.array([k**2, k * sy, np.exp(sy)])


def _capturing():
    captured: dict[str, np.ndarray] = {}

    def simulate(values):
        captured["simulated"] = _model(values)
        return captured["simulated"]

    return simulate, captured


def test_the_last_run_of_the_jacobian_is_the_reference() -> None:
    simulate, captured = _capturing()

    forward_difference_jacobian(("K", "Sy"), REFERENCE, simulate)

    np.testing.assert_array_equal(captured["simulated"], _model(REFERENCE))


def test_the_derivatives_do_not_depend_on_the_order_of_the_runs() -> None:
    simulate, _ = _capturing()

    jacobian = forward_difference_jacobian(("K", "Sy"), REFERENCE, simulate, relative_step=1e-6)

    expected = np.array([[4.0, 0.0], [0.5, 2.0], [0.0, np.exp(0.5)]])
    assert jacobian == pytest.approx(expected, rel=1e-4, abs=1e-5)
