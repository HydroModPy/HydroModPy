"""The class map of the downslope distance field.

The mesh is a strip of unit squares, one per cell, so a cell is identified by
the abscissa of its polygon and a test can say which cell landed in which
class without looking at a single pixel.
"""

from __future__ import annotations

from types import SimpleNamespace

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


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _mesh_run(n_faces: int) -> SimpleNamespace:
    """A run whose mesh is a strip of unit squares, one per cell."""
    vertices = [[float(index), 0.0, 0.0] for index in range(n_faces + 1)]
    vertices += [[float(index), 1.0, 0.0] for index in range(n_faces + 1)]
    top = n_faces + 1
    faces = [[index, index + 1, top + index + 1, top + index] for index in range(n_faces)]
    return SimpleNamespace(
        sim_id="sim-mesh",
        name="cheze",
        mesh=SimpleNamespace(
            vertices=np.asarray(vertices, dtype=float),
            face_node_connectivity=np.asarray(faces, dtype=int),
        ),
    )


def _layer(ax, label: str):
    """The one collection drawn under ``label``."""
    return next(item for item in ax.collections if str(item.get_label()) == label)


def _has_layer(ax, label: str) -> bool:
    return any(str(item.get_label()) == label for item in ax.collections)


def _cells(collection) -> list[int]:
    """Indices of the strip cells one collection covers."""
    return sorted(int(round(path.vertices[:, 0].min())) for path in collection.get_paths())


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


def test_each_cell_lands_in_its_own_class(mpl) -> None:
    run = _mesh_run(4)
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(
        run,
        ax,
        distance=np.array([10.0, 200.0, 800.0, 4000.0]),
        support=np.ones(4, dtype=bool),
    )

    try:
        assert _cells(_layer(ax, "0-75 m")) == [0]
        assert _cells(_layer(ax, "75-500 m")) == [1]
        assert _cells(_layer(ax, "500-1000 m")) == [2]
        assert _cells(_layer(ax, "> 1000 m")) == [3]
        assert _legend_labels(ax)[:4] == [
            "0-75 m (1 cell)",
            "75-500 m (1 cell)",
            "500-1000 m (1 cell)",
            "> 1000 m (1 cell)",
        ]
        assert "cheze" in ax.get_title()
        assert ax.get_xlabel() == "x (m)"
    finally:
        mpl.close(fig)


def test_a_boundary_value_opens_the_upper_class(mpl) -> None:
    run = _mesh_run(3)
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(
        run,
        ax,
        distance=np.array([75.0, 500.0, 1000.0]),
        support=np.ones(3, dtype=bool),
    )

    try:
        assert _cells(_layer(ax, "75-500 m")) == [0]
        assert _cells(_layer(ax, "500-1000 m")) == [1]
        assert _cells(_layer(ax, "> 1000 m")) == [2]
    finally:
        mpl.close(fig)


def test_the_scale_is_discrete_with_one_flat_colour_per_class(mpl) -> None:
    run = _mesh_run(4)
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(
        run,
        ax,
        distance=np.array([10.0, 20.0, 30.0, 4000.0]),
        support=np.ones(4, dtype=bool),
    )

    try:
        near = _layer(ax, "0-75 m")
        # Three different distances, one single colour: the class is the value.
        assert _cells(near) == [0, 1, 2]
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
# the two states that are not a distance
# --------------------------------------------------------------------------- #


def test_a_cell_off_the_support_is_out_of_the_scale_and_never_a_zero(mpl) -> None:
    run = _mesh_run(3)
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(
        run,
        ax,
        # Cell 1 carries a zero distance but is not measured: it may not be
        # drawn in the nearest class, which is what a plain zero would do.
        distance=np.array([10.0, 0.0, 800.0]),
        support=np.array([True, False, True]),
    )

    try:
        assert _cells(_layer(ax, "0-75 m")) == [0]
        off = _layer(ax, "off support")
        assert _cells(off) == [1]
        assert _face_color(off) not in [_rgb(color) for color in class_colors(4)]
        assert "not on the measured support (1 cell)" in _legend_labels(ax)
    finally:
        mpl.close(fig)


def test_a_cell_whose_descent_never_arrives_gets_its_own_state(mpl) -> None:
    run = _mesh_run(3)
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(
        run,
        ax,
        distance=np.array([10.0, np.inf, 4000.0]),
        support=np.ones(3, dtype=bool),
    )

    try:
        unreachable = _layer(ax, "unreachable")
        assert _cells(unreachable) == [1]
        assert _cells(_layer(ax, "> 1000 m")) == [2], (
            "an unreachable cell has no distance and may not join the far class"
        )
        assert _face_color(unreachable) not in [_rgb(color) for color in class_colors(4)]
        assert unreachable.get_hatch(), "the third state must not read as one more class"
        assert any("unreachable" in label for label in _legend_labels(ax))
        assert "never reaches" in " ".join(_legend_labels(ax))
    finally:
        mpl.close(fig)


def test_an_unmeasured_cell_is_not_an_unreachable_one(mpl) -> None:
    run = _mesh_run(2)
    fig, ax = mpl.subplots()

    # NaN is the value the distance field carries outside the active surface.
    DownslopeDistanceMap().render(
        run,
        ax,
        distance=np.array([10.0, np.nan]),
        support=np.ones(2, dtype=bool),
    )

    try:
        assert _cells(_layer(ax, "off support")) == [1]
        assert not _has_layer(ax, "unreachable")
    finally:
        mpl.close(fig)


def test_the_support_defaults_to_the_measured_cells(mpl) -> None:
    run = _mesh_run(3)
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(run, ax, distance=np.array([10.0, np.nan, 800.0]))

    try:
        assert _cells(_layer(ax, "0-75 m")) == [0]
        assert _cells(_layer(ax, "500-1000 m")) == [2]
        assert _cells(_layer(ax, "off support")) == [1]
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# when there is nothing to show, the figure says so
# --------------------------------------------------------------------------- #


def test_an_empty_support_is_annotated_rather_than_drawn_empty(mpl) -> None:
    run = _mesh_run(3)
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(
        run,
        ax,
        distance=np.array([10.0, 200.0, 800.0]),
        support=np.zeros(3, dtype=bool),
    )

    try:
        note = ax.texts[0].get_text()
        assert "no cell" in note
        assert not _has_layer(ax, "0-75 m")
        assert _cells(_layer(ax, "off support")) == [0, 1, 2]
    finally:
        mpl.close(fig)


def test_a_support_that_never_arrives_is_annotated(mpl) -> None:
    run = _mesh_run(2)
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(
        run,
        ax,
        distance=np.array([np.inf, np.inf]),
        support=np.ones(2, dtype=bool),
    )

    try:
        note = ax.texts[0].get_text()
        assert "no cell of the support reaches its target" in note
        assert _cells(_layer(ax, "unreachable")) == [0, 1]
    finally:
        mpl.close(fig)


def test_nothing_is_annotated_when_the_classes_are_populated(mpl) -> None:
    run = _mesh_run(2)
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(run, ax, distance=np.array([10.0, 800.0]))

    try:
        # The two classes must really be on the axes: an empty map carries no
        # annotation either, and this test may not pass on one.
        assert _cells(_layer(ax, "0-75 m")) == [0]
        assert _cells(_layer(ax, "500-1000 m")) == [1]
        assert len(ax.texts) == 0
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# overriding the classes
# --------------------------------------------------------------------------- #


def test_a_caller_may_give_its_own_class_edges(mpl) -> None:
    run = _mesh_run(3)
    fig, ax = mpl.subplots()

    DownslopeDistanceMap().render(
        run,
        ax,
        distance=np.array([5.0, 40.0, 400.0]),
        class_edges=(0.0, 25.0, 250.0),
    )

    try:
        assert _cells(_layer(ax, "0-25 m")) == [0]
        assert _cells(_layer(ax, "25-250 m")) == [1]
        assert _cells(_layer(ax, "> 250 m")) == [2]
        assert not _has_layer(ax, "75-500 m")
    finally:
        mpl.close(fig)


@pytest.mark.parametrize(
    "edges",
    [(0.0, 500.0, 75.0, 1000.0), (0.0, 75.0, 75.0, 1000.0)],
)
def test_class_edges_that_do_not_increase_are_refused(mpl, edges) -> None:
    run = _mesh_run(2)
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="strictly increasing"):
            DownslopeDistanceMap().render(
                run, ax, distance=np.array([10.0, 800.0]), class_edges=edges
            )
    finally:
        mpl.close(fig)


def test_a_class_edge_that_is_not_a_number_is_refused(mpl) -> None:
    run = _mesh_run(2)
    fig, ax = mpl.subplots()

    try:
        # NaN passes every ordering comparison, so it must be caught on its own
        # or it reaches searchsorted on an unsorted array and scatters classes.
        with pytest.raises(ValueError, match="finite"):
            DownslopeDistanceMap().render(
                run,
                ax,
                distance=np.array([10.0, 800.0]),
                class_edges=(0.0, float("nan"), 500.0),
            )
    finally:
        mpl.close(fig)


def test_a_single_class_edge_is_refused(mpl) -> None:
    run = _mesh_run(2)
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="at least two"):
            DownslopeDistanceMap().render(
                run, ax, distance=np.array([10.0, 800.0]), class_edges=(0.0,)
            )
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# refusals
# --------------------------------------------------------------------------- #


def test_a_distance_field_of_the_wrong_size_is_refused(mpl) -> None:
    run = _mesh_run(2)
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="the mesh holds 2"):
            DownslopeDistanceMap().render(run, ax, distance=np.array([1.0, 2.0, 3.0]))
    finally:
        mpl.close(fig)


def test_a_support_of_the_wrong_size_is_refused(mpl) -> None:
    run = _mesh_run(2)
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="the mesh holds 2"):
            DownslopeDistanceMap().render(
                run,
                ax,
                distance=np.array([1.0, 2.0]),
                support=np.array([True, False, True]),
            )
    finally:
        mpl.close(fig)


def test_a_negative_distance_is_refused(mpl) -> None:
    run = _mesh_run(2)
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="negative"):
            DownslopeDistanceMap().render(run, ax, distance=np.array([-5.0, 800.0]))
    finally:
        mpl.close(fig)


def test_a_negative_infinity_is_refused_rather_than_called_unreachable(mpl) -> None:
    run = _mesh_run(2)
    fig, ax = mpl.subplots()

    try:
        # Only +inf means "the descent ends short"; -inf is a broken field and
        # must not be promoted to the unreachable state.
        with pytest.raises(ValueError, match="negative"):
            DownslopeDistanceMap().render(run, ax, distance=np.array([-np.inf, 800.0]))
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the gallery
# --------------------------------------------------------------------------- #


def test_it_names_what_it_needs_when_it_cannot_be_drawn() -> None:
    reason = DownslopeDistanceMap().unavailable_reason(_mesh_run(2))

    assert reason is not None
    assert "calibration" in reason
    assert "render()" in reason


def test_it_is_skipped_by_the_gallery_rather_than_crashing(tmp_path) -> None:
    pytest.importorskip("matplotlib")
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run

    cfg = DisplayConfig(
        enabled=True,
        figures=["downslope_distance_map"],
        on_error="raise",
    )

    report = render_figures_for_run(_mesh_run(4), cfg, output_dir=tmp_path)

    assert report.rendered == ()
    assert [item.name for item in report.skipped] == ["downslope_distance_map"]
    assert "distance" in report.skipped[0].reason
    assert "render failed" not in report.skipped[0].reason


def test_it_is_registered_under_its_own_name() -> None:
    figure = get_figure("downslope_distance_map")

    assert isinstance(figure, DownslopeDistanceMap)
    assert figure.spec.name == "downslope_distance_map"
    assert figure.spec.kind == "spatial"
