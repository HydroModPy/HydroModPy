"""Overlay of the simulated stream network on the mapped one, on a relief background.

The grid cells are CELL_M metres wide. The tests draw the figure as a
``[display].figures`` entry does and read the two networks, the relief, the
casing that keeps the pair apart without color, and the notes for an empty network.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.display.figures.seepage_network_reference_overlay import (
    _SIMULATED_INSET,
    HALO_WEIGHT_PT,
    SeepageNetworkReferenceOverlay,
)

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


def test_threshold_above_every_release(mpl):
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(), ax, tau_specific_ratio=1.0e6)

    labels = legend_labels(ax)
    assert "simulated network (0 cells)" in labels
    assert "mapped network (3 cells)" in labels


def test_networks_are_cased(mpl):
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(), ax)

    casing = _collection(ax, "_network casing")
    observed = _collection(ax, "_observed")
    simulated = _collection(ax, "_simulated")
    assert drawn_cells(casing) == sorted(
        set(drawn_cells(observed)) | set(drawn_cells(simulated))
    ), "the casing covers the union of the two networks and nothing else"
    assert casing.get_zorder() < observed.get_zorder() < simulated.get_zorder()
    assert float(casing.get_linewidth()[0]) > float(observed.get_linewidth()[0]) > 0.0
    assert float(casing.get_linewidth()[0]) == pytest.approx(HALO_WEIGHT_PT)


def test_extent_catchment_or_mesh(mpl):
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(catchment_columns=[0, 1]), ax)

    assert ax.get_xlim()[1] < 3 * CELL_M
    assert "the delineated catchment" in legend_note(ax)

    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(catchment_columns=[0, 1]), ax, extent="mesh")

    assert ax.get_xlim()[1] >= NX * CELL_M
    assert "the whole mesh" in legend_note(ax)


def test_simulated_network_is_inset(mpl):
    # What a reader sees is the path plus the stroke around it, and the stroke
    # is set in points: it does not shrink with the map. An inset patch given
    # the weight of a cell grows back over the rim of mapped cell it is meant
    # to sit inside, and on the Nancon at the shipped figsize it covered 8.99
    # px of an 8.8 px cell, so the agreement read as a simulated network with
    # nothing under it. The area of the path alone could not see that.
    fig = SeepageNetworkReferenceOverlay().plot(_flank_run())
    ax = fig.axes[0]

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


def test_flat_ground_one_shade(mpl):
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(
        _flank_run(relief=np.full(NX * NY, 120.0)),
        ax,
    )

    relief = _collection(ax, "_relief")
    shading = np.asarray(relief.get_array(), dtype=float)
    assert np.allclose(shading, shading[0])
    assert 0.0 < float(shading[0]) < 1.0
    assert relief.get_clim() == (0.0, 1.0), (
        "ground with no relief keeps the full grey scale; stretching a "
        "spread of zero would print rounding noise as topography"
    )


def test_gentle_relief_is_stretched(mpl):
    # A shallow valley lights within a narrow band of the theoretical range.
    # Left on that range it prints as one flat plate and no talweg reads.
    gentle = np.asarray(
        [abs(column - AXIS_COLUMN) * 8.0 for _row in range(NY) for column in range(NX)],
        dtype=float,
    )
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(relief=gentle), ax)

    relief = _collection(ax, "_relief")
    shading = np.asarray(relief.get_array(), dtype=float)
    assert shading.max() - shading.min() < 0.2, "the synthetic relief is a gentle one"
    low, high = relief.get_clim()
    assert low > 0.3 and high < 0.95
    assert low == pytest.approx(float(np.percentile(shading, 2.0)))
    assert high == pytest.approx(float(np.percentile(shading, 98.0)))


def test_no_topography_note(mpl):
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(with_relief=False), ax)

    assert not [
        collection
        for collection in ax.collections
        if str(collection.get_label()).startswith("_relief")
    ]
    assert "no per-cell topography" in legend_note(ax)


# Each row is the run's options and a part of the note the legend must carry.
# A field of only NaN prints like flat white ground, and a mapped column outside
# the delineated catchment scores nothing, so the figure says so instead of drawing
# the simulated network alone as if it agreed.
NOTES = [
    pytest.param(
        {"relief": np.full(NX * NY, np.nan)}, "relief background is missing", id="relief all NaN"
    ),
    pytest.param(
        {"catchment_columns": [0, 1]}, "mapped network is empty", id="mapped network outside"
    ),
]


@pytest.mark.parametrize(("options", "note"), NOTES)
def test_legend_note(mpl, options, note):
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(_flank_run(**options), ax)

    assert note in legend_note(ax)


def test_missing_release_flux():
    reason = SeepageNetworkReferenceOverlay().unavailable_reason(comparison_run(with_release=False))

    assert reason is not None
    assert "release_flux" in reason


def test_relief_size_refused(mpl):
    fig, ax = mpl.subplots()

    with pytest.raises(ValueError, match=f"the mesh holds {NX * NY}"):
        SeepageNetworkReferenceOverlay().render(_flank_run(relief=np.arange(5.0)), ax)
