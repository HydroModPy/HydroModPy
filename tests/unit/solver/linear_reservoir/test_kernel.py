"""Unit tests of the exact kernel of the linear reservoir backend.

The four tests of this file verify the kernel the backend solves one
piece with: the closed form of the advance, the depth the piece releases,
the order of the answers, and the mass the sequence closes to.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.units.quantities import SECONDS_PER_DAY
from hydromodpy.solver.linear_reservoir.kernel import advance_depth, run


def test_one_piece_matches_the_closed_form() -> None:
    tau = 30.0 * SECONDS_PER_DAY
    rate = 2.0e-9
    state = advance_depth(0.0, rate, SECONDS_PER_DAY, tau)
    r_tau = tau * rate
    expected = r_tau + (0.0 - r_tau) * np.exp(-SECONDS_PER_DAY / tau)
    assert state == pytest.approx(expected, rel=1e-15)


def test_a_run_of_pieces_answers_in_their_order() -> None:
    """Rain of two days on an empty reservoir, then one dry day, then more rain."""
    rates = np.array([2.0e-9, 0.0, 4.0e-9])
    durations = np.full(rates.size, SECONDS_PER_DAY)
    solved = run(rates, durations, 0.0, 30.0 * SECONDS_PER_DAY, 1.0e6)
    assert solved.stored_m.size == 3
    assert solved.released_m3.size == 3
    # The mass closes over the whole run: what fell and left, plus what
    # stayed, is what the rain brought.
    rain = float(np.sum(rates * durations)) * 1.0e6
    stored = float(solved.stored_m[-1]) * 1.0e6
    assert float(np.sum(solved.released_m3)) + stored == pytest.approx(rain, rel=1e-12)


def test_a_recession_without_a_recharge_lets_the_state_fall() -> None:
    """Without a recharge the state decays, and the exponential is exact."""
    tau = 30.0 * SECONDS_PER_DAY
    state0 = 0.02
    solved = run(np.zeros(5), np.full(5, SECONDS_PER_DAY), state0, tau, 1.0e6)
    expected = state0 * float(np.exp(-SECONDS_PER_DAY / tau)) ** 5
    assert solved.stored_m[-1] == pytest.approx(expected, rel=1e-12)
    assert solved.stored_m[-1] < solved.stored_m[0]


def test_the_pieces_of_one_period_answer_as_one_step() -> None:
    """Native steps of one period integrate to the one-step answer."""
    tau = 30.0 * SECONDS_PER_DAY
    area = 1.0e6
    rate = 5.0e-8
    one_step = run(np.array([rate]), np.array([5.0 * SECONDS_PER_DAY]), 0.0, tau, area)
    rates = np.full(5, rate)
    durations = np.full(5, SECONDS_PER_DAY)
    pieces = run(rates, durations, 0.0, tau, area)
    assert pieces.stored_m[-1] == pytest.approx(one_step.stored_m[-1], rel=1e-12)
    assert float(np.sum(pieces.released_m3)) == pytest.approx(
        float(one_step.released_m3[0]), rel=1e-12
    )


def test_the_irregular_steps_close_the_mass() -> None:
    """Days of 28 to 31 days keep the mass closed to the machine."""
    tau = 30.0 * SECONDS_PER_DAY
    area = 1.0e6
    rates = np.full(4, 3.0e-9)
    durations = np.array([28.0, 30.0, 31.0, 30.0]) * SECONDS_PER_DAY
    solved = run(rates, durations, 0.0, tau, area)
    rain = float(np.sum(rates * durations)) * area
    stored = float(solved.stored_m[-1]) * area
    assert float(np.sum(solved.released_m3)) + stored == pytest.approx(rain, rel=1e-12)


def test_a_start_at_the_equilibrium_stays_at_it() -> None:
    """A state of `tau * R` under a constant rate holds there exactly."""
    tau = 30.0 * SECONDS_PER_DAY
    area = 1.0e6
    rate = 4.0e-9
    solved = run(np.array([rate]), np.array([SECONDS_PER_DAY]), tau * rate, tau, area)
    assert solved.stored_m[-1] == pytest.approx(tau * rate, rel=1e-15)
