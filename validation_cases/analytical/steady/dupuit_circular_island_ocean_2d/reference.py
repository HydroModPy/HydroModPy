"""Analytical reference solution for the steady circular-island ocean case.

This validation case targets a single-density unconfined aquifer on a circular
island with:

- uniform recharge on land,
- one flat impermeable substratum,
- imposed sea level through HydroModPy's ``ocean`` boundary condition,
- no salt wedge and no density correction.

For saturated thickness ``H = h - z_b`` above a flat substratum ``z_b``, the
steady radial Dupuit-Boussinesq equation is:

``(1 / r) d/dr (r K H dH/dr) + R = 0``

with symmetry at the island center ``dH/dr(0) = 0`` and a fixed coastal head
``h(a) = h_sea`` at shoreline radius ``a``. Integrating gives:

``H(r)^2 = H(a)^2 + (R / (2 K)) (a^2 - r^2)``

where ``H(a) = h_sea - z_b``. The comparison function below evaluates the
resulting hydraulic head:

``h(r) = z_b + sqrt((h_sea - z_b)^2 + (R / (2 K)) (a^2 - r^2))``

for ``r <= a`` and returns ``h_sea`` offshore.

Related island-aquifer references
---------------------------------
- Fetter, C. W. (1972). Position of the saline water interface beneath oceanic
  islands. *Water Resources Research*, 8(5), 1307-1315.
  https://doi.org/10.1029/WR008i005p01307
- Kurylyk, B. L., Briggs, M. A., Bourret, M., Vacher, H. L., Michael, H. A.,
  Rotz, L. C. H., Xin, P., Costall, A. R., & Abd-Elhamid, H. F. (2024).
  Analytical methodology for determining the extent of pumped freshwater
  lenses in recharge-limited, circular islands. *Hydrological Processes*,
  38(4), e14935. https://doi.org/10.1002/hyp.14935

Those island-lens references introduce the sharp-interface density factor
``(1 + alpha)``. This validation explicitly removes that factor because the
numerical benchmark requested here excludes the salt wedge.
"""

from __future__ import annotations

import numpy as np


SECONDS_PER_DAY = 86400.0
MM_PER_M = 1000.0


def mm_day_to_m_s(value: float) -> float:
    """Convert a recharge rate from mm/day to m/s."""
    return float(value) / MM_PER_M / SECONDS_PER_DAY


def expected_dupuit_circular_island_head(
    *,
    radius_m: float | np.ndarray,
    island_radius_m: float,
    recharge_mm_day: float,
    hydraulic_conductivity_m_per_s: float,
    substratum_elevation_m: float,
    sea_level_m: float = 0.0,
) -> np.ndarray:
    """Return the steady radial Dupuit-Boussinesq head on a circular island."""
    radius = np.asarray(radius_m, dtype=float)
    shoreline_radius = float(island_radius_m)
    sea_level = float(sea_level_m)
    substratum = float(substratum_elevation_m)
    recharge_m_per_s = mm_day_to_m_s(recharge_mm_day)
    conductivity = float(hydraulic_conductivity_m_per_s)

    if shoreline_radius <= 0.0:
        raise ValueError("island_radius_m must be > 0.")
    if conductivity <= 0.0:
        raise ValueError("hydraulic_conductivity_m_per_s must be > 0.")
    if substratum >= sea_level:
        raise ValueError("substratum_elevation_m must stay below sea_level_m.")

    head = np.full(radius.shape, sea_level, dtype=float)
    land_mask = radius <= shoreline_radius
    if np.any(land_mask):
        coastal_thickness = sea_level - substratum
        head_sq = coastal_thickness**2 + (recharge_m_per_s / (2.0 * conductivity)) * (
            shoreline_radius**2 - radius[land_mask] ** 2
        )
        head[land_mask] = substratum + np.sqrt(head_sq)
    return head
