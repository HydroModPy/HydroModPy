"""Unit tests for the smooth Boussinesq operators (smoothing.py).

Checks:
- smooth_positive_part reproduces max(u,0) away from the kink
- dsmooth_positive_part is the correct analytic derivative
- smooth_positive_thickness reproduces clip(u,0,bmax) away from the kinks
- Drainage Jacobian is consistent with the smooth drainage residual
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.smoothing import (
    dsmooth_positive_part,
    smooth_positive_part,
    smooth_positive_thickness,
)

# ---------------------------------------------------------------------------
# smooth_positive_part
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "u_val",
    [5.0, 10.0, 100.0],
)
def test_smooth_positive_part_large_positive(u_val: float) -> None:
    """Away from 0, smooth_positive_part ≈ u."""
    eps = 0.01
    result = float(smooth_positive_part(np.array([u_val]), eps)[0])
    assert abs(result - u_val) < 1e-4 * u_val


@pytest.mark.parametrize(
    "u_val",
    [-5.0, -10.0, -100.0],
)
def test_smooth_positive_part_large_negative(u_val: float) -> None:
    """Away from 0 on the negative side, smooth_positive_part ≈ 0."""
    eps = 0.01
    result = float(smooth_positive_part(np.array([u_val]), eps)[0])
    assert abs(result) < 1e-4 * abs(u_val)


def test_smooth_positive_part_always_positive() -> None:
    """smooth_positive_part is strictly positive for any finite input."""
    u = np.linspace(-10.0, 10.0, 201)
    result = smooth_positive_part(u, 0.01)
    assert np.all(result > 0.0)


def test_dsmooth_positive_part_matches_fd() -> None:
    """Analytic derivative matches finite differences."""
    u = np.linspace(-2.0, 2.0, 41)
    eps = 0.1
    h = 1e-6
    fd = (smooth_positive_part(u + h, eps) - smooth_positive_part(u - h, eps)) / (2 * h)
    analytic = dsmooth_positive_part(u, eps)
    np.testing.assert_allclose(analytic, fd, rtol=1e-5, atol=1e-10)


def test_dsmooth_positive_part_range() -> None:
    """Derivative stays in (0, 1) everywhere."""
    u = np.linspace(-50.0, 50.0, 1001)
    d = dsmooth_positive_part(u, 0.05)
    assert np.all(d > 0.0)
    assert np.all(d < 1.0)


# ---------------------------------------------------------------------------
# smooth_positive_thickness
# ---------------------------------------------------------------------------


def test_smooth_positive_thickness_interior() -> None:
    """clip(u, 0, bmax) ≈ u when u is well inside (0, bmax)."""
    bmax = np.array([30.0])
    raw = np.array([15.0])
    result = float(smooth_positive_thickness(raw, bmax, eps=0.01)[0])
    assert abs(result - 15.0) < 1e-3


def test_smooth_positive_thickness_fully_dry() -> None:
    """clip(u, 0, bmax) ≈ 0 when u << 0."""
    bmax = np.array([30.0])
    raw = np.array([-20.0])
    result = float(smooth_positive_thickness(raw, bmax, eps=0.01)[0])
    assert abs(result) < 1e-4


def test_smooth_positive_thickness_fully_saturated() -> None:
    """clip(u, 0, bmax) ≈ bmax when u >> bmax."""
    bmax = np.array([30.0])
    raw = np.array([60.0])
    result = float(smooth_positive_thickness(raw, bmax, eps=0.01)[0])
    assert abs(result - 30.0) < 1e-3


def test_smooth_positive_thickness_zero_bmax() -> None:
    """When bmax=0 the result is zero regardless of raw."""
    bmax = np.array([0.0])
    raw = np.array([5.0])
    result = float(smooth_positive_thickness(raw, bmax, eps=0.05)[0])
    assert abs(result) < 1e-6


# ---------------------------------------------------------------------------
# Jacobian consistency: smooth operators only (no mesh required)
# ---------------------------------------------------------------------------


def test_drainage_jacobian_consistency_via_smoothing() -> None:
    """dsmooth_positive_part is the exact FD derivative of smooth_positive_part (drainage case)."""

    head_minus_ztop = np.linspace(-0.5, 0.5, 51)
    eps = 0.01
    h = 1e-6
    fd = (
        smooth_positive_part(head_minus_ztop + h, eps)
        - smooth_positive_part(head_minus_ztop - h, eps)
    ) / (2 * h)
    analytic = dsmooth_positive_part(head_minus_ztop, eps)
    np.testing.assert_allclose(analytic, fd, rtol=1e-4, atol=1e-7)
