"""The class map of the downslope distance field.

The figure is driven by a run and nothing else, as a ``[display].figures`` entry
drives it. The run is the V-shaped valley of
:mod:`tests.unit.display._network_comparison_run`, where the descent of a cell
is a whole number of cell widths, so a test says which cell landed in which
class without looking at a single pixel and without asking the criterion.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.display.figures.downslope_distance_map import DownslopeDistanceMap, class_colors
from tests._helpers.sealed_runs import sealed_search

from ._network_comparison_run import (
    AXIS_COLUMN,
    CELL_M,
    NX,
    NY,
    cell,
    column_cells,
    comparison_run,
    drawn_cells,
    legend_labels,
    legend_note,
)

WIDE_CELL_M = 600.0
"""A cell width that spreads the same geometry over the far classes."""


def _layer(ax, label: str):
    """The one collection drawn under ``label``."""
    return next(item for item in ax.collections if str(item.get_label()) == label)


def _has_layer(ax, label: str) -> bool:
    return any(str(item.get_label()) == label for item in ax.collections)


def _cells(ax, label: str, cell_m: float = CELL_M) -> list[int]:
    """The grid cells one drawn class covers."""
    return drawn_cells(_layer(ax, label), cell_m)


def _face_color(collection) -> tuple[float, ...]:
    return tuple(np.asarray(collection.get_facecolor()).reshape(-1)[:3])


def _rgb(color: str) -> tuple[float, ...]:
    from matplotlib.colors import to_rgb

    return tuple(to_rgb(color))


def _two_branch_run(cell_m: float = CELL_M):
    """A run whose simulated network runs two cells up each flank.

    Seepage at the far end of the northern east flank and one cell up the
    western one: their water crosses the flank cell by cell and then joins the
    mapped column, so the support of ``D_so`` holds one cell at every whole
    number of cell widths from the map, and the axis column at zero.

    Sealed under ``crossing``: the distance classes are the subject here, not
    the rasterization rule, and the mapped axis has no free end this mesh's
    heads rule could trace without being lost.
    """
    run = comparison_run(seepage_cells=[cell(4, 2), cell(0, 1)], cell_m=cell_m)
    run.dir = sealed_search(
        {
            "outputs": {
                "streams": {
                    "support": "network",
                    "map": {"complete": "data.hydrography", "drawn_by": "crossing"},
                }
            }
        }
    )
    return run


# --------------------------------------------------------------------------- #
# the four classes of the paper
# --------------------------------------------------------------------------- #


def test_the_scale_is_discrete_with_one_flat_color_per_class(mpl) -> None:
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(_two_branch_run(WIDE_CELL_M), ax)

    try:
        near = _layer(ax, "0-75 m")
        # Three cells, one single color: the class is the value.
        assert len(near.get_paths()) == 3
        assert _face_color(near) == pytest.approx(_rgb(class_colors(4)[0]))
        assert _face_color(_layer(ax, "> 1000 m")) == pytest.approx(_rgb(class_colors(4)[3]))
        assert not fig.axes[1:], "a discrete class scale carries no continuous colorbar"
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# which of the two distances is on the page, in words
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# the support is the one the criterion averages over
# --------------------------------------------------------------------------- #


def test_the_direction_picks_the_network_the_descent_starts_from(mpl) -> None:
    # D_os is measured over the mapped column, and its cells descend to the
    # simulated network one cell at a time: zero at the outlet, one cell width
    # above it, two at the top.
    run = comparison_run(seepage_cells=[cell(4, 0)])
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(run, ax, direction="to_simulated")

    try:
        assert _cells(ax, "0-75 m") == [cell(AXIS_COLUMN, 0)]
        assert _cells(ax, "75-500 m") == [cell(AXIS_COLUMN, 1), cell(AXIS_COLUMN, 2)]
        assert "D_os" in ax.get_title()
        assert "the mapped cells down to the simulated network" in ax.get_title()
        assert "how far each of the mapped cells" in legend_note(ax)
    finally:
        mpl.close(fig)


def test_an_unknown_direction_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="direction must be one of"):
            DownslopeDistanceMap().render(comparison_run(), ax, direction="sideways")
    finally:
        mpl.close(fig)


def test_the_map_opens_on_the_catchment_and_a_caller_may_widen_it(mpl) -> None:
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(_two_branch_run(), ax, extent="mesh")

    try:
        assert ax.get_xlim()[1] >= NX * CELL_M
        assert "the whole mesh" in legend_note(ax)
    finally:
        mpl.close(fig)

    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(
        comparison_run(seepage_cells=[cell(0, 1)], catchment_columns=[0, 1]), ax
    )

    try:
        assert ax.get_xlim()[1] < 3 * CELL_M
        assert "the delineated catchment" in legend_note(ax)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# when there is nothing to measure, the figure says so
# --------------------------------------------------------------------------- #


def test_a_support_that_never_arrives_is_annotated(mpl) -> None:
    # A run whose model releases nothing has no simulated network, so no
    # mapped cell has a descent down to one.
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(comparison_run(), ax, direction="to_simulated")

    try:
        note = legend_note(ax)
        assert "no cell of the support reaches its target" in note
        assert _cells(ax, "unreachable") == column_cells(AXIS_COLUMN)
        assert _layer(ax, "unreachable").get_hatch(), (
            "the third state must not read as one more class"
        )
        assert any("never reaches" in label for label in legend_labels(ax))
    finally:
        mpl.close(fig)


def test_an_empty_support_is_annotated_rather_than_drawn_empty(mpl) -> None:
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(comparison_run(), ax)

    try:
        assert "no cell is on the measured support" in legend_note(ax)
        assert not _has_layer(ax, "0-75 m")
        assert len(_cells(ax, "off support")) == NX * NY
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# overriding the classes
# --------------------------------------------------------------------------- #


def test_a_caller_may_give_its_own_class_edges(mpl) -> None:
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(_two_branch_run(), ax, class_edges=(0.0, 50.0, 150.0))

    try:
        assert _cells(ax, "0-50 m") == column_cells(AXIS_COLUMN)
        assert _cells(ax, "50-150 m") == [cell(1, 1), cell(3, 2)]
        assert _cells(ax, "> 150 m") == [cell(0, 1), cell(4, 2)]
        assert not _has_layer(ax, "75-500 m")
    finally:
        mpl.close(fig)


@pytest.mark.parametrize(
    "edges",
    [(0.0, 500.0, 75.0, 1000.0), (0.0, 75.0, 75.0, 1000.0)],
)
def test_class_edges_that_do_not_increase_are_refused(mpl, edges) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="strictly increasing"):
            DownslopeDistanceMap().render(comparison_run(), ax, class_edges=edges)
    finally:
        mpl.close(fig)


def test_a_class_edge_that_is_not_a_number_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        # NaN passes every ordering comparison, so it must be caught on its own
        # or it reaches searchsorted on an unsorted array and scatters classes.
        with pytest.raises(ValueError, match="finite"):
            DownslopeDistanceMap().render(
                comparison_run(), ax, class_edges=(0.0, float("nan"), 500.0)
            )
    finally:
        mpl.close(fig)


def test_a_single_class_edge_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="at least two"):
            DownslopeDistanceMap().render(comparison_run(), ax, class_edges=(0.0,))
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the gallery
# --------------------------------------------------------------------------- #


def test_it_is_rendered_from_a_run_alone(tmp_path) -> None:
    pytest.importorskip("matplotlib")
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run

    cfg = DisplayConfig(enabled=True, figures=["downslope_distance_map"], on_error="raise")

    report = render_figures_for_run(_two_branch_run(), cfg, output_dir=tmp_path)

    assert report.rendered == ("downslope_distance_map",)
    assert report.skipped == ()
    assert (tmp_path / "downslope_distance_map.png").exists()


def test_it_is_skipped_by_the_gallery_rather_than_crashing(tmp_path) -> None:
    pytest.importorskip("matplotlib")
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run

    cfg = DisplayConfig(enabled=True, figures=["downslope_distance_map"], on_error="raise")

    report = render_figures_for_run(comparison_run(with_release=False), cfg, output_dir=tmp_path)

    assert report.rendered == ()
    assert [item.name for item in report.skipped] == ["downslope_distance_map"]
    assert "release_flux" in report.skipped[0].reason
    assert "render failed" not in report.skipped[0].reason
