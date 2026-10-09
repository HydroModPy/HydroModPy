"""Check the Brutsaert recession laws against a fine Dupuit solution of the same strip.

The reference of the two Brutsaert cases is a closed form. This test solves the
Boussinesq equation of the strip on a fine finite-volume grid with SciPy, from
the same steady water table under recharge, and asks the closed forms to match
it. It pins the constant of the nonlinear law for a strip drained on one side
and the modal weights of the linear series, without running a solver.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.integrate import solve_ivp
from scipy.sparse import diags

from validation_cases.analytical.transient.brutsaert_reference import (
    SECONDS_PER_DAY,
    linear_recession_discharge,
    linear_recession_rate,
    nonlinear_recession_coefficient,
)

K_M_PER_S = 1.0e-4
SPECIFIC_YIELD = 0.1
RECHARGE_M_PER_S = 2.0e-3 / SECONDS_PER_DAY
# A hundred times less recharge keeps the deep strip linear: a 4 mm rise on 50 m.
WEAK_RECHARGE_M_PER_S = 2.0e-5 / SECONDS_PER_DAY


def _fine_strip_discharge(
    *,
    length_m: float,
    width_m: float,
    outlet_head_m: float,
    recharged_length_m: float,
    days: np.ndarray,
    n_cells: int,
    recharge_m_per_s: float = RECHARGE_M_PER_S,
) -> np.ndarray:
    """Solve ``Sy dh/dt = K d/dx (h dh/dx)`` with a divide at 0 and ``h = outlet`` at ``length``.

    The face fluxes use ``K (h_i^2 - h_j^2) / (2 dx)``, the exact Dupuit flux
    between two heads. The initial state is the steady water table under
    recharge on ``[0, recharged_length]``.
    """
    dx = length_m / n_cells
    # Steady state on the same faces: K (h_i^2 - h_j^2) / (2 dx) carries the
    # recharge that fell upstream of the face, R min(x_face, recharged length).
    face_x = np.arange(1, n_cells + 1) * dx
    face_flux = recharge_m_per_s * np.minimum(face_x, recharged_length_m)
    face_drop = 2.0 * face_flux * dx / K_M_PER_S
    face_drop[-1] *= 0.5
    initial_head = np.sqrt(outlet_head_m**2 + np.cumsum(face_drop[::-1])[::-1])

    def rhs(_t: float, head: np.ndarray) -> np.ndarray:
        square = np.maximum(head, 0.0) ** 2
        face = np.zeros(n_cells + 1)
        face[1:n_cells] = K_M_PER_S * (square[:-1] - square[1:]) / (2.0 * dx)
        face[n_cells] = K_M_PER_S * (square[-1] - outlet_head_m**2) / dx
        return -(face[1:] - face[:-1]) / (SPECIFIC_YIELD * dx)

    def jacobian(_t: float, head: np.ndarray):
        positive = np.maximum(head, 0.0)
        scale = K_M_PER_S / dx
        main = np.zeros(n_cells)
        main[:-1] -= scale * positive[:-1]
        main[1:] -= scale * positive[1:]
        main[-1] -= 2.0 * scale * positive[-1]
        lower = scale * positive[:-1]
        upper = scale * positive[1:]
        return diags([lower, main, upper], [-1, 0, 1]) / (SPECIFIC_YIELD * dx)

    solution = solve_ivp(
        rhs,
        (0.0, float(days[-1]) * SECONDS_PER_DAY),
        initial_head,
        method="BDF",
        jac=jacobian,
        rtol=1.0e-10,
        atol=1.0e-12,
        t_eval=np.asarray(days, dtype=float) * SECONDS_PER_DAY,
    )
    assert solution.success, solution.message
    last = np.maximum(solution.y[-1], 0.0)
    return width_m * K_M_PER_S * (last**2 - outlet_head_m**2) / dx


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
def test_nonlinear_law_matches_a_fine_dupuit_strip_drained_on_one_side() -> None:
    """The late slope of ``Q^(-1/2)`` is ``a / 2`` and ``b`` is 3/2 on the fine strip."""
    length_m, width_m = 50.0, 30.0
    days = np.arange(16.0, 129.0)
    discharge = _fine_strip_discharge(
        length_m=length_m,
        width_m=width_m,
        outlet_head_m=0.0,
        recharged_length_m=length_m,
        days=days,
        n_cells=400,
    )
    coefficient = nonlinear_recession_coefficient(
        hydraulic_conductivity_m_per_s=K_M_PER_S,
        specific_yield=SPECIFIC_YIELD,
        drainage_length_m=length_m,
        outlet_width_m=width_m,
    )
    seconds = days * SECONDS_PER_DAY
    slope = np.polyfit(seconds, discharge**-0.5, 1)[0]
    decline = -np.diff(discharge) / np.diff(seconds)
    exponent = np.polyfit(np.log(np.sqrt(discharge[1:] * discharge[:-1])), np.log(decline), 1)[0]

    assert abs(2.0 * slope / coefficient - 1.0) < 1.0e-3
    assert abs(exponent - 1.5) < 2.0e-3


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
def test_linear_series_matches_a_fine_deep_strip_with_an_unrecharged_outlet_strip() -> None:
    """The series follows the fine strip when recharge stops short of the outlet."""
    length_m, width_m, thickness_m = 395.0, 30.0, 50.0
    recharged_length_m = 390.0
    days = np.arange(10.0, 91.0, 10.0)
    discharge = _fine_strip_discharge(
        length_m=length_m,
        width_m=width_m,
        outlet_head_m=thickness_m,
        recharged_length_m=recharged_length_m,
        days=days,
        n_cells=790,
        recharge_m_per_s=WEAK_RECHARGE_M_PER_S,
    )
    rate = linear_recession_rate(
        hydraulic_conductivity_m_per_s=K_M_PER_S,
        specific_yield=SPECIFIC_YIELD,
        saturated_thickness_m=thickness_m,
        drainage_length_m=length_m,
    )
    initial_discharge = WEAK_RECHARGE_M_PER_S * width_m * recharged_length_m
    series = linear_recession_discharge(
        elapsed_seconds=days * SECONDS_PER_DAY,
        initial_discharge_m3_s=initial_discharge,
        recession_rate_per_s=rate,
        drainage_length_m=length_m,
        recharged_length_m=recharged_length_m,
    )

    # Leaving out the unrecharged 5 m next to the outlet moves Q by 1 %.
    assert np.max(np.abs(discharge / series - 1.0)) < 1.0e-3
