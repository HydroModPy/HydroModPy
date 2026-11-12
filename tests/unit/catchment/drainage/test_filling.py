"""Raising the closed depressions of a surface so every path reaches an outlet.

A downslope distance is a length along a flow path, and a flow path only exists
once the depressions are resolved. Conditioning a raster before delineation does
not carry over: it is pit-free on its own grid, and read at the centroids of a
mesh it grows new pits. The surface has to be conditioned on the graph the
distances are measured on.
"""

from __future__ import annotations

import heapq

import numpy as np
import pytest

from hydromodpy.catchment.drainage.filling import (
    DEFAULT_EPSILON_M,
    fill_depressions_on_graph,
    priority_flood,
)


def _chain(n: int) -> list[set[int]]:
    """Neighbors of a one-dimensional chain of cells."""
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


REFUSALS = [
    pytest.param(np.zeros(4), 4, np.zeros(4, bool), "no finite outlet", id="no outlet"),
    pytest.param(
        np.array([1.0, np.nan]), 2, np.array([False, True]), "no finite outlet", id="nan outlet"
    ),
    pytest.param(np.zeros(4), 4, np.zeros(3, bool), "the outlet mask holds", id="short mask"),
    pytest.param(
        np.zeros(4),
        3,
        np.array([True, False, False, False]),
        "the adjacency holds",
        id="short adjacency",
    ),
]


@pytest.mark.parametrize(("values", "n_adjacent", "outlets", "message"), REFUSALS)
def test_refusals(values, n_adjacent, outlets, message) -> None:
    with pytest.raises(ValueError, match=message):
        fill_depressions_on_graph(values, _chain(n_adjacent), outlets)


def _grid_adjacency(n_rows: int, n_cols: int) -> list[set[int]]:
    """Eight neighbors of each cell of a rows x cols grid."""
    out: list[set[int]] = []
    for row in range(n_rows):
        for col in range(n_cols):
            near = {
                (r, c)
                for r in range(row - 1, row + 2)
                for c in range(col - 1, col + 2)
                if 0 <= r < n_rows and 0 <= c < n_cols and (r, c) != (row, col)
            }
            out.append({r * n_cols + c for r, c in near})
    return out


def _reference_fill(
    values: np.ndarray, adjacency: list[set[int]], seeds: np.ndarray, epsilon: float
):
    """The flood without pins, written out, the way the fill ran before it shared its loop."""
    surface = values.copy()
    finite = np.isfinite(surface)
    visited = np.zeros(surface.size, dtype=bool)
    frontier: list[tuple[float, int]] = []
    for cell in np.flatnonzero(seeds & finite):
        visited[int(cell)] = True
        heapq.heappush(frontier, (surface[int(cell)], int(cell)))
    while frontier:
        level, cell = heapq.heappop(frontier)
        for neighbour in adjacency[cell]:
            if visited[neighbour] or not finite[neighbour]:
                continue
            visited[neighbour] = True
            if surface[neighbour] <= level:
                surface[neighbour] = level + epsilon
            heapq.heappush(frontier, (surface[neighbour], neighbour))
    return surface


# Cells 0..3, a square: 0-1, 0-2, 1-3, 2-3. The seed is cell 3.
SQUARE = [{1, 2}, {0, 3}, {0, 3}, {1, 2}]
LOW = np.array([0.0, 0.0, 0.0, 10.0])
SEED_3 = np.array([False, False, False, True])

FLOOD_CASES = (
    (
        "one step for every cell",
        {"step": 0.5},
        [11.0, 10.5, 10.5, 10.0],
    ),
    (
        "a step per cell is read at the cell that is raised",
        {"step": np.array([0.1, 0.2, 0.3, 0.4])},
        [10.3, 10.2, 10.3, 10.0],
    ),
    (
        "a pinned cell is entered from its pin only, so it sits above the pin",
        {"step": np.array([0.1, 0.2, 0.3, 0.4]), "pin": np.array([-1, 0, -1, -1])},
        [10.4, 10.6, 10.3, 10.0],
    ),
)


@pytest.mark.parametrize(
    ("case", "kwargs", "expected"), FLOOD_CASES, ids=[case for case, _, _ in FLOOD_CASES]
)
def test_the_flood_raises_each_cell_onto_its_rim_by_its_step(
    case: str, kwargs: dict, expected: list[float]
) -> None:
    del case
    surface, raised = priority_flood(LOW, SQUARE, SEED_3, **kwargs)

    np.testing.assert_allclose(surface, expected, rtol=0.0, atol=1e-12)
    assert raised.tolist() == [True, True, True, False]


def test_a_cell_within_the_tolerance_above_the_level_is_raised_like_one_below_it() -> None:
    values = np.array([5.0, 1.0 + 1e-10, 1.0])
    seeds = np.array([False, False, True])

    kept, kept_mask = priority_flood(values, _chain(3), seeds, step=0.1)
    raised, raised_mask = priority_flood(values, _chain(3), seeds, step=0.1, tolerance=1e-9)

    assert np.array_equal(kept, values)
    assert not kept_mask.any()
    np.testing.assert_allclose(raised, [5.0, 1.1, 1.0], atol=1e-12)
    assert raised_mask.tolist() == [False, True, False]


def test_a_cell_the_seeds_never_reach_is_left_alone_or_refused_on_request() -> None:
    values = np.array([3.0, 2.0, 1.0, 7.0])
    adjacency = [{1}, {0, 2}, {1}, set()]
    seeds = np.array([False, False, True, False])

    surface, _ = priority_flood(values, adjacency, seeds, step=0.1)
    assert surface[3] == 7.0

    with pytest.raises(ValueError, match=r"1 cell\(s\) are never reached from a seed \(first: 3\)"):
        priority_flood(values, adjacency, seeds, step=0.1, every_cell=True)


def test_a_pinned_cell_whose_pin_is_cut_off_from_the_seeds_is_refused() -> None:
    # Cell 0 is reachable only through cell 1, which is entered from cell 0 alone.
    values = np.array([1.0, 2.0, 3.0, 0.0])
    adjacency = [{1}, {0, 2}, {1, 3}, {2}]
    seeds = np.array([False, False, False, True])
    pin = np.array([-1, 0, -1, -1])

    with pytest.raises(ValueError, match="never reached from a seed"):
        priority_flood(values, adjacency, seeds, step=0.1, pin=pin, every_cell=True)
