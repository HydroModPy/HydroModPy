"""The package-agnostic MVR record builder.

The general :func:`build_mvr_period_records` knows nothing about LAK: it formats
and validates :class:`MoverRecord` transfers between any two named packages. The
tests check that:

* records keep their provider / receiver package names and ids untouched, for a
  mix of packages (SFR, LAK, MAW);
* :func:`mover_package_count` counts the distinct package names referenced;
* an unknown ``mvrtype`` is rejected;
* a negative ``value`` is rejected.
"""

from __future__ import annotations

import pytest

from hydromodpy.solver.modflow6.builders import (
    MoverRecord,
    build_mvr_period_records,
    mover_package_count,
)


def test_records_are_package_agnostic() -> None:
    # A mix of providers / receivers across SFR, LAK and MAW formats unchanged.
    moves = [
        MoverRecord("SFR-1", 2, "LAK-1", 0, "FACTOR", 1.0),
        MoverRecord("MAW-1", 1, "SFR-1", 5, "UPTO", 3.0),
    ]
    records = build_mvr_period_records(moves)
    assert records == [
        ["SFR-1", 2, "LAK-1", 0, "FACTOR", 1.0],
        ["MAW-1", 1, "SFR-1", 5, "UPTO", 3.0],
    ]
    # SFR-1, LAK-1 and MAW-1 are three distinct packages.
    assert mover_package_count(records) == 3


def test_unknown_mvrtype_is_rejected() -> None:
    with pytest.raises(ValueError, match="mvrtype must be one of"):
        build_mvr_period_records([MoverRecord("SFR-1", 0, "LAK-1", 0, "SIPHON", 1.0)])


def test_negative_value_is_rejected() -> None:
    with pytest.raises(ValueError, match="value must be >= 0"):
        build_mvr_period_records([MoverRecord("SFR-1", 0, "LAK-1", 0, "FACTOR", -1.0)])
