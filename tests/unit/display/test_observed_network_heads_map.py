"""Heads map: the trace of a redrawn run on the mapped network, and the forced dam foot.

The run is the 5 x 3 V-valley of :mod:`tests.unit.display._network_comparison_run`
with 100 m cells. One mapped line runs down the axis column, with a free end at
each end. The sealed area keeps exactly one head, landing 140 m away, which
makes the legend counts checkable by hand. A forced head has no free end and no
landing cell, so it is a diamond of its own.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from matplotlib.colors import to_rgba

from hydromodpy.display.figures.observed_network_heads_map import (
    FORCED_HEAD_COLOR,
    ObservedNetworkHeadsMap,
)
from hydromodpy.results.run.descent import RunDescent
from tests._helpers.sealed_runs import sealed_search
from tests.unit.display._network_comparison_run import (
    AXIS_COLUMN,
    CELL_M,
    CRS,
    comparison_run,
    legend_labels,
    legend_note,
)

HILLSIDE = 10  # a cell index off the axis


def sealed_run(**map_knobs):
    run = comparison_run()
    output = {
        "support": "network",
        "model": {"seepage_threshold": 0.0},
        "map": {"complete": "data.hydrography", "drawn_by": "heads", **map_knobs},
    }
    run.dir = sealed_search({"outputs": {"streams": output}})
    return run


def run_with_dam_foot(cells):
    run = comparison_run()
    kept = run.descent
    stored = replace(kept.view(), dam_foot=np.asarray(cells, dtype=np.int64))
    run.descent = RunDescent(
        lambda: stored,
        load_open_water=kept.open_water,
        load_catchment_cells=kept.catchment_cells,
        load_recharge=kept.criterion_recharge,
    )
    return run


def test_run_with_the_mapped_network_is_available() -> None:
    assert ObservedNetworkHeadsMap().unavailable_reason(comparison_run()) is None


def test_run_without_release_flux_is_unavailable() -> None:
    reason = ObservedNetworkHeadsMap().unavailable_reason(comparison_run(with_release=False))

    assert reason is not None
    assert "release_flux" in reason


def test_run_scored_under_crossing_is_redrawn_under_heads(mpl) -> None:
    fig, ax = mpl.subplots()

    ObservedNetworkHeadsMap().render(sealed_run(drawn_by="crossing"), ax)

    assert "redrawn under map.drawn_by = 'heads'" in legend_note(ax)
    assert legend_labels(ax) == [
        "traced (3 cells)",
        "mapped network",
        "head kept (1)",
        "landing cell centre",
    ]


def test_radius_that_reaches_no_head_refuses_to_render(mpl) -> None:
    # A single-reach map has one head candidate, so a lost one leaves none.
    run = sealed_run(heads={"radius": "30 m", "min_drained_area": 0.04})
    fig, ax = mpl.subplots()

    with pytest.raises(ValueError, match="snap radius 30 m"):
        ObservedNetworkHeadsMap().render(run, ax)


def test_permanent_reaches_draw_their_heads_too(mpl) -> None:
    # The permanent reaches start one row lower, and a 45 m radius keeps each
    # map to one head on this grid of 100 m cells.
    import geopandas as gpd
    from shapely.geometry import LineString

    run = sealed_run(heads={"radius": "45 m", "min_drained_area": 0.0})
    axis_x = (AXIS_COLUMN + 0.5) * CELL_M
    permanent = gpd.GeoDataFrame(
        geometry=[LineString([(axis_x, 0.1 * CELL_M), (axis_x, 1.5 * CELL_M)])], crs=CRS
    )
    full = run.hydrographic_network("reference")
    run.has_hydrographic_network = lambda role="generated": (
        role in ("reference", "reference_permanent")
    )
    run.hydrographic_network = lambda role="generated": (
        permanent if role == "reference_permanent" else full
    )
    fig, ax = mpl.subplots()

    ObservedNetworkHeadsMap().render(run, ax)

    assert "permanent: 1 head(s) traced, 0 lost" in ax.get_title()
    labels = legend_labels(ax)
    assert "permanent trace (2 cells)" in labels
    assert "permanent head kept (1)" in labels


def test_dam_foot_has_its_own_marker_and_legend_entry(mpl) -> None:
    fig, ax = mpl.subplots()

    ObservedNetworkHeadsMap().render(run_with_dam_foot([HILLSIDE]), ax)

    assert "1 dam foot" in ax.get_title()
    assert "dam foot, forced head (1)" in legend_labels(ax)
    marked = [
        collection
        for collection in ax.collections
        if collection.get_offsets().shape[0] == 1
        and len(collection.get_facecolor())
        and np.allclose(collection.get_facecolor()[0], to_rgba(FORCED_HEAD_COLOR))
    ]
    assert len(marked) == 1
