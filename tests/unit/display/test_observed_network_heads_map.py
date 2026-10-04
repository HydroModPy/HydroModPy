"""The heads map renders the trace of a redrawn run, and says when it forced the rule.

The run is the 5 x 3 V-valley of :mod:`tests.unit.display._network_comparison_run`:
one mapped line down the axis column, a free end at each end. The window and
area of ``test_the_sealed_area_moves_the_landing_cell`` keep exactly one head,
landing 140 m away, which is what makes the legend counts checkable by hand.
"""

from __future__ import annotations

import pytest

from hydromodpy.display.figures.observed_network_heads_map import ObservedNetworkHeadsMap
from tests.unit.display._network_comparison_run import comparison_run, legend_labels, legend_note


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _sealed_run(**heads):
    run = comparison_run()
    output = {
        "support": "network",
        "observed_network": "data.hydrography",
        "tau_specific_ratio": 0.0,
        "observed_rasterization": "heads",
        **heads,
    }
    run.config_snapshot = {"calibration": {"outputs": {"streams": output}}}
    return run


def test_a_run_with_the_mapped_network_is_available() -> None:
    assert ObservedNetworkHeadsMap().unavailable_reason(comparison_run()) is None


def test_a_run_without_release_flux_is_told_so() -> None:
    reason = ObservedNetworkHeadsMap().unavailable_reason(comparison_run(with_release=False))
    assert reason is not None
    assert "release_flux" in reason


def test_a_run_scored_under_heads_redraws_with_its_sealed_radius(mpl) -> None:
    run = _sealed_run(heads_snap_radius=150.0, heads_min_drained_area_km2=0.06)
    fig, ax = mpl.subplots()

    ObservedNetworkHeadsMap().render(run, ax)

    assert "1 head(s) traced, 0 lost" in ax.get_title()
    assert legend_labels(ax) == [
        "traced (2 cells)",
        "mapped network",
        "head kept (1)",
        "landing cell centre",
    ]
    note = legend_note(ax)
    assert "redrawn under observed_rasterization" not in note
    assert "criterion settings: calibration output 'streams'" in note


def test_a_run_scored_under_crossing_is_redrawn_under_heads_anyway(mpl) -> None:
    run = _sealed_run(observed_rasterization="crossing")
    fig, ax = mpl.subplots()

    ObservedNetworkHeadsMap().render(run, ax)

    note = legend_note(ax)
    assert "redrawn under observed_rasterization = 'heads'" in note
    assert legend_labels(ax) == [
        "traced (3 cells)",
        "mapped network",
        "head kept (1)",
        "landing cell centre",
    ]


def test_a_radius_the_fixture_cannot_reach_refuses_to_render(mpl) -> None:
    """A single-reach map has one head candidate: lost means none is kept."""
    run = _sealed_run(heads_snap_radius="30 m", heads_min_drained_area_km2=0.04)
    fig, ax = mpl.subplots()

    with pytest.raises(ValueError, match="snap radius 30 m"):
        ObservedNetworkHeadsMap().render(run, ax)


def test_a_run_with_permanent_reaches_draws_their_heads_too(mpl) -> None:
    """The permanent reaches start one row lower: their trace and head join the page.

    A 45 m radius keeps each map to one head on this grid of 100 m cells.
    """
    import geopandas as gpd
    from shapely.geometry import LineString

    from tests.unit.display._network_comparison_run import AXIS_COLUMN, CELL_M, CRS

    run = _sealed_run(heads_snap_radius="45 m", heads_min_drained_area_km2=0.0)
    axis_x = (AXIS_COLUMN + 0.5) * CELL_M
    permanent = gpd.GeoDataFrame(
        geometry=[LineString([(axis_x, 0.1 * CELL_M), (axis_x, 1.5 * CELL_M)])],
        crs=CRS,
    )
    full = run.hydrographic_network("reference")
    run.has_hydrographic_network = lambda role="generated": (
        role
        in (
            "reference",
            "reference_permanent",
        )
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
