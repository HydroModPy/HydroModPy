"""Smooth C¹ approximations of the piecewise operators used in Boussinesq.

Replacing hard kinks (``np.maximum``, ``np.clip``) with smooth counterparts
makes the Newton Jacobian continuous and improves solver convergence on fine
meshes where stiff ill-conditioned systems expose the non-differentiability.

All operators converge to their piecewise limits as ε → 0.

Default smoothing radii
-----------------------
``_EPS_THICKNESS_M``
    5 cm rounding radius at the aquifer floor and ceiling.  For a 10–50 m
    aquifer the relative bias is < 0.5 %.

``_EPS_DRAINAGE_M``
    1 cm rounding radius at the drainage activation level.

``_EPS_QEX_M_S``
    1e-8 m/s rounding radius for saturation-excess terms — same order as
    typical recharge rates so the kink is smoothed at physically relevant
    scales.

``_EPS_SIGMA``
    1 % rounding radius in the dimensionless saturation-ratio domain.
"""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# Default ε values
# ---------------------------------------------------------------------------

_EPS_THICKNESS_M: float = 5.0e-3  # 5 mm — keeps bias < 0.1 % on a 5+ m aquifer
_EPS_DRAINAGE_M: float = 0.01  # metres
_EPS_QEX_M_S: float = 1.0e-8  # m/s
_EPS_SIGMA: float = 1.0e-4  # dimensionless — bias < eps/(2r) ≈ 0.1 % for r=0.05


# ---------------------------------------------------------------------------
# Core smooth operators
# ---------------------------------------------------------------------------


def smooth_positive_part(u: np.ndarray, eps: float) -> np.ndarray:
    """Smooth approximation of ``max(u, 0)``.

    .. math::
        f(u) = \\tfrac{1}{2}\\bigl(u + \\sqrt{u^2 + \\varepsilon^2}\\bigr)

    Properties:

    - :math:`f(u) \\approx u` for :math:`u \\gg \\varepsilon`
    - :math:`f(u) \\approx 0` for :math:`u \\ll -\\varepsilon`
    - :math:`f(0) = \\varepsilon/2`  (small bias, vanishes as :math:`\\varepsilon\\to 0`)
    - Everywhere :math:`C^\\infty`
    """
    u = np.asarray(u, dtype=float)
    e = float(eps)
    return 0.5 * (u + np.sqrt(u * u + e * e))


def dsmooth_positive_part(u: np.ndarray, eps: float) -> np.ndarray:
    """Derivative of :func:`smooth_positive_part` with respect to ``u``.

    .. math::
        f'(u) = \\tfrac{1}{2}\\Bigl(1 + \\frac{u}{\\sqrt{u^2 + \\varepsilon^2}}\\Bigr)

    Returns values in :math:`(0, 1)` for all finite ``u``.
    """
    u = np.asarray(u, dtype=float)
    e = float(eps)
    return 0.5 * (1.0 + u / np.sqrt(u * u + e * e))


# ---------------------------------------------------------------------------
# Saturated thickness operators
# ---------------------------------------------------------------------------


def smooth_positive_thickness(
    raw: np.ndarray,
    bmax: np.ndarray,
    eps: float,
) -> np.ndarray:
    """Smooth approximation of ``clip(raw, 0, bmax)``.

    Uses the identity

    .. math::
        \\operatorname{clip}(u, 0, b_{\\max})
        \\approx f(u,\\varepsilon) - f(u - b_{\\max},\\varepsilon)

    where :math:`f` is :func:`smooth_positive_part`.  The formula transitions
    smoothly from 0 (fully dry) to :math:`b_{\\max}` (fully saturated).

    When :math:`b_{\\max} = 0` the result is identically zero.

    Parameters
    ----------
    raw:
        Head minus bottom elevation ``h - z_bottom`` (metres, per-cell array).
    bmax:
        Maximum aquifer thickness ``z_top - z_bottom`` (metres, per-cell array).
    eps:
        Smoothing radius in metres.
    """
    raw = np.asarray(raw, dtype=float)
    bmax = np.asarray(bmax, dtype=float)
    return smooth_positive_part(raw, eps) - smooth_positive_part(raw - bmax, eps)


def dsmooth_positive_thickness_dh(
    raw: np.ndarray,
    bmax: np.ndarray,
    eps: float,
) -> np.ndarray:
    """Derivative of :func:`smooth_positive_thickness` with respect to head.

    Since ``raw = h - z_bottom`` and :math:`\\partial\\,\\text{raw}/\\partial h = 1`,
    this equals the derivative of the smooth clip with respect to ``raw``.

    Parameters
    ----------
    raw:
        Head minus bottom elevation (metres, per-cell array).
    bmax:
        Maximum aquifer thickness (metres, per-cell array).
    eps:
        Smoothing radius in metres.
    """
    raw = np.asarray(raw, dtype=float)
    bmax = np.asarray(bmax, dtype=float)
    return dsmooth_positive_part(raw, eps) - dsmooth_positive_part(raw - bmax, eps)


# ---------------------------------------------------------------------------
# Saturation-ratio clip
# ---------------------------------------------------------------------------


def smooth_clip_01(x: np.ndarray, eps: float) -> np.ndarray:
    """Smooth approximation of ``clip(x, 0, 1)`` on the unit interval.

    Uses the same double-positive-part identity as
    :func:`smooth_positive_thickness` with :math:`b_{\\max}=1`.

    Parameters
    ----------
    x:
        Input array (dimensionless saturation ratio or similar).
    eps:
        Smoothing radius (dimensionless).
    """
    x = np.asarray(x, dtype=float)
    return smooth_positive_part(x, eps) - smooth_positive_part(x - 1.0, eps)


__all__ = [
    "_EPS_DRAINAGE_M",
    "_EPS_QEX_M_S",
    "_EPS_SIGMA",
    "_EPS_THICKNESS_M",
    "dsmooth_positive_part",
    "dsmooth_positive_thickness_dh",
    "smooth_clip_01",
    "smooth_positive_part",
    "smooth_positive_thickness",
]
