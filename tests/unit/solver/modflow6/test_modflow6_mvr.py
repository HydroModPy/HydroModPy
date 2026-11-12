"""The MVR record builder, which knows nothing about LAK.

It formats and validates transfers between any two named packages (SFR, LAK, MAW).
A record is [provider package, provider id, receiver package, receiver id, mvrtype,
value], with value a fraction or a rate depending on mvrtype.
"""

from __future__ import annotations

import pytest

from hydromodpy.solver.modflow6.builders.mvr import (
    MoverRecord,
    build_mvr_period_records,
    mover_package_count,
)


def test_records_keep_their_packages_and_ids() -> None:
    moves = [
        MoverRecord("SFR-1", 2, "LAK-1", 0, "FACTOR", 1.0),
        MoverRecord("MAW-1", 1, "SFR-1", 5, "UPTO", 3.0),
    ]

    records = build_mvr_period_records(moves)

    assert records == [
        ["SFR-1", 2, "LAK-1", 0, "FACTOR", 1.0],
        ["MAW-1", 1, "SFR-1", 5, "UPTO", 3.0],
    ]
    assert mover_package_count(records) == 3  # SFR-1, LAK-1 and MAW-1


REFUSALS = [
    pytest.param(
        MoverRecord("SFR-1", 0, "LAK-1", 0, "SIPHON", 1.0),
        "mvrtype must be one of",
        id="unknown mvrtype",
    ),
    pytest.param(
        MoverRecord("SFR-1", 0, "LAK-1", 0, "FACTOR", -1.0),
        "value must be >= 0",
        id="negative value",
    ),
]


@pytest.mark.parametrize(("move", "message"), REFUSALS)
def test_refusals(move, message) -> None:
    with pytest.raises(ValueError, match=message):
        build_mvr_period_records([move])
