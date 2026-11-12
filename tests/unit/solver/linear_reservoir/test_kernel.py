"""Exact kernel of the linear reservoir, one piece of constant recharge at a time.

A piece of rate R (m/s) and duration dt (s) moves the stored depth s (m) toward tau * R with
the time constant tau (s). The depth released by a piece leaves through the outlet over a
catchment of area A (m2), in m3.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.units.quantities import SECONDS_PER_DAY
from hydromodpy.solver.linear_reservoir.kernel import advance_depth, run

TAU_S = 30.0 * SECONDS_PER_DAY
AREA_M2 = 1.0e6


def test_one_piece_matches_the_closed_form() -> None:
    rate = 2.0e-9  # m/s
    r_tau = TAU_S * rate
    expected = r_tau + (0.0 - r_tau) * np.exp(-SECONDS_PER_DAY / TAU_S)

    state = advance_depth(0.0, rate, SECONDS_PER_DAY, TAU_S)

    assert state == pytest.approx(expected, rel=1e-15)


# One row per sequence of pieces: the rates in m/s and the durations in days.
SEQUENCES = [
    pytest.param([2.0e-9, 0.0, 4.0e-9], [1.0, 1.0, 1.0], id="rain, one dry day, more rain"),
    pytest.param([3.0e-9] * 4, [28.0, 30.0, 31.0, 30.0], id="irregular months"),
]


@pytest.mark.parametrize(("rates", "days"), SEQUENCES)
def test_mass_is_conserved(rates, days) -> None:
    rates = np.array(rates)
    durations = np.array(days) * SECONDS_PER_DAY

    solved = run(rates, durations, 0.0, TAU_S, AREA_M2)

    # One answer per piece, in the order of the pieces.
    assert solved.stored_m.size == rates.size
    assert solved.released_m3.size == rates.size
    # What left plus what stayed is what the rain brought.
    rain_m3 = float(np.sum(rates * durations)) * AREA_M2
    stored_m3 = float(solved.stored_m[-1]) * AREA_M2
    assert float(np.sum(solved.released_m3)) + stored_m3 == pytest.approx(rain_m3, rel=1e-12)


def test_recession_without_recharge() -> None:
    state0_m = 0.02
    solved = run(np.zeros(5), np.full(5, SECONDS_PER_DAY), state0_m, TAU_S, AREA_M2)

    expected = state0_m * float(np.exp(-SECONDS_PER_DAY / TAU_S)) ** 5
    assert solved.stored_m[-1] == pytest.approx(expected, rel=1e-12)
    assert solved.stored_m[-1] < solved.stored_m[0]


def test_pieces_of_one_period_make_one_step() -> None:
    rate = 5.0e-8  # m/s
    one_step = run(np.array([rate]), np.array([5.0 * SECONDS_PER_DAY]), 0.0, TAU_S, AREA_M2)

    pieces = run(np.full(5, rate), np.full(5, SECONDS_PER_DAY), 0.0, TAU_S, AREA_M2)

    assert pieces.stored_m[-1] == pytest.approx(one_step.stored_m[-1], rel=1e-12)
    assert float(np.sum(pieces.released_m3)) == pytest.approx(
        float(one_step.released_m3[0]), rel=1e-12
    )


def test_equilibrium_stays_at_equilibrium() -> None:
    rate = 4.0e-9  # m/s, equilibrium depth tau * R
    solved = run(np.array([rate]), np.array([SECONDS_PER_DAY]), TAU_S * rate, TAU_S, AREA_M2)

    assert solved.stored_m[-1] == pytest.approx(TAU_S * rate, rel=1e-15)
