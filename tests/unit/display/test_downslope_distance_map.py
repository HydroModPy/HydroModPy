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

from hydromodpy.display.colormaps import HIGH_CONTRAST_TRIPLET
from hydromodpy.display.figure_registry import get as get_figure
from hydromodpy.display.figures.downslope_distance_map import (
    DISTANCE_CLASS_EDGES_M,
    DownslopeDistanceMap,
    class_colors,
    class_labels,
)

from ._network_comparison_run import (
    AXIS_COLUMN,
    CELL_M,
    NX,
    NY,
    cell,
    column_cells,
    comparison_run,
    drawn_cells,
)

WIDE_CELL_M = 600.0
"""A cell width that spreads the same geometry over the far classes."""


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _layer(ax, label: str):
    """The one collection drawn under ``label``."""
    return next(item for item in ax.collections if str(item.get_label()) == label)


def _has_layer(ax, label: str) -> bool:
    return any(str(item.get_label()) == label for item in ax.collections)


def _cells(ax, label: str, cell_m: float = CELL_M) -> list[int]:
    """The grid cells one drawn class covers."""
    return drawn_cells(_layer(ax, label), cell_m)


def _legend_labels(ax) -> list[str]:
    return [text.get_text() for text in ax.get_legend().get_texts()]


def _face_color(collection) -> tuple[float, ...]:
    return tuple(np.asarray(collection.get_facecolor()).reshape(-1)[:3])


def _rgb(color: str) -> tuple[float, ...]:
    from matplotlib.colors import to_rgb

    return tuple(to_rgb(color))


def _relative_luminance(color: str) -> float:
    """Perceived brightness of one colour, the quantity a greyscale print keeps."""
    from matplotlib.colors import to_rgb

    channels = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in to_rgb(color)
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _two_branch_run(cell_m: float = CELL_M):
    """A run whose simulated network runs two cells up each flank.

    Seepage at the far end of the northern east flank and one cell up the
    western one: their water crosses the flank cell by cell and then joins the
    mapped column, so the support of ``D_so`` holds one cell at every whole
    number of cell widths from the map, and the axis column at zero.
    """
    return comparison_run(seepage_cells=[cell(4, 2), cell(0, 1)], cell_m=cell_m)


# --------------------------------------------------------------------------- #
# the four classes of the paper
# --------------------------------------------------------------------------- #


def test_the_default_classes_are_the_ones_of_the_paper() -> None:
    assert DISTANCE_CLASS_EDGES_M == (0.0, 75.0, 500.0, 1000.0)
    assert class_labels(DISTANCE_CLASS_EDGES_M) == (
        "0-75 m",
        "75-500 m",
        "500-1000 m",
        "> 1000 m",
    )


def test_each_cell_of_the_support_lands_in_its_own_class(mpl) -> None:
    # One cell width from the map is 600 m, two are 1200 m, so the two flanks
    # split across the two far classes and the axis column sits at zero.
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(_two_branch_run(WIDE_CELL_M), ax)

    try:
        assert _cells(ax, "0-75 m", WIDE_CELL_M) == column_cells(AXIS_COLUMN)
        assert _cells(ax, "500-1000 m", WIDE_CELL_M) == [cell(1, 1), cell(3, 2)]
        assert _cells(ax, "> 1000 m", WIDE_CELL_M) == [cell(0, 1), cell(4, 2)]
        assert not _has_layer(ax, "75-500 m")
        assert _legend_labels(ax)[:4] == [
            "0-75 m (3 cells)",
            "75-500 m (0 cells)",
            "500-1000 m (2 cells)",
            "> 1000 m (2 cells)",
        ]
        assert "nancon" in ax.get_title()
        assert ax.get_xlabel() == "x (m)"
    finally:
        mpl.close(fig)


def test_the_same_support_moves_class_with_the_size_of_a_cell(mpl) -> None:
    # The same two branches on a hundred-metre mesh are one and two hundred
    # metres from the map, so they share the near class instead of splitting.
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(_two_branch_run(), ax)

    try:
        assert _cells(ax, "0-75 m") == column_cells(AXIS_COLUMN)
        assert _cells(ax, "75-500 m") == [
            cell(0, 1),
            cell(1, 1),
            cell(3, 2),
            cell(4, 2),
        ]
        assert not _has_layer(ax, "500-1000 m")
    finally:
        mpl.close(fig)


def test_the_scale_is_discrete_with_one_flat_colour_per_class(mpl) -> None:
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(_two_branch_run(WIDE_CELL_M), ax)

    try:
        near = _layer(ax, "0-75 m")
        # Three cells, one single colour: the class is the value.
        assert len(near.get_paths()) == 3
        assert _face_color(near) == pytest.approx(_rgb(class_colors(4)[0]))
        assert _face_color(_layer(ax, "> 1000 m")) == pytest.approx(_rgb(class_colors(4)[3]))
        assert not fig.axes[1:], "a discrete class scale carries no continuous colorbar"
    finally:
        mpl.close(fig)


def test_the_four_default_colours_come_from_the_high_contrast_triplet() -> None:
    colors = class_colors(4)

    assert colors[1:] == (
        HIGH_CONTRAST_TRIPLET[1],
        HIGH_CONTRAST_TRIPLET[2],
        HIGH_CONTRAST_TRIPLET[0],
    )
    assert colors[0] not in HIGH_CONTRAST_TRIPLET


def test_the_classes_stay_ordered_and_apart_in_greyscale() -> None:
    luminances = [_relative_luminance(color) for color in class_colors(4)]

    assert luminances == sorted(luminances, reverse=True), (
        "a longer distance must read as a darker cell, so the ordering of the "
        f"classes survives a greyscale print: {luminances}"
    )
    gaps = [low - high for low, high in zip(luminances[:-1], luminances[1:], strict=False)]
    assert min(gaps) > 0.1, f"two classes collide in greyscale: {luminances}"


def test_an_off_support_cell_stays_apart_from_the_shortest_distance() -> None:
    # The state that means "never measured" printed almost the same grey as
    # the class that means "agrees within 75 m". On a greyscale print the two
    # merged, which is the one confusion the third state exists to prevent.
    from hydromodpy.display.figures.downslope_distance_map import _OFF_SUPPORT_COLOR

    off_support = _relative_luminance(_OFF_SUPPORT_COLOR)
    lightest_class = _relative_luminance(class_colors(4)[0])

    assert off_support - lightest_class > 0.1, (
        f"off support {off_support} collides with the shortest class {lightest_class}"
    )


# --------------------------------------------------------------------------- #
# the support is the one the criterion averages over
# --------------------------------------------------------------------------- #


def test_a_cell_off_the_support_is_out_of_the_scale_and_never_a_zero(mpl) -> None:
    # Seepage halfway down the mapped column: the model produces no stream on
    # its northern cell, which sits ON the map and so is zero metres from it.
    # Drawn in the nearest class it would read as a perfect agreement where
    # nothing was measured at all.
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, 1)])
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(run, ax)

    try:
        assert _cells(ax, "0-75 m") == [cell(AXIS_COLUMN, 0), cell(AXIS_COLUMN, 1)]
        assert cell(AXIS_COLUMN, 2) in _cells(ax, "off support")
        assert _face_color(_layer(ax, "off support")) not in [
            _rgb(color) for color in class_colors(4)
        ]
        assert "not on the measured support (13 cells)" in _legend_labels(ax)
    finally:
        mpl.close(fig)


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
        assert "descent of the mapped cells" in ax.texts[0].get_text()
    finally:
        mpl.close(fig)


def test_an_unknown_direction_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="direction must be one of"):
            DownslopeDistanceMap().render(comparison_run(), ax, direction="sideways")
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
        note = ax.texts[0].get_text()
        assert "no cell of the support reaches its target" in note
        assert _cells(ax, "unreachable") == column_cells(AXIS_COLUMN)
        assert _layer(ax, "unreachable").get_hatch(), (
            "the third state must not read as one more class"
        )
        assert any("never reaches" in label for label in _legend_labels(ax))
    finally:
        mpl.close(fig)


def test_an_empty_support_is_annotated_rather_than_drawn_empty(mpl) -> None:
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(comparison_run(), ax)

    try:
        assert "no cell is on the measured support" in ax.texts[0].get_text()
        assert not _has_layer(ax, "0-75 m")
        assert len(_cells(ax, "off support")) == NX * NY
    finally:
        mpl.close(fig)


def test_the_note_names_the_measurement_and_its_threshold(mpl) -> None:
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(_two_branch_run(), ax, tau_specific_ratio=0.0)

    try:
        # The classes must really be populated: an empty map carries the two
        # lines too, and this test may not pass on one.
        assert _cells(ax, "0-75 m") == column_cells(AXIS_COLUMN)
        note = ax.texts[0].get_text()
        assert note.startswith("D_so: descent of the simulated cells")
        assert "seepage threshold: none (tau = 0)" in note
        assert "no cell" not in note
    finally:
        mpl.close(fig)


def test_the_note_names_the_threshold_the_partition_was_cut_at(mpl) -> None:
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(_two_branch_run(), ax, tau_specific_ratio=0.25)

    try:
        assert "tau = 0.25 of the mean recharge" in ax.texts[0].get_text()
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


def test_it_names_what_it_needs_when_the_run_kept_no_release_flux() -> None:
    reason = DownslopeDistanceMap().unavailable_reason(comparison_run(with_release=False))

    assert reason is not None
    assert "release_flux" in reason


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


def test_it_is_registered_under_its_own_name() -> None:
    figure = get_figure("downslope_distance_map")

    assert isinstance(figure, DownslopeDistanceMap)
    assert figure.spec.name == "downslope_distance_map"
    assert figure.spec.kind == "spatial"
    assert figure.spec.required_fields == ("release_flux",)
