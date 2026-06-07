"""Analytical reference solution for the steady circular-island piecewise-K case.

This validation case targets a single-density unconfined aquifer on a circular
island with:

- uniform recharge on land,
- one flat impermeable substratum,
- imposed sea level through HydroModPy's ``ocean`` boundary condition,
- concentric piecewise-constant hydraulic conductivity,
- no salt wedge and no density correction.

For saturated thickness ``H = h - z_b`` above a flat substratum ``z_b``, the
steady radial Dupuit-Boussinesq equation is:

``(1 / r) d/dr (r K H dH/dr) + R = 0``

with symmetry at the island center ``dH/dr(0) = 0`` and a fixed coastal head
``h(a) = h_sea`` at shoreline radius ``a``. For piecewise-constant ``K(r)``,
the transformed variable ``U = H^2`` satisfies:

``U(r) = U(a) + R ∫_r^a s / K(s) ds``

The comparison function below evaluates the resulting hydraulic head for
``r <= a`` and returns ``h_sea`` offshore.

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

from validation_cases.analytical.steady.boussinesq_piecewise import (
    expected_boussinesq_circular_island_piecewise_k_head,
)

__all__ = ["expected_boussinesq_circular_island_piecewise_k_head"]
