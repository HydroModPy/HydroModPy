"""The visual check of a simulated stream network against the mapped one.

The figure answers one question before any number is trusted: do the two
networks live in the same place, and does the simulated one follow the talwegs
of the routing surface. Both come from the run itself, so the tests drive it
the way a ``[display].figures`` entry does and assert on the two networks the
run's release flux implies, on the relief behind them, on the pair staying
apart without colour, and on what the figure says when one of them is empty.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.display.figure_registry import get as get_figure
from hydromodpy.display.figures.seepage_network_reference_overlay import (
    NETWORK_COLORS,
    SeepageNetworkReferenceOverlay,
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


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _flank_run(**kwargs):
    """A run whose stream climbs two cells up the northern east flank.

    Its water crosses those two cells and then runs down the mapped column, so
    the simulated network is the map plus the two cells of the flank.
    """
    return comparison_run(seepage_cells=[cell(4, 2)], **kwargs)


def _relative_luminance(color: str) -> float:
    """Perceived brightness of one colour, the quantity a greyscale print keeps."""
    from matplotlib.colors import to_rgb

    channels = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in to_rgb(color)
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _polygon_area(vertices: np.ndarray) -> float:
    x, y = vertices[:, 0], vertices[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _collection(ax, label_prefix: str):
    return next(
        collection
        for collection in ax.collections
        if str(collection.get_label()).startswith(label_prefix)
    )


def _shading(ax) -> np.ndarray:
    return np.asarray(_collection(ax, "_relief").get_array(), dtype=float)


# --------------------------------------------------------------------------- #
# the composition
# --------------------------------------------------------------------------- #


def test_overlay_draws_the_two_networks_the_run_implies(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(), ax)

    try:
        assert drawn_cells(_collection(ax, "_observed")) == column_cells(AXIS_COLUMN)
        assert drawn_cells(_collection(ax, "_simulated")) == sorted(
            [*column_cells(AXIS_COLUMN), cell(3, 2), cell(4, 2)]
        )
        labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert labels[:2] == ["mapped network (3 cells)", "simulated network (5 cells)"]
        assert ax.get_xlabel() == "x (m)"
        assert ax.get_ylabel() == "y (m)"
        assert "nancon" in ax.get_title()
    finally:
        mpl.close(fig)


def test_overlay_stacks_the_networks_over_the_relief(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(), ax)

    try:
        relief = _collection(ax, "_relief")
        assert len(relief.get_paths()) == NX * NY, "the relief covers every mesh cell"
        assert relief.get_zorder() < _collection(ax, "_observed").get_zorder()
        assert (
            _collection(ax, "_observed").get_zorder() < _collection(ax, "_simulated").get_zorder()
        ), "the simulated network is drawn over the mapped one"
    finally:
        mpl.close(fig)


def test_overlay_frames_the_whole_mesh(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(), ax)

    try:
        xmin, xmax = ax.get_xlim()
        ymin, ymax = ax.get_ylim()
        assert xmin <= 0.0 and xmax >= NX * CELL_M
        assert ymin <= 0.0 and ymax >= NY * CELL_M
    finally:
        mpl.close(fig)


def test_overlay_draws_the_outlet_when_the_run_carries_one(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(), ax)

    try:
        labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert "Outlet" in labels
        assert _collection(ax, "Outlet").get_offsets().tolist() == [[250.0, 50.0]]
    finally:
        mpl.close(fig)


def test_overlay_names_the_threshold_it_was_drawn_at(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(), ax, tau_specific_ratio=0.25)

    try:
        assert "tau = 0.25 of the mean recharge" in ax.texts[0].get_text()
    finally:
        mpl.close(fig)


def test_a_threshold_above_every_release_leaves_no_simulated_network(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(), ax, tau_specific_ratio=1.0e6)

    try:
        labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert "simulated network (0 cells)" in labels
        assert "mapped network (3 cells)" in labels
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the two networks stay apart without colour
# --------------------------------------------------------------------------- #


def test_the_two_networks_stay_apart_in_greyscale() -> None:
    luminances = [_relative_luminance(color) for color in NETWORK_COLORS.values()]

    assert abs(luminances[0] - luminances[1]) > 0.1, (
        "the mapped and simulated networks must survive a greyscale print, so "
        f"their lightnesses may not collide: {luminances}"
    )


def test_the_simulated_network_is_inset_so_shape_carries_the_distinction(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(), ax)

    try:
        mapped = _polygon_area(_collection(ax, "_observed").get_paths()[0].vertices)
        simulated = _polygon_area(_collection(ax, "_simulated").get_paths()[0].vertices)
        assert mapped == pytest.approx(CELL_M**2), "the mapped network fills its cell"
        assert simulated < 0.5 * mapped, (
            "the simulated network must be drawn inset inside the cell, so the "
            "two networks are told apart by shape and not only by colour"
        )
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the relief
# --------------------------------------------------------------------------- #


def test_the_relief_lights_the_flank_that_faces_the_lamp(mpl) -> None:
    # The valley is lit from the west: the east flank faces the lamp and must
    # come out brighter than the west one, otherwise the shading carries no
    # aspect and the talwegs do not read.
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(), ax, azimuth_deg=270.0)

    try:
        shading = _shading(ax)
        assert shading.shape == (NX * NY,)
        assert np.all((shading >= 0.0) & (shading <= 1.0))
        grid = shading.reshape(NY, NX)
        assert np.all(grid[:, NX - 1] > grid[:, 0])
    finally:
        mpl.close(fig)


def test_flat_ground_takes_one_uniform_shade(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(
        _flank_run(relief=np.full(NX * NY, 120.0)),
        ax,
    )

    try:
        relief = _collection(ax, "_relief")
        shading = np.asarray(relief.get_array(), dtype=float)
        assert np.allclose(shading, shading[0])
        assert 0.0 < float(shading[0]) < 1.0
        assert relief.get_clim() == (0.0, 1.0), (
            "ground with no relief keeps the full grey scale; stretching a "
            "spread of zero would print rounding noise as topography"
        )
    finally:
        mpl.close(fig)


def test_a_gentle_relief_is_stretched_over_the_greys_it_occupies(mpl) -> None:
    # A shallow valley lights within a narrow band of the theoretical range.
    # Left on that range it prints as one flat plate and no talweg reads.
    gentle = np.asarray(
        [abs(column - AXIS_COLUMN) * 8.0 for _row in range(NY) for column in range(NX)],
        dtype=float,
    )
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(relief=gentle), ax)

    try:
        relief = _collection(ax, "_relief")
        shading = np.asarray(relief.get_array(), dtype=float)
        assert shading.max() - shading.min() < 0.2, "the synthetic relief is a gentle one"
        low, high = relief.get_clim()
        assert low > 0.3 and high < 0.95
        assert low == pytest.approx(float(np.percentile(shading, 2.0)))
        assert high == pytest.approx(float(np.percentile(shading, 98.0)))
    finally:
        mpl.close(fig)


def test_a_cell_without_an_elevation_stays_unshaded(mpl) -> None:
    elevation = np.full(NX * NY, 120.0)
    elevation[cell(1, 1)] = np.nan
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(relief=elevation), ax)

    try:
        shading = _shading(ax)
        assert np.isnan(shading[cell(1, 1)]), (
            "a cell the run gave no elevation must stay blank, never take the shade of flat ground"
        )
        assert np.isfinite(shading[np.arange(NX * NY) != cell(1, 1)]).all()
    finally:
        mpl.close(fig)


def test_overlay_says_when_the_run_persisted_no_topography(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(with_relief=False), ax)

    try:
        assert not [
            collection
            for collection in ax.collections
            if str(collection.get_label()).startswith("_relief")
        ]
        assert "no per-cell topography" in ax.texts[0].get_text()
    finally:
        mpl.close(fig)


def test_overlay_says_when_no_cell_carries_an_elevation(mpl) -> None:
    # A field of nothing but NaN prints exactly like flat white ground. Left
    # unsaid, a reader takes the blank for a relief with no talweg in it.
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(relief=np.full(NX * NY, np.nan)), ax)

    try:
        assert "relief background is missing" in ax.texts[0].get_text()
    finally:
        mpl.close(fig)


def test_overlay_refuses_a_topography_that_does_not_match_the_mesh(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match=f"the mesh holds {NX * NY}"):
            SeepageNetworkReferenceOverlay().render(_flank_run(relief=np.arange(5.0)), ax)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# an empty network is said, never drawn as an agreement
# --------------------------------------------------------------------------- #


def test_overlay_says_when_the_simulated_network_is_empty(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(comparison_run(), ax)

    try:
        assert "simulated network is empty" in ax.texts[0].get_text()
        labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert "simulated network (0 cells)" in labels
    finally:
        mpl.close(fig)


def test_overlay_says_when_the_mapped_network_leaves_the_catchment(mpl) -> None:
    # The mapped column runs outside the delineated watershed, so the criterion
    # scores none of it. The figure has nothing to compare against and says so
    # rather than drawing a simulated network alone as if it agreed.
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(catchment_columns=[0, 1]), ax)

    try:
        assert "mapped network is empty" in ax.texts[0].get_text()
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the gallery
# --------------------------------------------------------------------------- #


def test_overlay_is_rendered_from_a_run_alone(tmp_path) -> None:
    pytest.importorskip("matplotlib")
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run

    cfg = DisplayConfig(
        enabled=True,
        figures=["seepage_network_reference_overlay"],
        on_error="raise",
    )

    report = render_figures_for_run(_flank_run(), cfg, output_dir=tmp_path)

    assert report.rendered == ("seepage_network_reference_overlay",)
    assert report.skipped == ()
    assert (tmp_path / "seepage_network_reference_overlay.png").exists()


def test_overlay_is_skipped_by_the_gallery_rather_than_crashing(tmp_path) -> None:
    pytest.importorskip("matplotlib")
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run

    cfg = DisplayConfig(
        enabled=True,
        figures=["seepage_network_reference_overlay"],
        on_error="raise",
    )

    report = render_figures_for_run(comparison_run(with_release=False), cfg, output_dir=tmp_path)

    assert report.rendered == ()
    assert [item.name for item in report.skipped] == ["seepage_network_reference_overlay"]
    assert "release_flux" in report.skipped[0].reason
    assert "render failed" not in report.skipped[0].reason


def test_overlay_names_what_it_needs_when_the_run_kept_no_release_flux() -> None:
    reason = SeepageNetworkReferenceOverlay().unavailable_reason(comparison_run(with_release=False))

    assert reason is not None
    assert "release_flux" in reason


def test_the_figure_is_registered_under_its_own_name() -> None:
    figure = get_figure("seepage_network_reference_overlay")

    assert isinstance(figure, SeepageNetworkReferenceOverlay)
    assert figure.spec.name == "seepage_network_reference_overlay"
    assert figure.spec.kind == "comparison"
    assert figure.spec.required_fields == ("release_flux",)
