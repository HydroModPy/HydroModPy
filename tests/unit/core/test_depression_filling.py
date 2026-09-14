"""Raising the closed depressions of a surface so every path reaches an outlet.

A downslope distance is a length along a flow path, and a flow path only exists
once the depressions are resolved. Conditioning a raster before delineation does
not carry over: it is pit-free on its own grid, and read at the centroids of a
mesh it grows new pits. The surface has to be conditioned on the graph the
distances are measured on.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.depression_filling import (
    DEFAULT_EPSILON_M,
    fill_depressions_on_graph,
)


def _chain(n: int) -> list[set[int]]:
    """Neighbours of a one-dimensional chain of cells."""
    return [{i - 1, i + 1} & set(range(n)) for i in range(n)]


def test_a_surface_without_a_pit_is_left_alone() -> None:
    values = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
    outlets = np.array([False, False, False, False, True])

    report = fill_depressions_on_graph(values, _chain(5), outlets)

    assert report.n_filled == 0
    assert report.max_fill == 0.0
    np.testing.assert_allclose(report.surface, values)


def test_a_pit_is_raised_to_its_spill_level() -> None:
    # The 0.0 at index 2 is a closed depression: its rim is the 3.0 at index 3.
    values = np.array([5.0, 4.0, 0.0, 3.0, 1.0])
    outlets = np.array([False, False, False, False, True])

    report = fill_depressions_on_graph(values, _chain(5), outlets)

    assert report.n_filled == 1
    assert report.surface[2] == pytest.approx(3.0 + DEFAULT_EPSILON_M)
    assert report.max_fill == pytest.approx(3.0 + DEFAULT_EPSILON_M)


def test_the_filled_floor_still_drains() -> None:
    # A flat floor has no steepest descent to follow, so the flood leaves a
    # slope behind it rather than a plateau.
    values = np.array([9.0, 1.0, 1.0, 1.0, 4.0, 0.0])
    outlets = np.zeros(6, dtype=bool)
    outlets[5] = True

    surface = fill_depressions_on_graph(values, _chain(6), outlets).surface

    inside = surface[1:4]
    assert np.all(np.diff(inside) < 0.0), inside


def test_every_cell_reaches_the_outlet_after_the_flood() -> None:
    rng = np.random.default_rng(4)
    n = 200
    values = np.linspace(50.0, 0.0, n) + rng.normal(0.0, 3.0, n)
    outlets = np.zeros(n, dtype=bool)
    outlets[-1] = True

    surface = fill_depressions_on_graph(values, _chain(n), outlets).surface

    # On a chain, "reaches the outlet" is "every cell is above the next one".
    assert np.all(np.diff(surface) < 0.0)


def test_an_inactive_cell_is_neither_raised_nor_crossed() -> None:
    values = np.array([5.0, np.nan, 0.0, 3.0, 1.0])
    outlets = np.zeros(5, dtype=bool)
    outlets[4] = True

    report = fill_depressions_on_graph(values, _chain(5), outlets)

    assert np.isnan(report.surface[1])
    # Cell 0 sits behind the inactive one, so the flood never reaches it.
    assert report.surface[0] == 5.0


class TestRefused:
    def test_no_outlet_at_all(self) -> None:
        with pytest.raises(ValueError, match="no finite outlet"):
            fill_depressions_on_graph(np.zeros(4), _chain(4), np.zeros(4, dtype=bool))

    def test_an_outlet_that_is_not_a_finite_cell(self) -> None:
        values = np.array([1.0, np.nan])
        outlets = np.array([False, True])
        with pytest.raises(ValueError, match="no finite outlet"):
            fill_depressions_on_graph(values, _chain(2), outlets)

    def test_a_mask_of_the_wrong_length(self) -> None:
        with pytest.raises(ValueError, match="the outlet mask holds"):
            fill_depressions_on_graph(np.zeros(4), _chain(4), np.zeros(3, dtype=bool))

    def test_an_adjacency_of_the_wrong_length(self) -> None:
        outlets = np.zeros(4, dtype=bool)
        outlets[0] = True
        with pytest.raises(ValueError, match="the adjacency holds"):
            fill_depressions_on_graph(np.zeros(4), _chain(3), outlets)
