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
    INACTIVE_LABEL,
    NO_RECEIVER_LABEL,
    OCTANT_NAMES,
    FlowDirectionMap,
    octant_colors,
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
from ._render_helpers import relative_luminance

SOUTH_WEST_STEP_M = 10.0
"""Drop per column and per row of the tilted plane, so a diagonal is steepest."""


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def tilted_plane() -> np.ndarray:
    """Return a plane falling toward the south-west corner of the grid.

    One column and one row are the same drop, so the diagonal step falls twice
    as much over ``sqrt(2)`` times the distance: it is the steepest descent of
    every interior cell, and no four-neighbour graph can take it.
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


def test_the_flanks_drain_to_the_axis_and_the_axis_drains_to_the_outlet(mpl) -> None:
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(), ax)

    try:
        west_of_axis = [cell(column, row) for row in range(NY) for column in (0, 1)]
        east_of_axis = [cell(column, row) for row in range(NY) for column in (3, 4)]
        assert _octant_cells(ax, "E") == sorted(west_of_axis)
        assert _octant_cells(ax, "W") == sorted(east_of_axis)
        assert _octant_cells(ax, "S") == [cell(AXIS_COLUMN, 1), cell(AXIS_COLUMN, 2)]
        assert _octant_cells(ax, "N") == []
    finally:
        mpl.close(fig)


def test_the_cell_with_no_receiver_is_drawn_as_a_dead_end(mpl) -> None:
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(), ax)

    try:
        # The low point of the valley is the only cell nothing is lower than.
        assert _octant_cells(ax, NO_RECEIVER_LABEL) == [cell(AXIS_COLUMN, 0)]
        for name in OCTANT_NAMES:
            assert cell(AXIS_COLUMN, 0) not in _octant_cells(ax, name), (
                "a cell with no receiver may not also carry a bearing"
            )
    finally:
        mpl.close(fig)


def test_every_cell_is_drawn_exactly_once(mpl) -> None:
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(), ax)

    try:
        drawn = [
            index
            for label in (*OCTANT_NAMES, NO_RECEIVER_LABEL, INACTIVE_LABEL)
            for index in _octant_cells(ax, label)
        ]
        assert sorted(drawn) == list(range(NX * NY)), (
            "the bearings, the dead ends and the inactive cells partition the mesh"
        )
    finally:
        mpl.close(fig)


def test_the_note_counts_the_cells_that_took_each_bearing(mpl) -> None:
    """Four bands and four absences look like eight bands until it is written.

    On a shared-edge graph the diagonals cannot be taken at all, which is the
    first thing this map says and the one thing its colours cannot show.
    """
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(), ax)

    try:
        note = ax.texts[0].get_text()
        assert "bearings: E 6, W 6, S 2" in note
        assert "none on NE, N, NW, SW, SE" in note
    finally:
        mpl.close(fig)


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
# the neighbourhood the graph was built on
# --------------------------------------------------------------------------- #


def test_no_diagonal_bearing_appears_without_a_diagonal_graph(mpl) -> None:
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(topography=tilted_plane()), ax)

    try:
        for name in ("NE", "NW", "SE", "SW"):
            assert _octant_cells(ax, name) == [], (
                f"{name} is not a shared edge, so a four-neighbour graph cannot take it"
            )
        assert "no diagonal" in ax.texts[0].get_text()
    finally:
        mpl.close(fig)


def test_the_diagonal_descent_is_taken_once_the_graph_carries_it(mpl) -> None:
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(
        comparison_run(topography=tilted_plane()), ax, diagonal_neighbors=True
    )

    try:
        interior = [cell(column, row) for row in (1, 2) for column in range(1, NX)]
        assert _octant_cells(ax, "SW") == sorted(interior)
        # The southern row and the western column have no south-west neighbour,
        # so they keep the cardinal step that is left to them.
        assert _octant_cells(ax, "W") == [cell(column, 0) for column in range(1, NX)]
        assert _octant_cells(ax, "S") == [cell(0, row) for row in (1, 2)]
        assert _octant_cells(ax, NO_RECEIVER_LABEL) == [cell(0, 0)]
        assert "including the diagonals" in ax.texts[0].get_text()
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the legend a reader tells north-east from south-west with
# --------------------------------------------------------------------------- #


def test_the_compass_puts_each_colour_at_the_bearing_it_means(mpl) -> None:
    from matplotlib.patches import Wedge

    fig, ax = mpl.subplots()

    FlowDirectionMap().render(
        comparison_run(topography=tilted_plane()), ax, diagonal_neighbors=True
    )

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
            assert len(matching) == 1, f"one wedge carries the colour the map used for {name}"
            centre = (matching[0].theta1 + matching[0].theta2) / 2.0
            assert centre == pytest.approx(45.0 * OCTANT_NAMES.index(name)), (
                f"the {name} colour must sit at the {name} bearing of the rose"
            )
    finally:
        mpl.close(fig)


def test_a_bearing_no_cell_took_is_drawn_hollow(mpl) -> None:
    """A painted wedge claims cells the map does not have."""
    from matplotlib.patches import Wedge

    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(), ax)

    try:
        wedges = [item for item in _compass(ax).patches if isinstance(item, Wedge)]
        assert len(wedges) == len(OCTANT_NAMES)
        painted = {
            name
            for name, wedge in zip(OCTANT_NAMES, wedges, strict=True)
            if wedge.get_facecolor()[3] > 0.0
        }
        assert painted == {"E", "W", "S"}
        hollow = [wedge for name, wedge in zip(OCTANT_NAMES, wedges, strict=True) if name == "NE"]
        assert hollow[0].get_linestyle() != "solid"
    finally:
        mpl.close(fig)


def test_the_compass_names_the_eight_bearings(mpl) -> None:
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(), ax)

    try:
        labels = {text.get_text() for text in _compass(ax).texts}
        assert set(OCTANT_NAMES) <= labels
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the colours the map is read by
# --------------------------------------------------------------------------- #


def test_the_two_states_that_carry_no_bearing_stay_off_the_circle() -> None:
    """A dead end and an inactive cell may not read as a ninth bearing.

    The cyclic palette spans the whole lightness range, so a flat colour for
    either state can always land on one of the eight: the sand of the
    high-contrast triplet sits 0.04 in relative luminance from octant SE, in
    the same warm hue. Both neutrals must keep a real gap from all eight.
    """
    pytest.importorskip("matplotlib")

    from hydromodpy.display.figures.flow_direction_map import _INACTIVE_FACE, _PIT_FACE

    octants = [relative_luminance(color) for color in octant_colors()]

    for neutral in (_PIT_FACE, _INACTIVE_FACE):
        gap = min(abs(relative_luminance(neutral) - level) for level in octants)
        assert gap > 0.1, f"{neutral} sits {gap:.3f} from the nearest octant"


def test_the_dead_end_is_told_by_a_texture_and_not_by_a_hue(mpl) -> None:
    """No hue is free on a cyclic palette, so the ninth state is hatched."""
    from matplotlib.colors import to_hex

    from hydromodpy.display.figures.flow_direction_map import _PIT_FACE

    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(), ax)

    try:
        layer = _labelled(ax, NO_RECEIVER_LABEL)
        assert layer is not None
        assert layer.get_hatch(), "a flat colour cannot be told from all eight octants"
        assert to_hex(layer.get_facecolor()[0]) == to_hex(_PIT_FACE)
    finally:
        mpl.close(fig)


def test_the_catchment_outline_is_drawn_as_a_halo_under_a_line(mpl) -> None:
    """One line cannot clear both ends of a cyclic palette at once.

    Over the darkest octant a dark outline contrasts 1.6:1 and disappears;
    over the lightest one a pale outline does the same. Two passes leave one
    of the two readable wherever the outline runs.
    """
    from matplotlib.collections import LineCollection
    from matplotlib.colors import to_hex

    from hydromodpy.display.figures.flow_direction_map import _CONTOUR_HALO, _CONTOUR_LINE

    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(), ax)

    try:
        outlines = [item for item in ax.collections if isinstance(item, LineCollection)]
        assert len(outlines) == 2, "the outline is drawn twice, halo then line"
        halo, line = outlines
        assert to_hex(halo.get_color()[0]) == to_hex(_CONTOUR_HALO)
        assert to_hex(line.get_color()[0]) == to_hex(_CONTOUR_LINE)
        assert halo.get_linewidth()[0] > 2.0 * line.get_linewidth()[0]
        assert relative_luminance(_CONTOUR_HALO) - relative_luminance(_CONTOUR_LINE) > 0.9
    finally:
        mpl.close(fig)


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


def test_a_coarser_subsample_draws_fewer_arrows_than_cells(mpl) -> None:
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(), ax, arrow_bins=2)

    try:
        arrows = _quiver(ax)
        assert arrows is not None
        drawn = len(arrows.get_offsets())
        assert 0 < drawn <= 4, f"a 2 x 2 subsample may draw at most four arrows, drew {drawn}"
    finally:
        mpl.close(fig)


def test_no_arrow_has_zero_length(mpl) -> None:
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(), ax)

    try:
        arrows = _quiver(ax)
        assert arrows is not None
        magnitude = np.hypot(arrows.U, arrows.V)
        assert np.all(magnitude > 0.0), (
            "a cell with no receiver must be drawn as a dead end, never as an arrow "
            "of zero length pointing nowhere"
        )
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


def test_it_is_rendered_from_a_run_alone(tmp_path) -> None:
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run

    cfg = DisplayConfig(enabled=True, figures=["flow_direction_map"], on_error="raise")

    report = render_figures_for_run(comparison_run(), cfg, output_dir=tmp_path)

    assert report.rendered == ("flow_direction_map",)
    assert report.skipped == ()
    assert (tmp_path / "flow_direction_map.png").exists()


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
