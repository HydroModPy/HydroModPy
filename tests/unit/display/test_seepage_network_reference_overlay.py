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

from hydromodpy.display.figures.seepage_network_reference_overlay import (
    _SIMULATED_INSET,
    HALO_WEIGHT_PT,
    NETWORK_COLORS,
    NETWORK_HALO,
    RELIEF_GREYS,
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
    legend_labels,
    legend_note,
)
from ._render_helpers import relative_luminance


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


def _contrast_ratio(one: str, other: str) -> float:
    """The WCAG contrast of two colours, which is what a print keeps or loses."""
    first, second = relative_luminance(one), relative_luminance(other)
    light, dark = max(first, second), min(first, second)
    return (light + 0.05) / (dark + 0.05)


def _collection(ax, label_prefix: str):
    return next(
        collection
        for collection in ax.collections
        if str(collection.get_label()).startswith(label_prefix)
    )


def _drawn_width_px(ax, label_prefix: str) -> tuple[float, float]:
    """Return the width of one drawn cell in pixels, without and with its stroke."""
    collection = _collection(ax, label_prefix)
    corners = ax.transData.transform(collection.get_paths()[0].vertices[:, :2])
    path = float(corners[:, 0].max() - corners[:, 0].min())
    stroke = float(collection.get_linewidth()[0]) * ax.figure.dpi / 72.0
    return path, path + stroke


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
        labels = legend_labels(ax)
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


def test_overlay_frames_everything_the_catchment_covers(mpl) -> None:
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
        labels = legend_labels(ax)
        assert "Outlet" in labels
        assert _collection(ax, "Outlet").get_offsets().tolist() == [[250.0, 50.0]]
    finally:
        mpl.close(fig)


def test_overlay_names_the_threshold_it_was_drawn_at(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(), ax, tau_specific_ratio=0.25)

    try:
        assert "tau = 0.25 of the mean recharge" in legend_note(ax)
    finally:
        mpl.close(fig)


def test_a_threshold_above_every_release_leaves_no_simulated_network(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(), ax, tau_specific_ratio=1.0e6)

    try:
        labels = legend_labels(ax)
        assert "simulated network (0 cells)" in labels
        assert "mapped network (3 cells)" in labels
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the two networks stay apart without colour
# --------------------------------------------------------------------------- #


def test_the_casing_lifts_both_networks_off_the_darkest_relief() -> None:
    # Drawn straight on the hillshade, the simulated network measured 1.32
    # against its darkest shade: invisible on screen and gone in print. What
    # a network sits on has to be the casing, and the casing has to separate
    # from the relief in turn, or the fix has only moved the collision.
    darkest = min(RELIEF_GREYS, key=relative_luminance)

    for name, color in NETWORK_COLORS.items():
        assert _contrast_ratio(color, NETWORK_HALO) >= 3.0, (
            f"the {name} network is unreadable on its own casing"
        )
        assert _contrast_ratio(color, darkest) < _contrast_ratio(color, NETWORK_HALO), (
            f"the casing must be the better ground for the {name} network"
        )
    assert _contrast_ratio(NETWORK_HALO, darkest) >= 3.0, (
        "the casing itself has to read against the relief, or it hides nothing"
    )


def test_both_networks_are_cased_before_they_are_drawn(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(), ax)

    try:
        casing = _collection(ax, "_network casing")
        observed = _collection(ax, "_observed")
        simulated = _collection(ax, "_simulated")
        assert drawn_cells(casing) == sorted(
            set(drawn_cells(observed)) | set(drawn_cells(simulated))
        ), "the casing covers the union of the two networks and nothing else"
        assert casing.get_zorder() < observed.get_zorder() < simulated.get_zorder()
        assert float(casing.get_linewidth()[0]) > float(observed.get_linewidth()[0]) > 0.0
        assert float(casing.get_linewidth()[0]) == pytest.approx(HALO_WEIGHT_PT)
    finally:
        mpl.close(fig)


def test_the_overlay_opens_on_the_catchment_and_a_caller_may_widen_it(mpl) -> None:
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(catchment_columns=[0, 1]), ax)

    try:
        assert ax.get_xlim()[1] < 3 * CELL_M
        assert "the delineated catchment" in legend_note(ax)
    finally:
        mpl.close(fig)

    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(catchment_columns=[0, 1]), ax, extent="mesh")

    try:
        assert ax.get_xlim()[1] >= NX * CELL_M
        assert "the whole mesh" in legend_note(ax)
    finally:
        mpl.close(fig)


def test_the_two_networks_stay_apart_in_greyscale() -> None:
    luminances = [relative_luminance(color) for color in NETWORK_COLORS.values()]

    assert abs(luminances[0] - luminances[1]) > 0.1, (
        "the mapped and simulated networks must survive a greyscale print, so "
        f"their lightnesses may not collide: {luminances}"
    )


def test_the_simulated_network_is_inset_so_shape_carries_the_distinction(mpl) -> None:
    # What a reader sees is the path plus the stroke around it, and the stroke
    # is set in points: it does not shrink with the map. An inset patch given
    # the weight of a cell grows back over the rim of mapped cell it is meant
    # to sit inside, and on the Nancon at the shipped figsize it covered 8.99
    # px of an 8.8 px cell, so the agreement read as a simulated network with
    # nothing under it. The area of the path alone could not see that.
    fig = SeepageNetworkReferenceOverlay().plot(_flank_run())
    ax = fig.axes[0]

    try:
        fig.canvas.draw()
        mapped_path, mapped_drawn = _drawn_width_px(ax, "_observed")
        inset_path, inset_drawn = _drawn_width_px(ax, "_simulated")
        assert inset_path == pytest.approx(_SIMULATED_INSET * mapped_path, rel=1e-3), (
            "the simulated patch is drawn inset, so the two networks are told "
            "apart by shape and not only by colour"
        )
        assert inset_drawn == pytest.approx(inset_path), (
            "a stroke on the inset patch is the inset given back: the casing "
            "already carries the weight both networks are drawn with"
        )
        assert mapped_drawn - inset_drawn > 0.25 * mapped_drawn, (
            "a rim of mapped cell has to survive around the simulated patch"
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
        assert "no per-cell topography" in legend_note(ax)
    finally:
        mpl.close(fig)


def test_overlay_says_when_no_cell_carries_an_elevation(mpl) -> None:
    # A field of nothing but NaN prints exactly like flat white ground. Left
    # unsaid, a reader takes the blank for a relief with no talweg in it.
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(relief=np.full(NX * NY, np.nan)), ax)

    try:
        assert "relief background is missing" in legend_note(ax)
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
        assert "simulated network is empty" in legend_note(ax)
        labels = legend_labels(ax)
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
        assert "mapped network is empty" in legend_note(ax)
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
