from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.catchment.drainage.descent import (
    Descent,
    build_descent,
    descent_basin,
    descent_graph,
)
from hydromodpy.catchment.drainage.distance import (
    build_downslope_metric,
    resolve_diagonal_neighbors,
    shared_node_adjacency,
)
from hydromodpy.catchment.drainage.filling import DEFAULT_EPSILON_M, fill_depressions_on_graph
from hydromodpy.catchment.drainage.graph import (
    accumulate_on_downhill_graph,
    cell_adjacency_from_face_connectivity,
    domain_edge_cells,
)
from tests._helpers.descent_cases import grid_centres, grid_descent, triangle_mesh
from tests._helpers.ugrid_meshes import quad_mesh

# A cell a hair above the flood level is raised and gets a receiver.
#
# The floor next to the spill is flooded to ``spill + epsilon``; the next cell
# lies ``2e-10`` m above that, below the drop the receiver graph tells from a
# flat. Left as it stands it would have no lower neighbor; the flood raises it
# like a cell below the level.

SPILL = 0.0
HAIR = SPILL + DEFAULT_EPSILON_M + 2.0e-10
N_COLS = 5
FLOOR, PROBE = N_COLS + 1, N_COLS + 2


def _strip() -> np.ndarray:
    top = np.full((3, N_COLS), 10.0)
    top[1, :] = [SPILL, SPILL, HAIR, 5.0, 10.0]
    return top


# A constant-head cell passed as a base level is a seed of D.
#
# Water leaves the model there, as it does on the domain rim. The bowl around
# such a cell drains to it as it stands; without the seed the fill would raise
# the whole bowl up to its rim.

N = 9
CENTRE = (N // 2) * N + N // 2


def _bowl() -> np.ndarray:
    rows, cols = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    return 5.0 + (rows - N // 2) ** 2 + (cols - N // 2) ** 2


# A constant-head cell keeps its steepest descent; the walks that stop there read -1.
#
# The cell sits on a slope, so the steepest descent hands it a lower neighbor.
# D sends its upslope cells into it and keeps that receiver, so an accumulation
# crosses a river CHD and the outlet still sums the domain. The drainage mover
# and the reach rectification stop where water leaves the model: they read the
# stopping receiver, -1 on the constant-head cells.

N_passes = 7
HEAD = 3 * N_passes + 3


def _slope(n: int) -> np.ndarray:
    rows, cols = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    return 10.0 + rows + 0.1 * cols


def _head_at(cell: int, n: int) -> np.ndarray:
    base_level = np.zeros(n * n, dtype=bool)
    base_level[cell] = True
    return base_level


def test_the_accumulation_crosses_the_constant_head_cell() -> None:
    descent = grid_descent(_slope(N_passes), base_level=_head_at(HEAD, N_passes))

    accumulated = accumulate_on_downhill_graph(
        descent.metric.graph, np.ones((1, N_passes * N_passes))
    )[0]

    outlets = descent.routable & (descent.receiver < 0)
    assert np.isclose(accumulated[outlets].sum(), N_passes * N_passes)
    assert accumulated[int(descent.receiver[HEAD])] > accumulated[HEAD]


# A flat beside the channel drains into the channel, not along it.
#
# A flat valley floor (1 m) is closed by a high rim, with the spill point at the
# downstream end of the channel A that runs down its middle. The plain flood
# grows the flat from the spill point, so the floor runs beside A down to the
# outlet. With A pinned, the floor rises twice as fast away from the channel as
# along it and each floor cell joins A within its lateral distance.

N_ROWS, N_COLS_flat, AXIS = 15, 9, 4
FLOOR_flat, RIM = 1.0, 10.0


def _quad_valley() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    top = np.full((N_ROWS, N_COLS_flat), FLOOR_flat)
    top[0, :] = top[-1, :] = top[:, 0] = top[:, -1] = RIM
    top[0, AXIS] = 0.0
    channel = np.zeros(N_ROWS * N_COLS_flat, dtype=bool)
    pins = np.full(N_ROWS * N_COLS_flat, -1, dtype=int)
    for row in range(N_ROWS - 1):
        channel[row * N_COLS_flat + AXIS] = True
        if row > 0:
            pins[row * N_COLS_flat + AXIS] = (row - 1) * N_COLS_flat + AXIS
    return top, channel, pins


def _triangle_valley() -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[np.ndarray, ...]]:
    vertices, connectivity, centroids = triangle_mesh(N_ROWS, N_COLS_flat)
    n_cells = connectivity.shape[0]
    rim = domain_edge_cells(connectivity, np.ones(n_cells, dtype=bool))
    top = np.where(rim, RIM, FLOOR_flat)
    channel = np.zeros(n_cells, dtype=bool)
    pins = np.full(n_cells, -1, dtype=int)
    # Square s holds the triangles 2s (on its lower edge) and 2s + 1 (on its upper edge).
    for row in range(N_ROWS - 1):
        square = row * N_COLS_flat + AXIS
        channel[[2 * square, 2 * square + 1]] = True
        pins[2 * square + 1] = 2 * square
        if row > 0:
            pins[2 * square] = 2 * (square - N_COLS_flat) + 1
    top[2 * AXIS] = 0.0
    return top, channel, pins, (vertices, connectivity, centroids)


def _worst_run_beside(descent: Descent, centres: np.ndarray, channel: np.ndarray) -> float:
    """Largest distance a floor cell runs down-valley beyond its lateral distance to A."""
    floor = descent.routable & ~channel & (descent.surface < 0.5 * (FLOOR_flat + RIM))
    worst = -np.inf
    for start in np.flatnonzero(floor).tolist():
        cell = start
        while not channel[cell] and descent.receiver[cell] >= 0:
            cell = int(descent.receiver[cell])
        assert channel[cell], f"floor cell {start} never reaches the channel"
        lateral = abs(centres[start, 0] - (AXIS + 0.5))
        worst = max(worst, centres[start, 1] - centres[cell, 1] - lateral)
    return worst


# A lake is crossed by D, never a sink of it: the cells below its dam drain downstream.
#
# The valley runs west along row 3. From the east: the upstream river, a lake of
# four cells, a dam with a carved corridor (5 m), a pit just below the dam (3 m),
# a sill (6 m), and the river down to the outlet. The pit's lowest pass is the
# corridor, back into the lake. Seeded as a sink, the lake would capture the pit
# over the corridor. Traversed, it fills to its spill level and drains through
# the corridor, the pit and the sill to the outlet, and so does the pit.

N_ROWS_lake = 7
N_COLS_lake = 14
AXIS_lake = 3
VALLEY = {
    0: 0.0,
    1: 1.0,
    2: 2.0,
    3: 6.0,  # the sill below the pit
    4: 3.0,  # the pit just below the dam
    5: 5.0,  # the carved corridor through the dam
    6: 4.0,  # the lake, cols 6 to 9
    7: 3.0,
    8: 3.5,
    9: 4.5,
    10: 8.0,
    11: 9.0,
    12: 10.0,
    13: 11.0,
}


LAKE_COLS = (6, 7, 8, 9)
SILL, PIT, CORRIDOR = (
    AXIS_lake * N_COLS_lake + 3,
    AXIS_lake * N_COLS_lake + 4,
    AXIS_lake * N_COLS_lake + 5,
)


def _valley() -> tuple[np.ndarray, np.ndarray]:
    rows, _ = np.meshgrid(np.arange(N_ROWS_lake), np.arange(N_COLS_lake), indexing="ij")
    top = 10.0 + 3.0 * np.abs(rows - AXIS_lake)
    for col, value in VALLEY.items():
        top[AXIS_lake, col] = value
    lake_of = np.full(N_ROWS_lake * N_COLS_lake, -1, dtype=int)
    lake_of[[AXIS_lake * N_COLS_lake + col for col in LAKE_COLS]] = 0
    return top, lake_of


def _walk(receiver: np.ndarray, start: int) -> list[int]:
    path = [start]
    while receiver[path[-1]] >= 0:
        path.append(int(receiver[path[-1]]))
    return path


# A pinned channel cell drains to its pin, even where T climbs along the channel.
#
# The channel A runs down column 3 to the outlet at row 0. At row 4 it crosses a
# sill of T (4 m) while the valley side at (4, 2) offers a gap at 2.5 m. The
# steepest descent leaves the channel through the gap; the pins hold it on A, and
# the copy is raised along the channel above the sill so each pin stays lower
# than its donor.

N_ROWS_chain, N_COLS_chain, AXIS_chain = 12, 7, 3
SILL_ROW, SILL_chain, GAP = 4, 4.0, 2.5


def _cell(row: int, col: int) -> int:
    return row * N_COLS_chain + col


def _valley_chain() -> np.ndarray:
    rows, cols = np.meshgrid(np.arange(N_ROWS_chain), np.arange(N_COLS_chain), indexing="ij")
    top = 5.0 + 2.0 * np.abs(cols - AXIS_chain)
    top[:, AXIS_chain] = 1.0 + 0.1 * np.arange(N_ROWS_chain)
    top[0, :] = top[-1, :] = 20.0
    top[0, AXIS_chain] = 0.0
    top[SILL_ROW, AXIS_chain] = SILL_chain
    top[SILL_ROW, AXIS_chain - 1] = GAP
    return top


def _channel_and_pins() -> tuple[np.ndarray, np.ndarray]:
    channel = np.zeros(N_ROWS_chain * N_COLS_chain, dtype=bool)
    pins = np.full(N_ROWS_chain * N_COLS_chain, -1, dtype=int)
    for row in range(N_ROWS_chain - 1):
        channel[_cell(row, AXIS_chain)] = True
        if row > 0:
            pins[_cell(row, AXIS_chain)] = _cell(row - 1, AXIS_chain)
    return channel, pins


# D is stored as receivers and a filled surface, and the graph comes back from them.
#
# A reader routes on D without the mesh geometry: ordering the cells by descending
# filled surface puts every donor before its receiver, because every link of D
# strictly descends on that surface.

PIT_TOP = np.array(
    [
        [9.0, 8.0, 7.0, 8.0],
        [8.0, 5.0, 4.0, 7.0],
        [7.0, 4.0, 1.0, 6.0],
        [6.0, 5.0, 4.0, 5.0],
    ]
)


"""A bowl: the middle cell is a pit of the top, deeper than its whole ring."""


def test_receivers_and_surface_of_different_sizes_are_refused() -> None:
    with pytest.raises(ValueError, match="receivers"):
        descent_graph(np.zeros(4, dtype=int), np.zeros(5))


# A pin that is out of range, leaves the channel, lands on a lake or cycles is refused.
#
# The error names a cell, so the caller can find the faulty projection of A.

N_pin = 6


def _top() -> np.ndarray:
    rows, cols = np.meshgrid(np.arange(N_pin), np.arange(N_pin), indexing="ij")
    return 10.0 + rows + cols


def _cell_pin(row: int, col: int) -> int:
    return row * N_pin + col


def _channel(*cells: int) -> np.ndarray:
    mask = np.zeros(N_pin * N_pin, dtype=bool)
    mask[list(cells)] = True
    return mask


def _pins(**links: int) -> np.ndarray:
    pins = np.full(N_pin * N_pin, -1, dtype=int)
    for donor, target in links.items():
        pins[int(donor.removeprefix("c"))] = target
    return pins


A, B, C = _cell_pin(2, 2), _cell_pin(2, 3), _cell_pin(3, 3)
LAKE = np.where(np.arange(N_pin * N_pin) == _cell_pin(3, 2), 0, -1)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (
            {
                "channel": _channel(A, B, C),
                "pinned_receiver": _pins(**{f"c{A}": B, f"c{B}": C, f"c{C}": A}),
            },
            "cycle through cell",
        ),
        (
            {"channel": _channel(A, B), "pinned_receiver": _pins(**{f"c{A}": A})},
            f"cycle through cell {A}",
        ),
        (
            {
                "channel": _channel(A),
                "pinned_receiver": _pins(**{f"c{A}": _cell_pin(3, 2)}),
                "lake_of": LAKE,
            },
            f"cell {A} is pinned onto a lake cell",
        ),
        (
            {"channel": _channel(A, _cell_pin(3, 2)), "lake_of": LAKE},
            f"cell {_cell_pin(3, 2)} is a channel cell inside a lake",
        ),
        (
            {"channel": _channel(A), "pinned_receiver": _pins(**{f"c{A}": N_pin * N_pin})},
            f"cell {A} is pinned to {N_pin * N_pin}",
        ),
        (
            {"channel": _channel(B), "pinned_receiver": _pins(**{f"c{A}": B})},
            f"cell {A} is pinned but is not a channel cell",
        ),
        (
            {"channel": _channel(A), "pinned_receiver": _pins(**{f"c{A}": B})},
            f"cell {A} is pinned onto a cell outside the channel",
        ),
        (
            {"pinned_receiver": _pins(**{f"c{A}": B})},
            "pinned_receiver needs channel",
        ),
    ],
    ids=[
        "cycle",
        "self-pin",
        "onto-lake",
        "channel-in-lake",
        "out-of-range",
        "non-channel-donor",
        "non-channel-target",
        "no-channel",
    ],
)
def test_the_pin_is_refused(options: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        grid_descent(_top(), **options)


# Every routable cell that is not a seed has a receiver, and no chain cycles.
#
# This is the contract the consumers rely on: the reach rectification turns a -1
# into an outlet reach and the drainage mover into a plain drain. On D a -1 only
# happens on a seed, on a quad grid and on a mesh without diagonals alike, and
# around a hole of non-routable cells, whose rim is a seed too.

N_drain = 12


def _rough_top(n_cells: int) -> np.ndarray:
    return np.random.default_rng(7).uniform(0.0, 20.0, n_cells)


def _with_a_hole(n_cells: int) -> np.ndarray:
    routable = np.ones(n_cells, dtype=bool)
    routable[n_cells // 2 : n_cells // 2 + 3] = False
    return routable


# The basin of D follows the receivers, so it crosses a river CHD and stops at a CHD sink.
#
# A constant-head cell on a slope keeps its steepest descent: the basin of the
# outlet goes on upstream of it. A constant-head cell at the bottom of a bowl has
# no lower neighbor: it is a sink, and the cells draining into it stay outside
# the basin. The basin never reads the stopping receiver, which ends every walk
# at a constant-head cell.

HEAD_river = 4 * N + 4
OUTLET = 0


def _basin_at_the_outlet(descent):
    return descent_basin(
        descent, cell_area_m2=np.ones(N * N), near=tuple(grid_centres(N, N)[OUTLET])
    )


# ``Descent.basin`` is exactly the set of cells whose receiver chain passes the outlet.

N_through = 15


def _chain_passes(receiver: np.ndarray, start: int, outlet: int) -> bool:
    cell = start
    while cell >= 0:
        if cell == outlet:
            return True
        cell = int(receiver[cell])
    return False


def test_an_off_graph_outlet_is_refused() -> None:
    routable = np.ones(N_through * N_through, dtype=bool)
    routable[0] = False
    descent = grid_descent(np.zeros((N_through, N_through)), routable=routable)

    with pytest.raises(ValueError, match="off the descended graph"):
        descent.basin(0)


# D of a domain that is the catchment is flooded from its outlet, not from its rim.
#
# Seeded at the outlet, the basin of the outlet is every cell of its connected
# part of the graph: no rim cell keeps a share of the domain for itself. A part
# detached from the outlet keeps its rim as seeds, or the flood would never reach
# it. An outlet off the graph is refused. Without an outlet D is the rim flood.

N_whole = 12


def _rough_top_whole(seed: int = 5) -> np.ndarray:
    rows, cols = np.meshgrid(np.arange(N_whole), np.arange(N_whole), indexing="ij")
    noise = np.random.default_rng(seed).uniform(0.0, 3.0, (N_whole, N_whole))
    return 10.0 + 0.5 * rows + 0.3 * cols + noise


def _centre(cell: int) -> tuple[float, float]:
    return tuple(grid_centres(N_whole, N_whole)[cell])


def test_an_outlet_off_the_graph_is_refused() -> None:
    routable = np.ones(N_whole * N_whole, dtype=bool)
    routable[0] = False

    with pytest.raises(ValueError, match="outlet cell 0 is off the descended graph"):
        grid_descent(_rough_top_whole(), routable=routable, outlet=0)


def test_on_triangles_the_outlet_drains_its_whole_part() -> None:
    vertices, connectivity, centroids = triangle_mesh(N_whole, N_whole)
    top = np.repeat(_rough_top_whole().reshape(-1), 2)
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
    descent = grid_descent(_rough_top_whole())
    areas = np.ones(N_whole * N_whole)
    west = (np.arange(N_whole * N_whole) % N_whole) < 6

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
    descent = grid_descent(_rough_top_whole())

    with pytest.raises(ValueError, match="adjacency of D"):
        descent_basin(
            descent.without_adjacency(), cell_area_m2=np.ones(N_whole * N_whole), near=_centre(0)
        )
    with pytest.raises(ValueError, match="cell_area_m2 holds 3 cells"):
        descent_basin(descent, cell_area_m2=np.ones(3))


# D raises an interior pit on its own copy; the model top is left as it was.
#
# The copy is a routing computation (principle P2). The solver, the drain
# elevations and the reach tops read the top T, so a descent that wrote its fill
# back would change the ground the model is built on.

N_copy = 6
PIT_copy = (3, 3)


def _sloping_top_with_a_pit() -> np.ndarray:
    rows, cols = np.meshgrid(np.arange(N_copy), np.arange(N_copy), indexing="ij")
    top = 10.0 + rows + cols
    top[PIT_copy] = 5.0
    return top


# D flags the cells it raised, and a model keeps it without its adjacency.
#
# The flow direction map draws the raised cells from that flag: comparing D's
# surface with a top that went through a text file would mark cells D never
# touched. The adjacency sets are the heavy part of D and nothing reads them
# after the build, so the copy a model keeps drops them and nothing else.


# D descends by shared nodes on a quad grid and by shared faces elsewhere.
#
# On quads a diagonal neighbor is taken when its drop per meter is the steepest,
# the D8 rule the stream criterion uses. A triangle shares nodes with about a
# dozen others and no direction there is a diagonal, so the graph falls back to
# shared faces, and the fill and the receivers both use that one graph.

N_diag = 5
CENTRE_diag = 2 * N_diag + 2
DIAGONAL = 1 * N_diag + 1


def _centre_with_a_steep_diagonal() -> np.ndarray:
    top = np.full((N_diag, N_diag), 9.5)
    top[0, :] = top[-1, :] = top[:, 0] = top[:, -1] = 1.0
    top[2, 2] = 10.0
    top[1, 2] = top[3, 2] = top[2, 1] = top[2, 3] = 9.0
    # A drop of 3 over sqrt(2) beats a drop of 1 over 1.
    top[1, 1] = 7.0
    return top


# The report counts a lake flooded to its spill apart from a pit filled outside lakes.
#
# On a plane rising to the north-east, one pit lies 2 m below its lowest
# neighbor and a lake of four cells lies 6 m below its own. ``n_raised`` and
# ``max_raise_m`` see the pit alone, ``n_lake_flooded`` and ``max_lake_flood_m``
# the lake alone.

N_report = 8
PIT_report = (2, 5)
LAKE_report = ((5, 5), (5, 6), (6, 5), (6, 6))


def _plane() -> tuple[np.ndarray, np.ndarray]:
    rows, cols = np.meshgrid(np.arange(N_report), np.arange(N_report), indexing="ij")
    top = 10.0 + rows + cols
    top[PIT_report] = 13.0  # lowest neighbor (1, 4) at 15
    lake_of = np.full(N_report * N_report, -1, dtype=int)
    for cell in LAKE_report:
        top[cell] = 12.0  # lowest neighbor (4, 4) at 18
        lake_of[cell[0] * N_report + cell[1]] = 0
    return top, lake_of


def test_the_pit_is_counted_as_raised() -> None:
    top, lake_of = _plane()

    descent = grid_descent(top, lake_of=lake_of)

    assert descent.n_raised == 1
    assert descent.max_raise_m == pytest.approx(2.0, abs=0.01)


def test_the_lake_is_counted_as_flooded() -> None:
    top, lake_of = _plane()

    descent = grid_descent(top, lake_of=lake_of)

    assert descent.n_lake_flooded == len(LAKE_report)
    assert descent.max_lake_flood_m == pytest.approx(6.0, abs=0.01)


# Without pins nor channel, D is the criterion's flood and steepest descent.
#
# The reference is the pipeline D ran before it held its own flood: the stream
# criterion's fill on the descended graph, then the steepest-descent receivers on
# the filled copy. Copy, receivers and raised count must match on every mesh the
# descent tests use.

N_plain = 12


def _reference(top, connectivity, vertices, centroids, routable, diagonal):
    n_cells = top.size
    on_graph = routable & np.isfinite(top)
    use = resolve_diagonal_neighbors(connectivity, n_cells=n_cells, requested=diagonal)
    adjacency = (
        shared_node_adjacency(connectivity, n_cells=n_cells)
        if use
        else cell_adjacency_from_face_connectivity(connectivity, n_cells=n_cells)
    )
    seeds = domain_edge_cells(connectivity, on_graph)
    fill = fill_depressions_on_graph(np.where(on_graph, top, np.nan), adjacency, seeds)
    metric = build_downslope_metric(
        fill.surface,
        connectivity,
        vertices=vertices,
        centroids=centroids,
        inactive_mask=~on_graph,
        diagonal_neighbors=use,
        adjacency=adjacency,
    )
    return fill, metric.graph.downstream


def _quad_case(seed: int, hole: bool, flat_share: float):
    vertices, connectivity = quad_mesh(N_plain, N_plain)
    rng = np.random.default_rng(seed)
    top = rng.uniform(0.0, 20.0, N_plain * N_plain)
    # Rounded plateaus give the flood ties to break, as a flat DEM does.
    plateau = rng.random(N_plain * N_plain) < flat_share
    top[plateau] = np.round(top[plateau] / 5.0) * 5.0
    routable = np.ones(N_plain * N_plain, dtype=bool)
    if hole:
        routable[N_plain * N_plain // 2 : N_plain * N_plain // 2 + 3] = False
    return top, connectivity, vertices, grid_centres(N_plain, N_plain), routable


def _triangle_case(seed: int):
    vertices, connectivity, centroids = triangle_mesh(N_plain, N_plain)
    top = np.random.default_rng(seed).uniform(0.0, 20.0, connectivity.shape[0])
    return top, connectivity, vertices, centroids, np.ones(top.size, dtype=bool)
