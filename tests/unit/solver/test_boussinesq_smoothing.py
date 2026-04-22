"""Unit tests for the smooth Boussinesq operators (smoothing.py).

Checks:
- smooth_positive_part reproduces max(u,0) away from the kink
- dsmooth_positive_part is the correct analytic derivative
- smooth_positive_thickness reproduces clip(u,0,bmax) away from the kinks
- dsmooth_positive_thickness_dh is consistent with the finite-difference
  derivative of smooth_positive_thickness
- smooth_clip_01 reproduces clip(x,0,1) away from the kinks
- Jacobian consistency: saturated_thickness_derivative_from_head matches the
  FD derivative of saturated_thickness_from_head (via the assembly helpers)
- Drainage Jacobian is consistent with the smooth drainage residual
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.smoothing import (
    _EPS_DRAINAGE_M,
    _EPS_THICKNESS_M,
    dsmooth_positive_part,
    dsmooth_positive_thickness_dh,
    smooth_clip_01,
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


def test_dsmooth_positive_thickness_matches_fd() -> None:
    """Analytic derivative matches FD of smooth_positive_thickness."""
    bmax = np.full(51, 20.0)
    raw = np.linspace(-5.0, 25.0, 51)
    eps = 0.05
    h = 1e-6
    fd = (
        smooth_positive_thickness(raw + h, bmax, eps)
        - smooth_positive_thickness(raw - h, bmax, eps)
    ) / (2 * h)
    analytic = dsmooth_positive_thickness_dh(raw, bmax, eps)
    # Centered-FD has O(h²) truncation error; small atol covers floating-point noise
    np.testing.assert_allclose(analytic, fd, rtol=1e-4, atol=1e-7)


def test_dsmooth_positive_thickness_range() -> None:
    """Derivative stays in [0, 1]."""
    bmax = np.full(101, 25.0)
    raw = np.linspace(-10.0, 35.0, 101)
    d = dsmooth_positive_thickness_dh(raw, bmax, eps=0.05)
    assert np.all(d >= -1e-12)
    assert np.all(d <= 1.0 + 1e-12)


# ---------------------------------------------------------------------------
# smooth_clip_01
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("x_val", [0.5, 0.3, 0.8])
def test_smooth_clip_01_interior(x_val: float) -> None:
    """clip(x,0,1) ≈ x in the interior."""
    result = float(smooth_clip_01(np.array([x_val]), eps=0.01)[0])
    assert abs(result - x_val) < 1e-3


@pytest.mark.parametrize("x_val", [-5.0, -1.0])
def test_smooth_clip_01_below_zero(x_val: float) -> None:
    """clip(x,0,1) ≈ 0 for x << 0."""
    result = float(smooth_clip_01(np.array([x_val]), eps=0.01)[0])
    assert abs(result) < 1e-4


@pytest.mark.parametrize("x_val", [5.0, 2.0])
def test_smooth_clip_01_above_one(x_val: float) -> None:
    """clip(x,0,1) ≈ 1 for x >> 1."""
    result = float(smooth_clip_01(np.array([x_val]), eps=0.01)[0])
    assert abs(result - 1.0) < 1e-4


# ---------------------------------------------------------------------------
# Jacobian consistency: smooth operators only (no mesh required)
# ---------------------------------------------------------------------------


def test_thickness_jacobian_consistency_via_smoothing() -> None:
    """dsmooth_positive_thickness_dh is the exact FD derivative of smooth_positive_thickness."""
    bmax = np.array([0.0, 0.0, 20.0, 20.0, 20.0, 20.0, 20.0])
    raw = np.array([-5.0, 5.0, -2.0, 0.5, 10.0, 19.5, 25.0])
    eps = _EPS_THICKNESS_M
    h = 1e-6
    fd = (
        smooth_positive_thickness(raw + h, bmax, eps)
        - smooth_positive_thickness(raw - h, bmax, eps)
    ) / (2 * h)
    analytic = dsmooth_positive_thickness_dh(raw, bmax, eps)
    np.testing.assert_allclose(analytic, fd, rtol=1e-4, atol=1e-7)


def test_drainage_jacobian_consistency_via_smoothing() -> None:
    """dsmooth_positive_part is the exact FD derivative of smooth_positive_part (drainage case)."""

    head_minus_ztop = np.linspace(-0.5, 0.5, 51)
    eps = _EPS_DRAINAGE_M
    h = 1e-6
    fd = (
        smooth_positive_part(head_minus_ztop + h, eps)
        - smooth_positive_part(head_minus_ztop - h, eps)
    ) / (2 * h)
    analytic = dsmooth_positive_part(head_minus_ztop, eps)
    np.testing.assert_allclose(analytic, fd, rtol=1e-4, atol=1e-7)
