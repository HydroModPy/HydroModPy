"""Smooth versions of max(u, 0) and clip(u, 0, bmax) used by the Boussinesq residual.

The inputs are lengths in m and eps is the smoothing width in m. Away from the
kinks the smooth operators match the sharp ones. Their derivative is the exact
derivative of the smooth value.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.smoothing import (
    dsmooth_positive_part,
    smooth_positive_part,
    smooth_positive_thickness,
)

# (u in m, expected value in m, relative tolerance)
POSITIVE_PART = [
    pytest.param(5.0, 5.0, 1e-4, id="5 m above zero"),
    pytest.param(10.0, 10.0, 1e-4, id="10 m above zero"),
    pytest.param(100.0, 100.0, 1e-4, id="100 m above zero"),
    pytest.param(-5.0, 0.0, 1e-4, id="5 m below zero"),
    pytest.param(-10.0, 0.0, 1e-4, id="10 m below zero"),
    pytest.param(-100.0, 0.0, 1e-4, id="100 m below zero"),
]


@pytest.mark.parametrize(("u_m", "expected_m", "rel_tol"), POSITIVE_PART)
def test_positive_part_away_from_the_kink(u_m, expected_m, rel_tol) -> None:
    result = float(smooth_positive_part(np.array([u_m]), 0.01)[0])

    assert abs(result - expected_m) < rel_tol * abs(u_m)


def test_positive_part_is_strictly_positive() -> None:
    result = smooth_positive_part(np.linspace(-10.0, 10.0, 201), 0.01)

    assert np.all(result > 0.0)


# (u range in m, eps in m, rtol, atol) for a central finite difference with h = 1e-6 m
DERIVATIVE_CHECKS = [
    pytest.param(np.linspace(-2.0, 2.0, 41), 0.1, 1e-5, 1e-10, id="wide width"),
    # The drainage term: head minus ground level, within half a meter.
    pytest.param(np.linspace(-0.5, 0.5, 51), 0.01, 1e-4, 1e-7, id="drainage"),
]


@pytest.mark.parametrize(("u_m", "eps_m", "rtol", "atol"), DERIVATIVE_CHECKS)
def test_derivative_matches_finite_difference(u_m, eps_m, rtol, atol) -> None:
    h = 1e-6
    fd = (smooth_positive_part(u_m + h, eps_m) - smooth_positive_part(u_m - h, eps_m)) / (2 * h)

    np.testing.assert_allclose(dsmooth_positive_part(u_m, eps_m), fd, rtol=rtol, atol=atol)


def test_derivative_stays_between_zero_and_one() -> None:
    d = dsmooth_positive_part(np.linspace(-50.0, 50.0, 1001), 0.05)

    assert np.all(d > 0.0)
    assert np.all(d < 1.0)


# (raw in m, bmax in m, eps in m, expected in m, absolute tolerance)
THICKNESS = [
    pytest.param(15.0, 30.0, 0.01, 15.0, 1e-3, id="inside the range"),
    pytest.param(-20.0, 30.0, 0.01, 0.0, 1e-4, id="fully dry"),
    pytest.param(60.0, 30.0, 0.01, 30.0, 1e-3, id="fully saturated"),
    pytest.param(5.0, 0.0, 0.05, 0.0, 1e-6, id="no thickness at all"),
]


@pytest.mark.parametrize(("raw_m", "bmax_m", "eps_m", "expected_m", "tol"), THICKNESS)
def test_thickness_is_a_smooth_clip(raw_m, bmax_m, eps_m, expected_m, tol) -> None:
    result = float(smooth_positive_thickness(np.array([raw_m]), np.array([bmax_m]), eps=eps_m)[0])

    assert abs(result - expected_m) < tol
