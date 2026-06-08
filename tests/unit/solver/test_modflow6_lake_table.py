"""The LAK stage-volume-area abacus feeding ``ModflowUtllaktab``.

MF6 interpolates the abacus and extrapolates poorly outside it, so the builder
sorts by stage and rejects any table that is not physically monotone: stage must
strictly increase, volume must not decrease (``dV/dz >= 0``) and surface area
must be non-negative.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from hydromodpy.solver.modflow6.builders import build_lake_table


def test_build_lake_table_sorts_by_stage_and_returns_triples() -> None:
    abacus = [
        (12.0, 50.0, 20.0),
        (10.0, 0.0, 5.0),
        (11.0, 20.0, 12.0),
    ]
    table = build_lake_table(None, lake_id="lac0", abacus=abacus)

    stages = [row[0] for row in table]
    assert stages == [10.0, 11.0, 12.0]  # sorted ascending
    assert all(len(row) == 3 for row in table)
    # Strictly increasing stage axis.
    assert all(b > a for a, b in pairwise(stages))


def test_build_lake_table_accepts_column_mapping() -> None:
    abacus = {"stage": [10.0, 11.0], "volume": [0.0, 20.0], "sarea": [5.0, 12.0]}
    table = build_lake_table(None, lake_id="lac0", abacus=abacus)
    assert table == [(10.0, 0.0, 5.0), (11.0, 20.0, 12.0)]


def test_build_lake_table_rejects_decreasing_volume() -> None:
    abacus = [(10.0, 30.0, 5.0), (11.0, 20.0, 12.0)]
    with pytest.raises(ValueError, match="volume must not decrease"):
        build_lake_table(None, lake_id="lac0", abacus=abacus)


def test_build_lake_table_rejects_duplicate_stage() -> None:
    abacus = [(10.0, 0.0, 5.0), (10.0, 20.0, 12.0)]
    with pytest.raises(ValueError, match="strictly increasing"):
        build_lake_table(None, lake_id="lac0", abacus=abacus)


def test_build_lake_table_rejects_negative_area() -> None:
    abacus = [(10.0, 0.0, 5.0), (11.0, 20.0, -1.0)]
    with pytest.raises(ValueError, match="must be"):
        build_lake_table(None, lake_id="lac0", abacus=abacus)


def test_build_lake_table_requires_two_rows() -> None:
    with pytest.raises(ValueError, match="at least two rows"):
        build_lake_table(None, lake_id="lac0", abacus=[(10.0, 0.0, 5.0)])
