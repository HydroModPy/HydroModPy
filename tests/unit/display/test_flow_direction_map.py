"""Map of where every cell sends its water, on grids whose answer is known.

The runs come from ``_network_comparison_run``. Two surfaces are used, the
V-shaped valley of that module, whose flanks descend to the axis and whose
axis descends to the outlet, and a plane tilted toward the south-west corner
where the steepest descent is a diagonal. Elevations are in m, cells are
``CELL_M`` wide. Both partitions are written down before the receiver graph
is built.
"""

from __future__ import annotations

import numpy as np
import pytest
from matplotlib.axes import Axes
from matplotlib.patches import Wedge
from matplotlib.quiver import Quiver

from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.figures.flow_direction_map import (
    NO_RECEIVER_LABEL,
    OCTANT_NAMES,
    RAISED_LABEL,
    FlowDirectionMap,
)
from hydromodpy.display.runs import render_figures_for_run

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

SOUTH_WEST_STEP_M = 10.0  # drop per column and per row of the tilted plane


def tilted_plane() -> np.ndarray:
    """A plane falling toward the south-west corner of the grid.

    One column and one row are the same drop, so the diagonal step falls twice
    as much over sqrt(2) times the distance. It is the steepest descent of
    every interior cell, and no four-neighbor graph can take it.
    """
    return np.asarray(
        [(column + row) * SOUTH_WEST_STEP_M for row in range(NY) for column in range(NX)],
        dtype=float,
    )


def valley_with_a_pit() -> np.ndarray:
    """The valley with the cell west of the axis dug below the axis itself."""
    top = valley_topography()
    top[cell(1, 1)] = -50.0
    return top


def run_without_top():
    run = comparison_run()
    run.mesh.topography = None
    return run


def octant_cells(ax, name: str) -> list[int]:
    """The grid cells drawn under one bearing, empty when none took it."""
    for collection in ax.collections:
        if str(collection.get_label()) == name:
            return drawn_cells(collection)
    return []


def labelled(ax, label: str):
    """The one collection drawn under ``label``, or None when it is empty."""
    return next((item for item in ax.collections if str(item.get_label()) == label), None)


def compass(ax):
    """The inset axes carrying the compass rose."""
    roses = [child for child in ax.get_children() if isinstance(child, Axes)]
    assert len(roses) == 1, "the figure draws exactly one compass rose"
    return roses[0]


def test_outlet_is_marked_on_the_lowest_cell(mpl) -> None:
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(), ax)

    stars = [line for line in ax.lines if line.get_marker() == "*"]
    assert len(stars) == 1
    assert stars[0].get_xdata()[0] == pytest.approx((AXIS_COLUMN + 0.5) * CELL_M)
    assert stars[0].get_ydata()[0] == pytest.approx(0.5 * CELL_M)
    assert "outlet cell 2 at 0.00 m" in ax.texts[0].get_text()


def test_no_diagonal_bearing_without_a_diagonal_graph(mpl) -> None:
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(
        comparison_run(topography=tilted_plane(), descent_diagonals=False), ax
    )

    for name in ("NE", "NW", "SE", "SW"):
        assert octant_cells(ax, name) == [], (
            f"{name} is not a shared edge, so a four-neighbour graph cannot take it"
        )
    assert "no diagonal" in ax.texts[0].get_text()


def test_pit_of_the_top_is_marked_as_raised(mpl) -> None:
    # The steepest descent of the top dies in the pit, D fills it and routes on.
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(topography=valley_with_a_pit()), ax)

    assert octant_cells(ax, NO_RECEIVER_LABEL) == [cell(AXIS_COLUMN, 0)], (
        "on D the only cell without receiver is the outlet of the valley, never a pit"
    )
    raised = labelled(ax, RAISED_LABEL)
    assert raised is not None
    assert len(raised.get_offsets()) == 1
    assert "the descent raised 1 cell on its copy" in ax.texts[0].get_text()


def test_compass_puts_each_color_at_its_bearing(mpl) -> None:
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(topography=tilted_plane()), ax)

    wedges = [item for item in compass(ax).patches if isinstance(item, Wedge)]
    assert len(wedges) == len(OCTANT_NAMES), "every bearing keeps a wedge, empty or not"
    for name in ("SW", "W", "S"):
        painted = labelled(ax, name)
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


def test_arrows_are_switched_off_by_zero_bins(mpl) -> None:
    fig, ax = mpl.subplots()

    FlowDirectionMap().render(comparison_run(), ax, arrow_bins=0)

    assert next((item for item in ax.collections if isinstance(item, Quiver)), None) is None
    assert "arrows" not in ax.texts[0].get_text()


def test_valley_is_the_one_the_module_publishes() -> None:
    # The expectations above are written against that surface. A change to it
    # has to break this test rather than quietly rewrite the partition.
    surface = valley_topography()

    assert surface[cell(AXIS_COLUMN, 0)] == surface.min()
    assert surface[cell(0, 0)] > surface[cell(1, 0)] > surface[cell(AXIS_COLUMN, 0)]


UNAVAILABLE = [
    pytest.param(run_without_top(), "topography", id="no mesh top kept"),
    pytest.param(comparison_run(topography=np.full(NX * NY, np.nan)), "elevation", id="all nodata"),
]


@pytest.mark.parametrize(("run", "word"), UNAVAILABLE)
def test_unavailable_reason_names_what_it_needs(run, word) -> None:
    reason = FlowDirectionMap().unavailable_reason(run)

    assert reason is not None
    assert word in reason


def test_surface_with_no_active_cell_is_skipped_by_the_gallery(tmp_path) -> None:
    cfg = DisplayConfig(enabled=True, figures=["flow_direction_map"], on_error="raise")

    report = render_figures_for_run(
        comparison_run(topography=np.full(NX * NY, np.nan)), cfg, output_dir=tmp_path
    )

    assert report.rendered == ()
    assert [item.name for item in report.skipped] == ["flow_direction_map"]
    assert "render failed" not in report.skipped[0].reason


def test_negative_arrow_bins_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()

    with pytest.raises(ValueError, match="arrow_bins"):
        FlowDirectionMap().render(comparison_run(), ax, arrow_bins=-1)


def test_toml_override_reaches_the_figure(tmp_path) -> None:
    # A knob set under [display.overrides.flow_direction_map] must arrive at
    # render(). The cheapest proof is a value render() is known to refuse.
    cfg = DisplayConfig(
        enabled=True,
        figures=["flow_direction_map"],
        overrides={"flow_direction_map": {"arrow_bins": -1}},
        on_error="raise",
    )

    with pytest.raises(ValueError, match="arrow_bins"):
        render_figures_for_run(comparison_run(), cfg, output_dir=tmp_path)
