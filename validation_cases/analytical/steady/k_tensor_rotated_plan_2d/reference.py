"""Exact head and flux of a uniform flow with a horizontal K tensor turned by ANGLE1.

MODFLOW 6 turns the K11 axis by ANGLE1 about the vertical, counter-clockwise
seen from above: from +x toward +y (Langevin et al. 2017, TM 6-A55, NPF
package). In the plane (x, y) the tensor then reads

    K_xx = K11 cos^2 a + K22 sin^2 a
    K_yy = K11 sin^2 a + K22 cos^2 a
    K_xy = (K11 - K22) sin a cos a

Far from the ends of the strip, dh/dy = -(K_xy / K_yy) dh/dx and the flow
along the strip is (K11 K22 / K_yy) (-dh/dx) times its cross-section.
"""

from __future__ import annotations

from validation_cases.analytical.steady.k_tensor_strip import StripTensor, rotated_strip_tensor


def plan_tensor(*, k11_m_per_s: float, k22_m_per_s: float, angle1_deg: float) -> StripTensor:
    """The tensor in the plane (x, y) for MODFLOW 6 K, K22 and ANGLE1."""
    return rotated_strip_tensor(k11_m_per_s, k22_m_per_s, angle1_deg)


__all__ = ["plan_tensor"]
