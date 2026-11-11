"""Smooth C¹ approximations of the piecewise operators used in Boussinesq.

Replacing hard kinks (``np.maximum``, ``np.clip``) with smooth counterparts
makes the Newton Jacobian continuous and improves solver convergence on fine
meshes where stiff ill-conditioned systems expose the non-differentiability.

All operators converge to their piecewise limits as ε → 0.
"""

from __future__ import annotations

import numpy as np

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
        Head minus bottom elevation ``h - z_bottom`` (meters, per-cell array).
    bmax:
        Maximum aquifer thickness ``z_top - z_bottom`` (meters, per-cell array).
    eps:
        Smoothing radius in meters.
    """
    raw = np.asarray(raw, dtype=float)
    bmax = np.asarray(bmax, dtype=float)
    return smooth_positive_part(raw, eps) - smooth_positive_part(raw - bmax, eps)


# ---------------------------------------------------------------------------
# Saturation-ratio clip
# ---------------------------------------------------------------------------


__all__ = [
    "dsmooth_positive_part",
    "smooth_positive_part",
    "smooth_positive_thickness",
]
