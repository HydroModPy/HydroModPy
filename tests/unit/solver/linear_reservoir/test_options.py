"""Unit tests of the options of the linear reservoir backend."""

from __future__ import annotations

from hydromodpy.solver.linear_reservoir.options import LinearReservoirOptions


def test_time_constant_reads_a_bare_number_in_days() -> None:
    assert LinearReservoirOptions(time_constant=30.0).time_constant == 30.0
    assert LinearReservoirOptions(time_constant="30 days").time_constant == 30.0
