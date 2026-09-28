"""The two snap figures draw the snap the run's own setting produced.

A mapped network one column off the talweg, snapped in ``apply``: every raw
cell moves one cell onto the axis, so the map draws one "moved" segment per
raw cell and the histogram piles every cell at one cell of displacement. A run
whose snap is off gets a sentence, not a figure.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.display.figures.observed_network_snap_histogram import (
    ObservedNetworkSnapHistogram,
)
from hydromodpy.display.figures.observed_network_snap_map import ObservedNetworkSnapMap
from tests.unit.display._network_comparison_run import (
    AXIS_COLUMN,
    CELL_M,
    NY,
    cell,
    comparison_run,
    legend_labels,
    legend_note,
)


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _shifted_run(mode: str | None):
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, row) for row in range(NY)])
    x = (AXIS_COLUMN + 1.5) * CELL_M
    network = gpd.GeoDataFrame(
        geometry=[LineString([(x, 0.1 * CELL_M), (x, (NY - 0.1) * CELL_M)])], crs=run.mesh.crs
    )
    run.hydrographic_network = lambda role="generated": network
    run.config_snapshot = None if mode is None else {"geographic": {"snap_streams": {"mode": mode}}}
    return run


@pytest.mark.parametrize("figure", [ObservedNetworkSnapMap, ObservedNetworkSnapHistogram])
def test_a_run_whose_snap_is_off_is_told_so(figure) -> None:
    reason = figure().unavailable_reason(_shifted_run(None))

    assert reason is not None
    assert "snap_streams" in reason
    assert figure().unavailable_reason(_shifted_run("diagnose")) is None


def test_the_map_draws_one_segment_per_moved_cell(mpl) -> None:
    fig, ax = mpl.subplots()
    ObservedNetworkSnapMap().render(_shifted_run("apply"), ax)

    labels = legend_labels(ax)
    assert f"moved ({NY} cells)" in labels
    assert "rejected (0 cells)" in labels
    segments = [
        collection
        for collection in ax.collections
        if str(collection.get_label()).endswith("displacement")
    ]
    assert len(segments) == 1
    lengths = [np.hypot(*np.diff(path.vertices, axis=0)[0]) for path in segments[0].get_paths()]
    assert lengths == pytest.approx([CELL_M] * NY)
    assert "floor F" in legend_note(ax)


def test_the_histogram_piles_every_cell_at_one_cell(mpl) -> None:
    fig, ax = mpl.subplots()
    ObservedNetworkSnapHistogram().render(_shifted_run("apply"), ax)

    heights = {
        round(patch.get_x() + patch.get_width() / 2.0, 6): patch.get_height()
        for patch in ax.patches
        if patch.get_height() > 0
    }
    assert sum(heights.values()) == NY
    assert list(heights) == [pytest.approx(CELL_M)]
    labels = [text.get_text() for text in ax.get_legend().get_texts()]
    assert any(label.startswith("p90 bound") for label in labels)
    assert "rejected, no displacement (0)" in labels
