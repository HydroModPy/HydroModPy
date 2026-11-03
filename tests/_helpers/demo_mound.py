"""The scaffolded demo as a physical case: a recharged hillslope that drains at its foot.

The demo is a 1 km square of 20 x 20 cells. The land surface falls by 5 m from the west
column to the east column, the base follows it 50 m below, and a uniform recharge leaves
through the drains at the land surface. The water table seeps in the east column and stays
below the surface elsewhere, as long as K is high enough for its gradient to stay below
the slope of the surface. The flow is then one-dimensional, and Dupuit gives the mound.
"""

from __future__ import annotations

from scipy.integrate import solve_ivp

CELL_M = 50.0
AREA_M2 = 1.0e6
RECHARGE_M_S = 0.8e-3 / 86400.0
SURFACE_DROP_M = 5.0
SURFACE_FOOT_M = 20.0
THICKNESS_M = 50.0


def dupuit_mound_m(k_m_s: float) -> float:
    """Return the rise of the water table from the east column to the west one.

    Going upslope from the centre of the drain column, ``K (h - z_b) dh/dx = R (L - x)``,
    with the saturated thickness over the sloping base and the no-flow divide at ``L``.
    """
    length = 1000.0 - CELL_M / 2.0
    span = 1000.0 - CELL_M
    slope = SURFACE_DROP_M / span

    def gradient(x: float, head: list[float]) -> list[float]:
        base = SURFACE_FOOT_M + slope * x - THICKNESS_M
        return [RECHARGE_M_S * (length - x) / (k_m_s * (head[0] - base))]

    solution = solve_ivp(gradient, (0.0, span), [SURFACE_FOOT_M], rtol=1e-10, atol=1e-10)
    return float(solution.y[0, -1] - SURFACE_FOOT_M)
