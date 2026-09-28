"""The Eq. 4 bound is a length: ``Doptim <= validity_length``.

"auto" is two cells, the paper's ``roptim <= 2``. A declared accuracy raises
the cell size, the snap floor ``F`` replaces the map's cell when it is larger
(``h + max(h, F)``), and a declared length wins. The numbers are the ones the
decision cards tabulate for the Nancon and the V-valley bench.
"""

from __future__ import annotations

import math

import pytest

from hydromodpy.core.stream_geometry import (
    VALIDITY_PROVENANCE_BY_CODE,
    VALIDITY_PROVENANCE_CODE,
    resolve_validity_length,
)


@pytest.mark.parametrize(
    ("h_obs", "accuracy", "floor", "length", "provenance"),
    [
        (75.0, None, None, 150.0, "auto"),
        (25.0, 50.0, None, 100.0, "declared_accuracy"),
        (75.0, 50.0, None, 150.0, "auto"),
        (75.0, None, 41.0, 150.0, "auto"),
        (25.0, None, 75.6, 100.6, "auto_floor"),
        (10.0, None, 127.0, 137.0, "auto_floor"),
        (25.0, 50.0, 75.6, 125.6, "auto_floor"),
        (25.0, 50.0, 30.0, 100.0, "declared_accuracy"),
        (75.0, None, math.nan, 150.0, "auto"),
    ],
)
def test_auto_follows_the_cell_the_accuracy_and_the_floor(
    h_obs: float, accuracy: float | None, floor: float | None, length: float, provenance: str
) -> None:
    validity = resolve_validity_length(h_obs_m=h_obs, accuracy_m=accuracy, floor_m=floor)

    assert validity.length_m == pytest.approx(length)
    assert validity.provenance == provenance


def test_a_declared_length_wins() -> None:
    validity = resolve_validity_length(
        h_obs_m=25.0, accuracy_m=50.0, floor_m=300.0, declared_m=40.0
    )

    assert (validity.length_m, validity.provenance) == (40.0, "user")


def test_the_provenance_travels_as_a_code_and_comes_back() -> None:
    for name, code in VALIDITY_PROVENANCE_CODE.items():
        assert VALIDITY_PROVENANCE_BY_CODE[code] == name
    validity = resolve_validity_length(h_obs_m=10.0, floor_m=127.0)
    assert VALIDITY_PROVENANCE_BY_CODE[validity.code] == "auto_floor"
