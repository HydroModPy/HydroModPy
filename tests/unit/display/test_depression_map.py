"""What the depression map says, on a mesh whose two answers are known apart.

The bug this file guards against is a map that showed one thing and named it
another, so the fixture is built to hold the two things at once and keep them
far apart.

The mesh is a ``9 x 5`` grid carrying TWO parallel V-valleys, one closing on
column 2 and one on column 6, separated by a ridge on column 4. Every cell
descends to the southern edge of the grid, so the surface has no closed
depression anywhere: a priority flood seeded on every escape must change
nothing. The delineated catchment covers the western valley alone, so its
outlet is the southern end of column 2, and a flood seeded on that ONE cell has
to raise the whole eastern valley over the ridge before a distance to it
exists. Fifteen of the forty-five cells, a third of the mesh, none of them in a
depression.

Digging one interior cell of the western flank below its neighbours adds the
only real depression on the page. Its spill level is written down here: the
lowest neighbour of that cell, which is not the same cell under a
four-neighbour graph as under an eight-neighbour one.

Two variants of that surface carry the rest of the answers. A second and deeper
pit dug in the eastern valley puts one depression inside the catchment and one
outside it, which is what a colour scale is read against. A catchment stopping
one row short of the southern edge makes the dug cell its low point, so the
outlet is interior and sits in a depression itself: on the Nancon it does, and
a flood that seeded the outlet reported that depression away.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.depression_filling import DEFAULT_EPSILON_M
from hydromodpy.display.figure_registry import get as get_figure
from hydromodpy.display.figures._routing_surface import routing_surface_from_run
from hydromodpy.display.figures.depression_map import (
    DEPRESSIONS,
    INACTIVE_LABEL,
    READINGS,
    UNREACHABLE,
    DepressionMap,
    depression_fill,
    reading_for,
)

from ._network_comparison_run import comparison_run, legend_labels, legend_note

NX = 9
NY = 5
CELL_M = 100.0
CRS = "EPSG:2154"

COLUMN_PROFILE_M: tuple[float, ...] = (40.0, 20.0, 0.0, 20.0, 40.0, 21.0, 1.0, 21.0, 41.0)
"""Two valley floors, on columns 2 and 6, with a ridge between them."""

ROW_DROP_M = 2.0
"""Drop from one row to the next toward the southern edge, ten times smaller."""

WESTERN_COLUMNS = (0, 1, 2, 3, 4)
EASTERN_COLUMNS = (5, 6, 7)
"""The eastern valley, up to but not including its own outer ridge on column 8.

Column 8 stands at 41 m, above the 40 m ridge the flood has to cross to get
there, so it is not raised. That is the boundary of the answer, and writing it
down is what makes the count below a construction rather than a recording.
"""

PIT_COLUMN = 1
PIT_ROW = 2
PIT_ELEVATION_M = 1.0
"""Where the dug cell sits: below every neighbour, above the outlet at 0 m."""

EDGE_SPILL_M = 4.0
"""Its lowest shared-edge neighbour: the valley floor one column to the east."""

NODE_SPILL_M = 2.0
"""Its lowest shared-node neighbour: the diagonal one row down, and lower."""

EAST_PIT_COLUMN = 6
EAST_PIT_ROW = 2
EAST_PIT_ELEVATION_M = -5.0
EAST_PIT_SPILL_M = 3.0
"""A second, deeper pit dug in the eastern valley, outside the catchment.

Its lowest shared-edge neighbour is the valley floor one row south, at 3 m,
so it needs eight metres of fill against the three the western pit needs.
Two pits of known and different depth, one in the catchment and one out of it,
is what tells a colour scale stretched over the mesh from one stretched over
the catchment.
"""

INTERIOR_CATCHMENT_ROWS = (1, 2, 3, 4)
"""A catchment stopping one row short of the southern edge of the mesh.

Its low point is then the dug cell, which is interior to the mesh and sits in
the only real depression on the page: the Nancon case in miniature, where the
catchment closes on a cell water does not leave the domain through.
"""


def cell(column: int, row: int) -> int:
    """Return the index of one grid cell, row-major from the southern row."""
    return row * NX + column


PIT_CELL = cell(PIT_COLUMN, PIT_ROW)
EAST_PIT_CELL = cell(EAST_PIT_COLUMN, EAST_PIT_ROW)
OUTLET_CELL = cell(2, 0)
EASTERN_CELLS = sorted(cell(column, row) for row in range(NY) for column in EASTERN_COLUMNS)


def two_basin_topography() -> np.ndarray:
    """Return the two-valley surface, which gets out of the domain everywhere."""
    return np.asarray(
        [COLUMN_PROFILE_M[column] + ROW_DROP_M * row for row in range(NY) for column in range(NX)],
        dtype=float,
    )


def pitted_topography() -> np.ndarray:
    """Return the same surface with one interior cell dug into a real pit."""
    surface = two_basin_topography()
    surface[PIT_CELL] = PIT_ELEVATION_M
    return surface


def two_pit_topography() -> np.ndarray:
    """Return the same surface with a second, deeper pit outside the catchment."""
    surface = pitted_topography()
    surface[EAST_PIT_CELL] = EAST_PIT_ELEVATION_M
    return surface


def basin_run(
    *,
    topography: np.ndarray | None = None,
    catchment_columns: Sequence[int] = WESTERN_COLUMNS,
    catchment_rows: Sequence[int] = tuple(range(NY)),
    name: str = "two-basin",
) -> SimpleNamespace:
    """Return a run carrying the two-valley mesh and one delineated catchment."""
    import geopandas as gpd
    from shapely.geometry import box

    vertices = np.asarray(
        [[column * CELL_M, row * CELL_M, 0.0] for row in range(NY + 1) for column in range(NX + 1)],
        dtype=float,
    )
    faces = np.asarray(
        [
            [
                row * (NX + 1) + column,
                row * (NX + 1) + column + 1,
                (row + 1) * (NX + 1) + column + 1,
                (row + 1) * (NX + 1) + column,
            ]
            for row in range(NY)
            for column in range(NX)
        ],
        dtype=int,
    )
    surface = two_basin_topography() if topography is None else np.asarray(topography, dtype=float)
    mesh = SimpleNamespace(
        vertices=vertices,
        face_node_connectivity=faces,
        topography=surface,
        crs=CRS,
    )
    watershed = gpd.GeoDataFrame(
        geometry=[
            box(
                min(catchment_columns) * CELL_M,
                min(catchment_rows) * CELL_M,
                (max(catchment_columns) + 1) * CELL_M,
                (max(catchment_rows) + 1) * CELL_M,
            )
        ],
        crs=CRS,
    )
    fields: dict[str, np.ndarray] = {"topography": surface}
    return SimpleNamespace(
        sim_id="sim-two-basin",
        name=name,
        mesh=mesh,
        has_field=lambda variable, **_: variable in fields,
        field=lambda variable, **_: fields[variable],
        geographic=lambda feature: watershed,
    )


def grid_neighbours(index: int, *, diagonal: bool) -> list[int]:
    """Return the neighbours of one grid cell, straight from the grid shape.

    Written from the geometry of the mesh rather than read back from the
    adjacency the figure used: a check against the builder it checks proves
    nothing about the flood.
    """
    column, row = index % NX, index // NX
    steps = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    if diagonal:
        steps += [(-1, -1), (-1, 1), (1, -1), (1, 1)]
    return [
        cell(column + across, row + up)
        for across, up in steps
        if 0 <= column + across < NX and 0 <= row + up < NY
    ]


def drawn_cells(collection) -> list[int]:
    """Return the grid cells one drawn collection covers, in index order."""
    cells = []
    for path in collection.get_paths():
        corners = path.vertices
        column = int(round(float(corners[:, 0].mean()) / CELL_M - 0.5))
        row = int(round(float(corners[:, 1].mean()) / CELL_M - 0.5))
        cells.append(cell(column, row))
    return sorted(cells)


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _labelled(ax, label: str):
    """The one collection drawn under ``label``, or None when it is empty."""
    return next((item for item in ax.collections if str(item.get_label()) == label), None)


# --------------------------------------------------------------------------- #
# the mesh the tests are written on
# --------------------------------------------------------------------------- #


def test_the_fixture_holds_two_basins_and_one_outlet() -> None:
    # Everything below reads as a property only if this holds: the eastern
    # valley closes on a cell that is not the outlet, and the outlet is the
    # unique low point of the delineated catchment.
    surface = routing_surface_from_run(basin_run())

    assert surface.outlet == OUTLET_CELL
    assert surface.topography[OUTLET_CELL] == pytest.approx(0.0)
    eastern_floor = cell(6, 0)
    assert surface.topography[eastern_floor] < surface.topography[cell(5, 0)]
    assert not surface.catchment[eastern_floor]


def test_the_escapes_are_the_edge_of_the_mesh_and_nothing_else() -> None:
    surface = routing_surface_from_run(basin_run())

    escapes = surface.escape_mask()
    perimeter = [
        index for index in range(NX * NY) if index % NX in (0, NX - 1) or index // NX in (0, NY - 1)
    ]
    assert np.flatnonzero(surface.domain_edge).tolist() == perimeter
    assert np.flatnonzero(escapes).tolist() == perimeter
    assert not escapes[PIT_CELL], "an interior cell is no escape"


def test_an_interior_outlet_is_no_escape_and_keeps_the_depression_it_sits_in() -> None:
    # The Nancon in miniature: there the catchment closes on cell 49905, at
    # 106.42 m and interior to the mesh, which needs 4.07 m of fill before it
    # spills out of the domain. Seeding the outlet erased that depression and
    # fourteen more from a map titled "closed depressions of the surface".
    surface = routing_surface_from_run(
        basin_run(topography=pitted_topography(), catchment_rows=INTERIOR_CATCHMENT_ROWS)
    )

    assert surface.outlet == PIT_CELL
    assert not surface.domain_edge[PIT_CELL]
    assert not surface.escape_mask()[PIT_CELL]
    assert np.flatnonzero(depression_fill(surface).closed.raised).tolist() == [PIT_CELL]


def test_an_inactive_column_moves_the_edge_of_the_domain(mpl) -> None:
    # The edge is where the ACTIVE mesh stops, not where the array does: a
    # buffered box with a nodata margin would otherwise seed its flood outside
    # the model and call every real depression an escape.
    values = pitted_topography()
    values[[cell(NX - 1, row) for row in range(NY)]] = np.nan
    run = basin_run(topography=values)

    surface = routing_surface_from_run(run)

    assert not surface.active[cell(NX - 1, 0)]
    assert surface.domain_edge[cell(NX - 2, 2)], "the outermost active column is now the edge"
    assert not surface.domain_edge[cell(NX - 3, 2)]
    assert np.flatnonzero(depression_fill(surface).closed.raised).tolist() == [PIT_CELL]

    fig, ax = mpl.subplots()
    try:
        DepressionMap().render(run, ax)
        assert f"{INACTIVE_LABEL} ({NY} cells)" in legend_labels(ax)
    finally:
        mpl.close(fig)


def test_the_edge_of_the_mesh_does_not_move_with_the_neighbourhood() -> None:
    # A diagonal link is a routing choice; the boundary of the domain is a
    # geometric fact about the mesh, and reading it off the neighbour count
    # would make the two move together.
    edges = routing_surface_from_run(basin_run()).domain_edge
    nodes = routing_surface_from_run(basin_run(), diagonal_neighbors=True).domain_edge

    assert np.array_equal(edges, nodes)


# --------------------------------------------------------------------------- #
# what the two floods are, and what separates them
# --------------------------------------------------------------------------- #


def test_a_surface_that_gets_out_everywhere_holds_no_depression() -> None:
    fill = depression_fill(routing_surface_from_run(basin_run()))

    assert int(fill.closed.raised.sum()) == 0
    assert np.allclose(fill.closed.filled, two_basin_topography())


def test_the_criterions_flood_raises_a_whole_basin_that_is_no_depression() -> None:
    # The defect, in miniature. The same surface the flood above left alone is
    # flooded over a third of its cells by the criterion's own flood, because
    # that one is seeded on a single outlet and the eastern valley closes
    # somewhere else. Those cells drain; they just do not drain here.
    fill = depression_fill(routing_surface_from_run(basin_run()))

    assert np.flatnonzero(fill.to_outlet.raised).tolist() == EASTERN_CELLS
    assert np.flatnonzero(fill.cut_off).tolist() == EASTERN_CELLS
    assert int(fill.pitted_and_unreachable.sum()) == 0
    assert fill.to_outlet.deepest_m > 30.0, "flooded over the ridge, not into a pit"


@pytest.mark.parametrize(
    ("diagonal", "spill_m"),
    [(False, EDGE_SPILL_M), (True, NODE_SPILL_M)],
)
def test_the_dug_cell_is_raised_onto_its_lowest_neighbour(diagonal: bool, spill_m: float) -> None:
    run = basin_run(topography=pitted_topography())

    fill = depression_fill(routing_surface_from_run(run, diagonal_neighbors=diagonal))

    assert np.flatnonzero(fill.closed.raised).tolist() == [PIT_CELL]
    assert fill.closed.filled[PIT_CELL] == pytest.approx(spill_m + DEFAULT_EPSILON_M)
    assert fill.closed.fill_m[PIT_CELL] == pytest.approx(
        spill_m + DEFAULT_EPSILON_M - PIT_ELEVATION_M
    )


def test_the_pit_is_the_only_cell_the_two_floods_agree_on() -> None:
    fill = depression_fill(routing_surface_from_run(basin_run(topography=pitted_topography())))

    assert np.all(fill.closed.raised <= fill.to_outlet.raised), (
        "the outlet is on the edge here, so the closed flood is seeded on strictly more "
        "cells, and more escapes can only lower a spill level"
    )
    assert np.flatnonzero(fill.pitted_and_unreachable).tolist() == [PIT_CELL]
    assert np.flatnonzero(fill.cut_off).tolist() == EASTERN_CELLS


@pytest.mark.parametrize(
    ("support", "sealed"),
    [
        ({"catchment_columns": EASTERN_COLUMNS}, cell(6, 0)),
        ({"catchment_rows": INTERIOR_CATCHMENT_ROWS}, PIT_CELL),
    ],
)
def test_the_depressions_do_not_move_when_another_cell_is_sealed(
    support: dict, sealed: int
) -> None:
    # Sealing the eastern valley moves the criterion's flood onto the western
    # one; sealing the dug cell moves it onto everything that cannot descend
    # into it. The closed depressions do not move in either case, because they
    # are a property of the surface and not of the cell someone chose to seal.
    # The second case is the one that discriminates: the sealed cell is the pit
    # itself, so a flood seeded on it reports no depression at all.
    western = depression_fill(routing_surface_from_run(basin_run(topography=pitted_topography())))
    elsewhere = depression_fill(
        routing_surface_from_run(basin_run(topography=pitted_topography(), **support))
    )

    assert elsewhere.surface.outlet == sealed
    assert western.surface.outlet != elsewhere.surface.outlet
    assert np.array_equal(western.closed.raised, elsewhere.closed.raised)
    assert np.flatnonzero(elsewhere.closed.raised).tolist() == [PIT_CELL]
    assert not np.array_equal(western.to_outlet.raised, elsewhere.to_outlet.raised)
    assert elsewhere.stranded_fraction == 0.0


@pytest.mark.parametrize("diagonal", [False, True])
def test_every_cell_leaves_the_surface_over_the_graph_the_flood_walked(diagonal: bool) -> None:
    # The invariant the whole conditioning exists for: once a flood is done,
    # every cell it was not seeded on has a strictly lower neighbour ON THE
    # SAME adjacency. Flooded over one neighbourhood and descended over
    # another, the filled cells spill over links the descent cannot take.
    surface = routing_surface_from_run(
        basin_run(topography=pitted_topography()), diagonal_neighbors=diagonal
    )

    fill = depression_fill(surface)

    for flood in (fill.closed, fill.to_outlet):
        stuck = [
            index
            for index in range(surface.n_cells)
            if not flood.seeds[index]
            and not any(
                flood.filled[other] < flood.filled[index]
                for other in grid_neighbours(index, diagonal=diagonal)
            )
        ]
        assert stuck == [], f"cells {stuck} cannot leave the conditioned surface"
    assert fill.stranded_fraction == 0.0


def test_the_outlet_falls_back_to_the_mesh_when_the_run_carries_no_catchment() -> None:
    run = basin_run(topography=pitted_topography())
    run.geographic = lambda feature: (_ for _ in ()).throw(KeyError(feature))

    surface = routing_surface_from_run(run)

    assert surface.catchment is None
    assert "the active mesh" in surface.outlet_note
    assert surface.outlet == int(np.argmin(pitted_topography()))


# --------------------------------------------------------------------------- #
# what the map draws
# --------------------------------------------------------------------------- #


def test_the_default_map_paints_the_depression_and_not_the_other_basin(mpl) -> None:
    # The regression this figure was rewritten for: the eastern valley used to
    # be painted as raised, on a map titled "depressions", and it holds none.
    fig, ax = mpl.subplots()

    DepressionMap().render(basin_run(topography=pitted_topography()), ax)

    try:
        raised = _labelled(ax, READINGS[DEPRESSIONS].raised_label)
        assert raised is not None
        assert drawn_cells(raised) == [PIT_CELL]
        assert raised.get_array().tolist() == pytest.approx(
            [EDGE_SPILL_M + DEFAULT_EPSILON_M - PIT_ELEVATION_M]
        )
        drains = _labelled(ax, READINGS[DEPRESSIONS].drains_label)
        assert set(EASTERN_CELLS) <= set(drawn_cells(drains))
    finally:
        mpl.close(fig)


def test_the_option_paints_what_the_criterions_flood_has_to_raise(mpl) -> None:
    fig, ax = mpl.subplots()

    DepressionMap().render(basin_run(topography=pitted_topography()), ax, shows=UNREACHABLE)

    try:
        raised = _labelled(ax, READINGS[UNREACHABLE].raised_label)
        assert raised is not None
        assert drawn_cells(raised) == sorted([PIT_CELL, *EASTERN_CELLS])
        assert _labelled(ax, READINGS[DEPRESSIONS].raised_label) is None
    finally:
        mpl.close(fig)


@pytest.mark.parametrize("shows", [DEPRESSIONS, UNREACHABLE])
def test_the_title_says_which_of_the_two_questions_is_on_the_page(mpl, shows: str) -> None:
    fig, ax = mpl.subplots()

    DepressionMap().render(basin_run(topography=pitted_topography()), ax, shows=shows)

    try:
        assert READINGS[shows].title in ax.get_title()
        assert (
            READINGS[shows].scale_label
            == _labelled(ax, READINGS[shows].raised_label).colorbar.ax.get_ylabel()
        )
    finally:
        mpl.close(fig)


def test_the_map_draws_no_depth_layer_on_a_surface_that_holds_no_pit(mpl) -> None:
    fig, ax = mpl.subplots()

    DepressionMap().render(basin_run(), ax)

    try:
        assert _labelled(ax, READINGS[DEPRESSIONS].raised_label) is None
        assert "no closed depression" in legend_note(ax)
        assert not fig.axes[1:], "an empty scale must not print a colorbar"
    finally:
        mpl.close(fig)


def test_the_legend_carries_the_size_of_what_is_drawn(mpl) -> None:
    fig, ax = mpl.subplots()

    DepressionMap().render(basin_run(topography=pitted_topography()), ax)

    try:
        labels = legend_labels(ax)
        assert f"{READINGS[DEPRESSIONS].raised_label} (1 cell)" in labels
        assert any(READINGS[DEPRESSIONS].outlet_label == label for label in labels)
    finally:
        mpl.close(fig)


def test_the_key_and_the_note_sit_under_the_map_and_not_on_it(mpl) -> None:
    # The subject of this map covers five per cent of the page, so nothing it
    # is read with may be printed on it. Measured on nancon_diagnostic.v2 at
    # the shipped page size: the key in the corner and the note at the foot
    # covered 11 568 mesh cells, the outlet and the southern half of the
    # catchment among them.
    fig, ax = mpl.subplots()

    DepressionMap().render(basin_run(topography=pitted_topography()), ax)

    try:
        assert ax.get_legend() is None
        assert list(ax.texts) == []
        assert fig.legends, "the key belongs to the figure, which can reserve room for it"
    finally:
        mpl.close(fig)


def test_the_outlet_is_marked_where_the_flood_was_seeded(mpl) -> None:
    fig, ax = mpl.subplots()

    DepressionMap().render(basin_run(topography=pitted_topography()), ax)

    try:
        stars = [line for line in ax.lines if line.get_marker() == "*"]
        assert len(stars) == 1
        surface = routing_surface_from_run(basin_run(topography=pitted_topography()))
        expected = surface.centroids[surface.outlet]
        assert stars[0].get_xdata()[0] == pytest.approx(expected[0])
        assert stars[0].get_ydata()[0] == pytest.approx(expected[1])
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the note, which is what keeps the two readings apart
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("shows", "depressions"),
    [
        (DEPRESSIONS, "1 cell in a closed depression"),
        (UNREACHABLE, "in a closed depression: 1 of the 1"),
    ],
)
def test_the_note_carries_both_counts_whichever_reading_is_drawn(
    mpl, shows: str, depressions: str
) -> None:
    # Whichever set is painted, a reader must be able to read the other one off
    # the page: taking one for the other is the whole defect. One cell is in a
    # depression here, fifteen more only fail to reach this outlet.
    fig, ax = mpl.subplots()

    DepressionMap().render(basin_run(topography=pitted_topography()), ax, shows=shows)

    try:
        note = legend_note(ax)
        assert depressions in note
        assert f"{len(EASTERN_CELLS)} " in note
        assert "outlet" in note
    finally:
        mpl.close(fig)


def test_the_depression_note_sends_the_reader_to_the_other_reading(mpl) -> None:
    fig, ax = mpl.subplots()

    DepressionMap().render(basin_run(topography=pitted_topography()), ax)

    try:
        note = legend_note(ax)
        assert f'shows="{UNREACHABLE}"' in note
        assert "1 cell in a closed depression" in note
        assert f"out elsewhere but not to this outlet: {len(EASTERN_CELLS)} cells" in note
        assert "24 cells on the edge of the active mesh, the outlet excluded" in note
        assert "no diagonal" in note
    finally:
        mpl.close(fig)


def test_the_unreachable_note_names_the_cell_the_answer_depends_on(mpl) -> None:
    fig, ax = mpl.subplots()

    DepressionMap().render(basin_run(topography=pitted_topography()), ax, shows=UNREACHABLE)

    try:
        note = legend_note(ax)
        assert "16 cells cannot reach the outlet" in note
        assert (
            "of them, in a closed depression: 1 of the 1 the mesh holds; "
            f"out elsewhere: {len(EASTERN_CELLS)} cells"
        ) in note
        assert f"sealed on outlet cell {OUTLET_CELL} at 0.00 m" in note
        assert "0.00%" in note
    finally:
        mpl.close(fig)


def test_the_unreachable_note_reconciles_its_count_with_the_other_reading(mpl) -> None:
    # The sealed cell is the pit itself here, so it is in a closed depression
    # and reaches the outlet, being it. The two readings then count depressions
    # differently, and the note has to say which of the two it is counting: on
    # the Nancon that is 3008 of the 3023 the surface holds.
    fig, ax = mpl.subplots()
    run = basin_run(topography=pitted_topography(), catchment_rows=INTERIOR_CATCHMENT_ROWS)

    DepressionMap().render(run, ax, shows=UNREACHABLE)

    try:
        assert "in a closed depression: 0 of the 1 the mesh holds" in legend_note(ax)
    finally:
        mpl.close(fig)


@pytest.mark.parametrize(
    ("shows", "expected"),
    [(DEPRESSIONS, "24 cells on the edge of the active mesh"), (UNREACHABLE, "the active mesh")],
)
def test_the_note_names_the_mesh_when_the_run_carries_no_catchment(
    mpl, shows: str, expected: str
) -> None:
    fig, ax = mpl.subplots()
    run = basin_run(topography=pitted_topography())
    run.geographic = lambda feature: (_ for _ in ()).throw(KeyError(feature))

    DepressionMap().render(run, ax, shows=shows)

    try:
        note = legend_note(ax)
        assert expected in note
        assert "catchment" not in note, "no catchment was delineated, so none may be named"
    finally:
        mpl.close(fig)


def test_the_note_names_the_other_cell_when_another_one_is_sealed(mpl) -> None:
    fig, ax = mpl.subplots()

    run = basin_run(topography=pitted_topography(), catchment_columns=EASTERN_COLUMNS)
    DepressionMap().render(run, ax, shows=UNREACHABLE)

    try:
        assert f"sealed on outlet cell {cell(6, 0)} at 1.00 m" in legend_note(ax)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the colour scale
# --------------------------------------------------------------------------- #


def test_the_unreachable_scale_is_set_by_the_fills_inside_the_catchment(mpl) -> None:
    """Outside it the mesh holds whole basins flooded over a ridge.

    A percentile over the whole mesh is set by those, and the metre-scale pit
    the note calls the real signal collapses onto the first colour of the ramp:
    the map declares its own subject unreadable. Measured on the Nancon, that
    ceiling is 31.21 m against 3.97 m, with two thirds of the drawn cells above
    it.
    """
    fig, ax = mpl.subplots()

    DepressionMap().render(basin_run(topography=pitted_topography()), ax, shows=UNREACHABLE)

    try:
        raised = _labelled(ax, READINGS[UNREACHABLE].raised_label)
        assert max(raised.get_array().tolist()) > 30.0
        assert raised.get_clim()[1] == pytest.approx(
            EDGE_SPILL_M + DEFAULT_EPSILON_M - PIT_ELEVATION_M
        )
        assert raised.colorbar.extend == "max", "the scale is cut, so the arrow is not decoration"
    finally:
        mpl.close(fig)


def test_the_depression_scale_is_stretched_over_the_pits_of_the_whole_mesh(mpl) -> None:
    """The closed flood raises pits, never a basin, so no lobe can set the scale.

    Restricting it to the catchment would leave every pit outside the catchment
    saturated at the top of the ramp while the map still calls them depressions
    and prints their depth on the bar.
    """
    fig, ax = mpl.subplots()

    run = basin_run(topography=two_pit_topography())
    DepressionMap().render(run, ax, clip_percentile=100.0)

    try:
        raised = _labelled(ax, READINGS[DEPRESSIONS].raised_label)
        assert drawn_cells(raised) == sorted([PIT_CELL, EAST_PIT_CELL])
        assert raised.get_clim()[1] == pytest.approx(
            EAST_PIT_SPILL_M + DEFAULT_EPSILON_M - EAST_PIT_ELEVATION_M
        )
        assert raised.colorbar.extend == "neither", "nothing is cut, so no arrow is drawn"
    finally:
        mpl.close(fig)


def test_the_unreachable_scale_falls_back_to_the_mesh_when_no_pit_is_inside(mpl) -> None:
    """An empty subset would leave the ramp with nothing to stretch over."""
    fig, ax = mpl.subplots()

    run = basin_run(topography=pitted_topography(), catchment_columns=EASTERN_COLUMNS)
    fill = depression_fill(routing_surface_from_run(run))
    assert not fill.surface.within_catchment(fill.to_outlet.raised).any(), (
        "the eastern valley all reaches its own outlet, so the subset is empty"
    )

    DepressionMap().render(run, ax, shows=UNREACHABLE, clip_percentile=100.0)

    try:
        raised = _labelled(ax, READINGS[UNREACHABLE].raised_label)
        assert PIT_CELL in drawn_cells(raised), "the only pit, and it is outside the catchment"
        assert raised.get_clim()[1] == pytest.approx(max(raised.get_array().tolist()))
    finally:
        mpl.close(fig)


def test_a_banned_colormap_is_refused_by_name(mpl) -> None:
    """The global ``[display].cmap`` reaches this figure like any other."""
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="banned"):
            DepressionMap().render(basin_run(topography=pitted_topography()), ax, cmap="jet")
    finally:
        mpl.close(fig)


def test_a_raised_cell_stays_separable_from_a_cell_that_drains(mpl) -> None:
    # The background is a flat grey and the depth runs light to dark, so the
    # shallow end has to print lighter than the background and the deep end
    # darker. Sat inside that range, a fill would vanish on a greyscale print.
    from matplotlib.colors import to_rgb

    from hydromodpy.display.figures.depression_map import _FILL_CMAP, _UNRAISED_FACE

    ramp = mpl.get_cmap(_FILL_CMAP)
    background = _relative_luminance(_UNRAISED_FACE)

    assert _relative_luminance(ramp(0.0)) - background > 0.1
    assert background - _relative_luminance(ramp(1.0)) > 0.1
    assert to_rgb(_UNRAISED_FACE)[0] == pytest.approx(to_rgb(_UNRAISED_FACE)[2]), (
        "the background must stay neutral so it cannot be read as a depth"
    )


def _relative_luminance(color) -> float:
    """Perceived brightness of one colour, the quantity a greyscale print keeps."""
    from matplotlib.colors import to_rgb

    channels = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in to_rgb(color)
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


# --------------------------------------------------------------------------- #
# what the figure refuses, and how it is asked for
# --------------------------------------------------------------------------- #


def test_a_reading_that_does_not_exist_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="shows must be one of"):
        reading_for("pits")


def test_the_reading_is_asked_for_from_a_toml(tmp_path) -> None:
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run

    cfg = DisplayConfig(
        enabled=True,
        figures=["depression_map"],
        overrides={"depression_map": {"shows": UNREACHABLE}},
        on_error="raise",
    )

    report = render_figures_for_run(
        basin_run(topography=pitted_topography()), cfg, output_dir=tmp_path
    )

    assert report.rendered == ("depression_map",)
    assert (tmp_path / "depression_map.png").exists()


def test_it_names_what_it_needs_when_the_run_kept_no_mesh_top() -> None:
    run = comparison_run()
    run.mesh.topography = None

    reason = DepressionMap().unavailable_reason(run)

    assert reason is not None
    assert "topography" in reason
    assert reason.endswith("route on")


def test_a_percentile_outside_the_scale_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="clip_percentile"):
            DepressionMap().render(
                basin_run(topography=pitted_topography()), ax, clip_percentile=0.0
            )
    finally:
        mpl.close(fig)


def test_it_is_rendered_from_a_run_alone(tmp_path) -> None:
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run

    cfg = DisplayConfig(enabled=True, figures=["depression_map"], on_error="raise")

    report = render_figures_for_run(
        basin_run(topography=pitted_topography()), cfg, output_dir=tmp_path
    )

    assert report.rendered == ("depression_map",)
    assert report.skipped == ()
    assert (tmp_path / "depression_map.png").exists()


def test_it_is_skipped_by_the_gallery_rather_than_crashing(tmp_path) -> None:
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run

    cfg = DisplayConfig(enabled=True, figures=["depression_map"], on_error="raise")

    report = render_figures_for_run(
        basin_run(topography=np.full(NX * NY, np.nan)), cfg, output_dir=tmp_path
    )

    assert report.rendered == ()
    assert [item.name for item in report.skipped] == ["depression_map"]
    assert "render failed" not in report.skipped[0].reason


def test_the_figure_is_registered_under_its_own_name() -> None:
    figure = get_figure("depression_map")

    assert isinstance(figure, DepressionMap)
    assert figure.spec.name == "depression_map"
