"""The map of what the model still has to climb out of, on a known surface.

The V-shaped valley of :mod:`tests.unit.display._network_comparison_run`
descends to its outlet from every cell, so a flood over it must change nothing.
Digging one cell of the western flank below all its neighbours puts one closed
depression on it, whose spill level is written down here: the lowest neighbour
of that cell, which is not the same cell under a four-neighbour graph as under
an eight-neighbour one. The two answers are the whole point of the figure.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.depression_filling import DEFAULT_EPSILON_M
from hydromodpy.display.figure_registry import get as get_figure
from hydromodpy.display.figures._routing_surface import routing_surface_from_run
from hydromodpy.display.figures.depression_map import (
    DRAINS_LABEL,
    RAISED_LABEL,
    DepressionMap,
    depression_fill,
)

from ._network_comparison_run import NX, NY, cell, comparison_run, drawn_cells, valley_topography

PIT_CELL = cell(0, 1)
"""The cell dug below its neighbours: the middle of the western flank."""

PIT_ELEVATION_M = 10.0
"""Where it is dug to, below every neighbour it has under either graph."""

EDGE_SPILL_M = 22.0
"""Its lowest shared-edge neighbour: the cell one column toward the axis."""

NODE_SPILL_M = 20.0
"""Its lowest shared-node neighbour: the diagonal one row down, and lower."""


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def dug_valley() -> np.ndarray:
    """Return the valley with one cell of its western flank dug into a pit."""
    surface = valley_topography()
    surface[PIT_CELL] = PIT_ELEVATION_M
    return surface


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


def _labelled(ax, label: str):
    """The one collection drawn under ``label``, or None when it is empty."""
    return next((item for item in ax.collections if str(item.get_label()) == label), None)


# --------------------------------------------------------------------------- #
# what the flood changes
# --------------------------------------------------------------------------- #


def test_a_surface_that_already_drains_is_left_alone() -> None:
    fill = depression_fill(routing_surface_from_run(comparison_run()))

    assert int(fill.raised.sum()) == 0
    assert np.allclose(fill.filled, valley_topography())
    assert fill.stranded_fraction == 0.0


@pytest.mark.parametrize(
    ("diagonal", "spill_m"),
    [(False, EDGE_SPILL_M), (True, NODE_SPILL_M)],
)
def test_the_dug_cell_is_raised_onto_its_lowest_neighbour(diagonal: bool, spill_m: float) -> None:
    run = comparison_run(topography=dug_valley())

    fill = depression_fill(routing_surface_from_run(run, diagonal_neighbors=diagonal))

    assert np.flatnonzero(fill.raised).tolist() == [PIT_CELL]
    assert fill.filled[PIT_CELL] == pytest.approx(spill_m + DEFAULT_EPSILON_M)
    assert fill.fill_m[PIT_CELL] == pytest.approx(spill_m + DEFAULT_EPSILON_M - PIT_ELEVATION_M)


@pytest.mark.parametrize("diagonal", [False, True])
def test_every_cell_leaves_over_the_graph_the_flood_walked(diagonal: bool) -> None:
    # The invariant the whole conditioning exists for: once the flood is done,
    # every cell but the sealed one has a strictly lower neighbour ON THE SAME
    # adjacency. Flooded over one neighbourhood and descended over another, the
    # filled cells spill over links the descent cannot take.
    surface = routing_surface_from_run(
        comparison_run(topography=dug_valley()), diagonal_neighbors=diagonal
    )

    fill = depression_fill(surface)

    stuck = [
        index
        for index in range(surface.n_cells)
        if index != surface.outlet
        and not any(
            fill.filled[other] < fill.filled[index]
            for other in grid_neighbours(index, diagonal=diagonal)
        )
    ]
    assert stuck == [], f"cells {stuck} cannot leave the conditioned surface"
    assert fill.stranded_fraction == 0.0


def test_the_answer_moves_with_the_cell_that_was_sealed() -> None:
    # Restricting the catchment to the eastern flank moves the low point onto
    # it, and everything that used to drain past it now has to be flooded over.
    whole = depression_fill(routing_surface_from_run(comparison_run(topography=dug_valley())))
    eastern = depression_fill(
        routing_surface_from_run(comparison_run(topography=dug_valley(), catchment_columns=[3, 4]))
    )

    assert whole.surface.outlet != eastern.surface.outlet
    assert int(eastern.raised.sum()) > int(whole.raised.sum())
    assert eastern.stranded_fraction == 0.0


def test_the_outlet_falls_back_to_the_mesh_when_the_run_carries_no_catchment() -> None:
    run = comparison_run(topography=dug_valley())
    run.geographic = lambda feature: (_ for _ in ()).throw(KeyError(feature))

    surface = routing_surface_from_run(run)

    assert surface.catchment is None
    assert "the active mesh" in surface.outlet_note
    assert surface.outlet == int(np.argmin(dug_valley()))


# --------------------------------------------------------------------------- #
# what the map draws
# --------------------------------------------------------------------------- #


def test_the_map_paints_the_depth_on_the_raised_cells_alone(mpl) -> None:
    fig, ax = mpl.subplots()

    DepressionMap().render(comparison_run(topography=dug_valley()), ax)

    try:
        raised = _labelled(ax, RAISED_LABEL)
        assert raised is not None
        assert drawn_cells(raised) == [PIT_CELL]
        assert raised.get_array().tolist() == pytest.approx(
            [EDGE_SPILL_M + DEFAULT_EPSILON_M - PIT_ELEVATION_M]
        )
        drains = _labelled(ax, DRAINS_LABEL)
        assert drains is not None
        assert drawn_cells(drains) == [index for index in range(NX * NY) if index != PIT_CELL]
    finally:
        mpl.close(fig)


def test_the_map_draws_no_depth_layer_on_a_surface_that_drains(mpl) -> None:
    fig, ax = mpl.subplots()

    DepressionMap().render(comparison_run(), ax)

    try:
        assert _labelled(ax, RAISED_LABEL) is None
        assert "no closed depression" in ax.texts[0].get_text()
        assert not fig.axes[1:], "an empty scale must not print a colorbar"
    finally:
        mpl.close(fig)


def test_the_note_carries_the_count_the_depth_and_the_sealed_cell(mpl) -> None:
    fig, ax = mpl.subplots()

    DepressionMap().render(comparison_run(topography=dug_valley()), ax)

    try:
        note = ax.texts[0].get_text()
        assert "1 cell raised" in note
        assert f"up to {EDGE_SPILL_M + DEFAULT_EPSILON_M - PIT_ELEVATION_M:.2f} m" in note
        assert "sealed on outlet cell 2 at 0.00 m" in note
        assert "no diagonal" in note
        assert "0.00%" in note
    finally:
        mpl.close(fig)


def test_the_note_names_the_other_cell_when_another_one_is_sealed(mpl) -> None:
    fig, ax = mpl.subplots()

    DepressionMap().render(comparison_run(topography=dug_valley(), catchment_columns=[3, 4]), ax)

    try:
        assert "sealed on outlet cell 3 at 20.00 m" in ax.texts[0].get_text()
    finally:
        mpl.close(fig)


def test_the_outlet_is_marked_where_the_flood_was_seeded(mpl) -> None:
    fig, ax = mpl.subplots()

    DepressionMap().render(comparison_run(topography=dug_valley()), ax)

    try:
        stars = [line for line in ax.lines if line.get_marker() == "*"]
        assert len(stars) == 1
        surface = routing_surface_from_run(comparison_run(topography=dug_valley()))
        expected = surface.centroids[surface.outlet]
        assert stars[0].get_xdata()[0] == pytest.approx(expected[0])
        assert stars[0].get_ydata()[0] == pytest.approx(expected[1])
    finally:
        mpl.close(fig)


def two_pit_valley() -> np.ndarray:
    """Return the valley with a shallow pit inside and a deep one outside.

    The pit on the western flank is a metre deep, the one on the eastern
    flank twenty. With the catchment restricted to the west, the second is
    the buffered box flooding to its rim by construction and the first is the
    signal the figure exists for.
    """
    surface = valley_topography()
    surface[cell(1, 1)] = 1.0
    surface[cell(4, 1)] = 1.0
    return surface


INSIDE_FILL_M = 1.001
"""What the shallow pit needs: its spill level, plus the epsilon, minus itself."""

OUTSIDE_FILL_M = 21.001
"""What the deep one needs, twenty times more, and outside the catchment."""


def test_the_colour_scale_is_set_by_the_fills_inside_the_catchment(mpl) -> None:
    """Outside it the mesh is a box flooded to its rim by construction.

    A percentile over the whole mesh is set by those lobes, and every pit the
    note calls the real signal then collapses onto the first colour of the
    ramp: the map declares its own subject unreadable.
    """
    fig, ax = mpl.subplots()
    run = comparison_run(topography=two_pit_valley(), catchment_columns=[0, 1, 2])

    DepressionMap().render(run, ax)

    try:
        raised = _labelled(ax, RAISED_LABEL)
        assert raised is not None
        assert sorted(raised.get_array().tolist()) == pytest.approx([INSIDE_FILL_M, OUTSIDE_FILL_M])
        assert raised.get_clim()[1] == pytest.approx(INSIDE_FILL_M)
    finally:
        mpl.close(fig)


def test_the_colorbar_says_the_deepest_cells_run_past_the_scale(mpl) -> None:
    """The scale is cut, so the arrow that says so is not decoration."""
    fig, ax = mpl.subplots()
    run = comparison_run(topography=two_pit_valley(), catchment_columns=[0, 1, 2])

    DepressionMap().render(run, ax)

    try:
        assert _labelled(ax, RAISED_LABEL).colorbar.extend == "max"
    finally:
        mpl.close(fig)


def test_the_scale_falls_back_to_the_mesh_when_no_pit_is_inside(mpl) -> None:
    """An empty subset would leave the ramp with nothing to stretch over."""
    fig, ax = mpl.subplots()

    DepressionMap().render(comparison_run(topography=dug_valley(), catchment_columns=[3, 4]), ax)

    try:
        raised = _labelled(ax, RAISED_LABEL)
        assert raised is not None
        assert drawn_cells(raised), "the flood raised cells, all of them outside the catchment"
        assert raised.get_clim()[1] > DEFAULT_EPSILON_M
    finally:
        mpl.close(fig)


def test_a_banned_colormap_is_refused_by_name(mpl) -> None:
    """The global ``[display].cmap`` reaches this figure like any other."""
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="banned"):
            DepressionMap().render(comparison_run(topography=dug_valley()), ax, cmap="jet")
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


def test_it_names_what_it_needs_when_the_run_kept_no_mesh_top() -> None:
    run = comparison_run()
    run.mesh.topography = None

    reason = DepressionMap().unavailable_reason(run)

    assert reason is not None
    assert "topography" in reason


def test_a_percentile_outside_the_scale_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="clip_percentile"):
            DepressionMap().render(comparison_run(topography=dug_valley()), ax, clip_percentile=0.0)
    finally:
        mpl.close(fig)


def test_it_is_rendered_from_a_run_alone(tmp_path) -> None:
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run

    cfg = DisplayConfig(enabled=True, figures=["depression_map"], on_error="raise")

    report = render_figures_for_run(
        comparison_run(topography=dug_valley()), cfg, output_dir=tmp_path
    )

    assert report.rendered == ("depression_map",)
    assert report.skipped == ()
    assert (tmp_path / "depression_map.png").exists()


def test_it_is_skipped_by_the_gallery_rather_than_crashing(tmp_path) -> None:
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run

    cfg = DisplayConfig(enabled=True, figures=["depression_map"], on_error="raise")

    report = render_figures_for_run(
        comparison_run(topography=np.full(NX * NY, np.nan)), cfg, output_dir=tmp_path
    )

    assert report.rendered == ()
    assert [item.name for item in report.skipped] == ["depression_map"]
    assert "render failed" not in report.skipped[0].reason


def test_the_figure_is_registered_under_its_own_name() -> None:
    figure = get_figure("depression_map")

    assert isinstance(figure, DepressionMap)
    assert figure.spec.name == "depression_map"
