"""D of a domain that is the catchment is flooded from its outlet, not from its rim.

Seeded at the outlet, the basin of the outlet is every cell of its connected
part of the graph: no rim cell keeps a share of the domain for itself. A part
detached from the outlet keeps its rim as seeds, or the flood would never reach
it. An outlet off the graph is refused. Without an outlet D is the rim flood.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.descent import build_descent, descent_basin
from tests._helpers.descent_cases import grid_centres, grid_descent, triangle_mesh

N = 12


def _rough_top(seed: int = 5) -> np.ndarray:
    rows, cols = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    noise = np.random.default_rng(seed).uniform(0.0, 3.0, (N, N))
    return 10.0 + 0.5 * rows + 0.3 * cols + noise


def _centre(cell: int) -> tuple[float, float]:
    return tuple(grid_centres(N, N)[cell])


def test_seeded_at_the_outlet_the_basin_is_the_whole_domain() -> None:
    top = _rough_top()
    rim = grid_descent(top)
    rim_basin = descent_basin(rim, cell_area_m2=np.ones(N * N), near=_centre(0))
    assert not rim_basin.mask.all()

    seeded = grid_descent(top, outlet=rim_basin.outlet)
    basin = descent_basin(
        seeded, cell_area_m2=np.ones(N * N), near=_centre(0), seeded_at_outlet=True
    )

    assert basin.outlet == rim_basin.outlet
    assert basin.seeded_at_outlet
    assert basin.mask.all()
    assert np.flatnonzero(seeded.base_level).tolist() == [rim_basin.outlet]


def test_a_detached_part_is_seeded_on_its_rim_and_stays_outside() -> None:
    routable = np.ones(N * N, dtype=bool)
    routable[np.arange(N) * N + 6] = False  # column 6 cuts the grid in two
    west = (np.arange(N * N) % N) < 6

    descent = grid_descent(_rough_top(), routable=routable, outlet=0)
    basin = descent_basin(descent, cell_area_m2=np.ones(N * N), near=_centre(0))

    np.testing.assert_array_equal(basin.mask, west)
    east = routable & ~west
    assert descent.base_level[east].any()
    assert np.flatnonzero(descent.base_level & west).tolist() == [0]


def test_an_outlet_off_the_graph_is_refused() -> None:
    routable = np.ones(N * N, dtype=bool)
    routable[0] = False

    with pytest.raises(ValueError, match="outlet cell 0 is off the descended graph"):
        grid_descent(_rough_top(), routable=routable, outlet=0)


def test_on_triangles_the_outlet_drains_its_whole_part() -> None:
    vertices, connectivity, centroids = triangle_mesh(N, N)
    top = np.repeat(_rough_top().reshape(-1), 2)
    options = {
        "vertices": vertices,
        "centroids": centroids,
        "routable": np.ones(top.size, dtype=bool),
    }
    rim = build_descent(top, connectivity, **options)
    outlet = int(np.argmin(top))

    seeded = build_descent(top, connectivity, outlet=outlet, **options)
    basin = descent_basin(
        seeded, cell_area_m2=np.full(top.size, 0.5), near=tuple(centroids[outlet])
    )

    assert rim.basin(outlet).sum() < top.size  # the rim keeps most of the domain
    assert basin.outlet == outlet
    assert basin.mask.all()
    assert basin.area_m2 == pytest.approx(0.5 * top.size)


def test_the_rule_says_how_the_outlet_was_found() -> None:
    descent = grid_descent(_rough_top())
    areas = np.ones(N * N)
    west = (np.arange(N * N) % N) < 6

    near = descent_basin(descent, cell_area_m2=areas, near=_centre(0))
    within = descent_basin(descent, cell_area_m2=areas, within=west)
    largest = descent_basin(descent, cell_area_m2=areas)

    assert (near.rule, within.rule, largest.rule) == (
        "near_point",
        "within_polygon",
        "largest_basin",
    )
    assert near.is_catchment and within.is_catchment and not largest.is_catchment
    assert west[within.outlet]


def test_snapping_needs_the_adjacency_and_matching_areas() -> None:
    descent = grid_descent(_rough_top())

    with pytest.raises(ValueError, match="adjacency of D"):
        descent_basin(descent.without_adjacency(), cell_area_m2=np.ones(N * N), near=_centre(0))
    with pytest.raises(ValueError, match="cell_area_m2 holds 3 cells"):
        descent_basin(descent, cell_area_m2=np.ones(3))
