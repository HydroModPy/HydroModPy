"""Unit tests of the options of the linear reservoir backend."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.solver.linear_reservoir.options import LinearReservoirOptions


def test_time_constant_reads_a_bare_number_in_days() -> None:
    assert LinearReservoirOptions(time_constant=30.0).time_constant == 30.0
    assert LinearReservoirOptions(time_constant="30 days").time_constant == 30.0


@pytest.mark.parametrize("rate", [0.0, -0.1])
def test_a_rate_of_zero_or_below_is_refused(rate: float) -> None:
    with pytest.raises(ValidationError):
        LinearReservoirOptions(time_constant=rate)


def test_a_table_without_its_time_constant_is_refused() -> None:
    with pytest.raises(ValidationError):
        LinearReservoirOptions()


def test_an_unknown_key_of_the_table_is_refused() -> None:
    with pytest.raises(ValidationError):
        LinearReservoirOptions(time_constant=30.0, no_solver_has_this_key=1)
