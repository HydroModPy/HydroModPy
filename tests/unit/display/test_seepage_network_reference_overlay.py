"""The visual check of a simulated stream network against the mapped one.

The figure answers one question before any number is trusted: do the two
networks live in the same place, and does the simulated one follow the talwegs
of the routing surface. Both come from the run itself, so the tests drive it
the way a ``[display].figures`` entry does and assert on the two networks the
run's release flux implies, on the relief behind them, on the pair staying
apart without color, and on what the figure says when one of them is empty.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.display.figures.seepage_network_reference_overlay import (
    _SIMULATED_INSET,
    HALO_WEIGHT_PT,
    SeepageNetworkReferenceOverlay,
)
from hydromodpy.display.style import relative_luminance

from ._network_comparison_run import (
    AXIS_COLUMN,
    CELL_M,
    NX,
    NY,
    cell,
    comparison_run,
    drawn_cells,
    legend_labels,
    legend_note,
)


def _flank_run(**kwargs):
    """A run whose stream climbs two cells up the northern east flank.

    Its water crosses those two cells and then runs down the mapped column, so
    the simulated network is the map plus the two cells of the flank.
    """
    return comparison_run(seepage_cells=[cell(4, 2)], **kwargs)


def _contrast_ratio(one: str, other: str) -> float:
    """The WCAG contrast of two colors, which is what a print keeps or loses."""
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
# the two networks stay apart without color
# --------------------------------------------------------------------------- #


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
            "apart by shape and not only by color"
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


def test_overlay_names_what_it_needs_when_the_run_kept_no_release_flux() -> None:
    reason = SeepageNetworkReferenceOverlay().unavailable_reason(comparison_run(with_release=False))

    assert reason is not None
    assert "release_flux" in reason
