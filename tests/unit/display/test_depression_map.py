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

Digging one interior cell of the western flank below its neighbors adds the
only real depression on the page. Its spill level is written down here: the
lowest neighbor of that cell, which is not the same cell under a
four-neighbor graph as under an eight-neighbor one.

Two variants of that surface carry the rest of the answers. A second and deeper
pit dug in the eastern valley puts one depression inside the catchment and one
outside it, which is what a color scale is read against. A catchment stopping
one row short of the southern edge makes the dug cell its low point, so the
outlet is interior and sits in a depression itself: on the Nancon it does, and
a flood that seeded the outlet reported that depression away.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.catchment.drainage.filling import DEFAULT_EPSILON_M
from hydromodpy.display.figures.depression_map import (
    DEPRESSIONS,
    INACTIVE_LABEL,
    READINGS,
    UNREACHABLE,
    DepressionMap,
    reading_for,
)
from hydromodpy.display.style import relative_luminance
from hydromodpy.results.derive.stream_network.depressions import depression_fill
from hydromodpy.results.derive.stream_network.routing_surface import routing_surface_from_run

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
"""Where the dug cell sits: below every neighbor, above the outlet at 0 m."""

EDGE_SPILL_M = 4.0
"""Its lowest shared-edge neighbor: the valley floor one column to the east."""

NODE_SPILL_M = 2.0
"""Its lowest shared-node neighbor: the diagonal one row down, and lower."""

EAST_PIT_COLUMN = 6
EAST_PIT_ROW = 2
EAST_PIT_ELEVATION_M = -5.0
EAST_PIT_SPILL_M = 3.0
"""A second, deeper pit dug in the eastern valley, outside the catchment.

Its lowest shared-edge neighbor is the valley floor one row south, at 3 m,
so it needs eight meters of fill against the three the western pit needs.
Two pits of known and different depth, one in the catchment and one out of it,
is what tells a color scale stretched over the mesh from one stretched over
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
    """Return the neighbors of one grid cell, straight from the grid shape.

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


# --------------------------------------------------------------------------- #
# what the two floods are, and what separates them
# --------------------------------------------------------------------------- #


def test_a_surface_that_gets_out_everywhere_holds_no_depression() -> None:
    fill = depression_fill(routing_surface_from_run(basin_run()))

    assert int(fill.closed.raised.sum()) == 0
    assert np.allclose(fill.closed.filled, two_basin_topography())


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

    # The spill heights are written for the four-neighbor graph: under D8 the
    # pit spills over a diagonal saddle, lower than its cardinal one.
    DepressionMap().render(basin_run(topography=pitted_topography()), ax, diagonal_neighbors=False)

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


def test_the_map_draws_no_depth_layer_on_a_surface_that_holds_no_pit(mpl) -> None:
    fig, ax = mpl.subplots()

    DepressionMap().render(basin_run(), ax)

    try:
        assert _labelled(ax, READINGS[DEPRESSIONS].raised_label) is None
        assert "no closed depression" in legend_note(ax)
        assert not fig.axes[1:], "an empty scale must not print a colorbar"
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


# --------------------------------------------------------------------------- #
# the color scale
# --------------------------------------------------------------------------- #


def test_the_unreachable_scale_is_set_by_the_fills_inside_the_catchment(mpl) -> None:
    """Outside it the mesh holds whole basins flooded over a ridge.

    A percentile over the whole mesh is set by those, and the meter-scale pit
    the note calls the real signal collapses onto the first color of the ramp:
    the map declares its own subject unreadable. Measured on the Nancon, that
    ceiling is 31.21 m against 3.97 m, with two thirds of the drawn cells above
    it.
    """
    fig, ax = mpl.subplots()

    DepressionMap().render(
        basin_run(topography=pitted_topography()),
        ax,
        shows=UNREACHABLE,
        diagonal_neighbors=False,
    )

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
    # The background is a flat gray and the depth runs light to dark, so the
    # shallow end has to print lighter than the background and the deep end
    # darker. Sat inside that range, a fill would vanish on a grayscale print.
    from matplotlib.colors import to_rgb

    from hydromodpy.display.figures.depression_map import _FILL_CMAP, _UNRAISED_FACE

    ramp = mpl.get_cmap(_FILL_CMAP)
    background = relative_luminance(_UNRAISED_FACE)

    assert relative_luminance(ramp(0.0)) - background > 0.1
    assert background - relative_luminance(ramp(1.0)) > 0.1
    assert to_rgb(_UNRAISED_FACE)[0] == pytest.approx(to_rgb(_UNRAISED_FACE)[2]), (
        "the background must stay neutral so it cannot be read as a depth"
    )


# --------------------------------------------------------------------------- #
# what the figure refuses, and how it is asked for
# --------------------------------------------------------------------------- #


def test_a_reading_that_does_not_exist_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="shows must be one of"):
        reading_for("pits")


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
