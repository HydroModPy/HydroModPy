"""The map of where every cell sends its water, on a grid whose answer is known.

The runs come from :mod:`tests.unit.display._network_comparison_run`. Two
surfaces are used: the V-shaped valley of that module, whose flanks descend to
the axis and whose axis descends to the outlet, and a plane tilted toward the
south-west corner, where the steepest descent is a diagonal and can therefore
only be taken when the graph carries diagonals. Both partitions are written
down here before the receiver graph is ever built.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.display.figures.flow_direction_map import (
    NO_RECEIVER_LABEL,
    OCTANT_NAMES,
    RAISED_LABEL,
    FlowDirectionMap,
)

from ._network_comparison_run import (
    AXIS_COLUMN,
    CELL_M,
    NX,
    NY,
    cell,
    comparison_run,
    drawn_cells,
    valley_topography,
)

SOUTH_WEST_STEP_M = 10.0
"""Drop per column and per row of the tilted plane, so a diagonal is steepest."""


def tilted_plane() -> np.ndarray:
    """Return a plane falling toward the south-west corner of the grid.

    One column and one row are the same drop, so the diagonal step falls twice
    as much over ``sqrt(2)`` times the distance: it is the steepest descent of
    every interior cell, and no four-neighbor graph can take it.
    """
    return np.asarray(
        [(column + row) * SOUTH_WEST_STEP_M for row in range(NY) for column in range(NX)],
        dtype=float,
    )


def _octant_cells(ax, name: str) -> list[int]:
    """The grid cells drawn under one bearing, empty when none took it."""
    for collection in ax.collections:
        if str(collection.get_label()) == name:
            return drawn_cells(collection)
    return []


def _labelled(ax, label: str):
    """The one collection drawn under ``label``, or None when it is empty."""
    return next(
        (item for item in ax.collections if str(item.get_label()) == label),
        None,
    )


def _compass(ax):
    """The inset axes carrying the compass rose."""
    from matplotlib.axes import Axes

    roses = [child for child in ax.get_children() if isinstance(child, Axes)]
    assert len(roses) == 1, "the figure draws exactly one compass rose"
    return roses[0]


def _quiver(ax):
    """The arrow layer, or None when the caller asked for none."""
    from matplotlib.quiver import Quiver

    return next((item for item in ax.collections if isinstance(item, Quiver)), None)


# --------------------------------------------------------------------------- #
# what the map says
# --------------------------------------------------------------------------- #


def test_the_outlet_is_marked_on_the_lowest_cell(mpl) -> None:
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(), ax)

    try:
        stars = [line for line in ax.lines if line.get_marker() == "*"]
        assert len(stars) == 1
        assert stars[0].get_xdata()[0] == pytest.approx((AXIS_COLUMN + 0.5) * CELL_M)
        assert stars[0].get_ydata()[0] == pytest.approx(0.5 * CELL_M)
        assert "outlet cell 2 at 0.00 m" in ax.texts[0].get_text()
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the neighborhood the graph was built on
# --------------------------------------------------------------------------- #


def test_no_diagonal_bearing_appears_without_a_diagonal_graph(mpl) -> None:
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(
        comparison_run(topography=tilted_plane(), descent_diagonals=False), ax
    )

    try:
        for name in ("NE", "NW", "SE", "SW"):
            assert _octant_cells(ax, name) == [], (
                f"{name} is not a shared edge, so a four-neighbour graph cannot take it"
            )
        assert "no diagonal" in ax.texts[0].get_text()
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# where the descent departs from the model top
# --------------------------------------------------------------------------- #


def valley_with_a_pit() -> np.ndarray:
    """Return the valley with the cell west of the axis dug below the axis itself."""
    top = valley_topography()
    top[cell(1, 1)] = -50.0
    return top


def test_a_pit_of_the_top_drains_on_the_descent_and_is_marked_as_raised(mpl) -> None:
    """The steepest descent of the top dies in the pit, D fills it and routes on."""
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(topography=valley_with_a_pit()), ax)

    try:
        assert _octant_cells(ax, NO_RECEIVER_LABEL) == [cell(AXIS_COLUMN, 0)], (
            "on D the only cell without receiver is the outlet of the valley, never a pit"
        )
        raised = _labelled(ax, RAISED_LABEL)
        assert raised is not None
        assert len(raised.get_offsets()) == 1
        note = ax.texts[0].get_text()
        assert "the descent raised 1 cell on its copy" in note
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the legend a reader tells north-east from south-west with
# --------------------------------------------------------------------------- #


def test_the_compass_puts_each_color_at_the_bearing_it_means(mpl) -> None:
    from matplotlib.patches import Wedge

    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(topography=tilted_plane()), ax)

    try:
        wedges = [item for item in _compass(ax).patches if isinstance(item, Wedge)]
        assert len(wedges) == len(OCTANT_NAMES), "every bearing keeps a wedge, empty or not"
        for name in ("SW", "W", "S"):
            painted = _labelled(ax, name)
            assert painted is not None, f"{name} is drawn on this surface"
            face = tuple(np.asarray(painted.get_facecolor()).reshape(-1)[:4])
            matching = [
                item
                for item in wedges
                if tuple(np.asarray(item.get_facecolor()).reshape(-1)[:4]) == pytest.approx(face)
            ]
            assert len(matching) == 1, f"one wedge carries the color the map used for {name}"
            centre = (matching[0].theta1 + matching[0].theta2) / 2.0
            assert centre == pytest.approx(45.0 * OCTANT_NAMES.index(name)), (
                f"the {name} color must sit at the {name} bearing of the rose"
            )
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the colors the map is read by
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# the arrows
# --------------------------------------------------------------------------- #


def test_the_arrows_are_a_subsample_the_caller_switches_off(mpl) -> None:
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(), ax, arrow_bins=0)

    try:
        assert _quiver(ax) is None
        assert "arrows" not in ax.texts[0].get_text()
    finally:
        mpl.close(fig)


def test_a_negative_subsample_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="arrow_bins"):
            FlowDirectionMap().render(comparison_run(), ax, arrow_bins=-1)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# what the figure refuses, and how it is asked for
# --------------------------------------------------------------------------- #


def test_it_names_what_it_needs_when_the_run_kept_no_mesh_top() -> None:
    run = comparison_run()
    run.mesh.topography = None

    reason = FlowDirectionMap().unavailable_reason(run)

    assert reason is not None
    assert "topography" in reason


def test_it_names_what_it_needs_when_the_mesh_top_is_all_nodata() -> None:
    run = comparison_run(topography=np.full(NX * NY, np.nan))

    reason = FlowDirectionMap().unavailable_reason(run)

    assert reason is not None
    assert "elevation" in reason


def test_a_surface_with_no_active_cell_is_skipped_by_the_gallery(tmp_path) -> None:
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run

    cfg = DisplayConfig(enabled=True, figures=["flow_direction_map"], on_error="raise")

    report = render_figures_for_run(
        comparison_run(topography=np.full(NX * NY, np.nan)), cfg, output_dir=tmp_path
    )

    assert report.rendered == ()
    assert [item.name for item in report.skipped] == ["flow_direction_map"]
    assert "render failed" not in report.skipped[0].reason


def test_a_toml_override_reaches_the_figure(tmp_path) -> None:
    # The declarative path is the whole point: a knob set under
    # [display.overrides.flow_direction_map] must arrive at render(), and the
    # cheapest proof is a value render() is known to refuse.
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run

    cfg = DisplayConfig(
        enabled=True,
        figures=["flow_direction_map"],
        overrides={"flow_direction_map": {"arrow_bins": -1}},
        on_error="raise",
    )

    with pytest.raises(ValueError, match="arrow_bins"):
        render_figures_for_run(comparison_run(), cfg, output_dir=tmp_path)


def test_the_valley_used_here_is_the_one_the_module_publishes() -> None:
    # The expectations above are written against that surface; a change to it
    # has to break this test rather than quietly rewrite the partition.
    surface = valley_topography()

    assert surface[cell(AXIS_COLUMN, 0)] == surface.min()
    assert surface[cell(0, 0)] > surface[cell(1, 0)] > surface[cell(AXIS_COLUMN, 0)]
