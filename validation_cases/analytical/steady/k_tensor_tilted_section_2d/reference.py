"""Exact head and flux of a uniform flow with a K tensor tilted by ANGLE2.

MODFLOW 6 turns the K11 axis by ANGLE2 about the K22 axis, clockwise seen from
the positive K22 axis looking toward the center (Langevin et al. 2017, TM 6-A55,
NPF package). With ANGLE1 = 0 that axis is +y, and a positive ANGLE2 turns K11
from +x toward +z: K11 rises toward the east. In the plane (x, z) the tensor
then reads

    K_xx = K11 cos^2 a + K33 sin^2 a
    K_zz = K11 sin^2 a + K33 cos^2 a
    K_xz = (K11 - K33) sin a cos a

Far from the ends of the section, dh/dz = -(K_xz / K_zz) dh/dx and the flow
along it is (K11 K33 / K_zz) (-dh/dx) times its cross-section. A run with
ANGLE2 turning K11 toward -z would give the opposite dh/dz.
"""

from __future__ import annotations

from validation_cases.analytical.steady.k_tensor_strip import StripTensor, rotated_strip_tensor


def section_tensor(*, k11_m_per_s: float, k33_m_per_s: float, angle2_deg: float) -> StripTensor:
    """The tensor in the plane (x, z) for MODFLOW 6 K, K33 and ANGLE2, with ANGLE1 = 0."""
    return rotated_strip_tensor(k11_m_per_s, k33_m_per_s, angle2_deg)


__all__ = ["section_tensor"]
