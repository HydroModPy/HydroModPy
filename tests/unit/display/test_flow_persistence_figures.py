"""Share of steps a cell flows (%) and whether it stops, counted as the network criterion does.

The run is the monthly V-valley of ``tests._helpers.transient_network_run``. The outlet
releases 2 L/s in summer and floods from the head of the axis in winter, so it flows every
month. The two upper axis cells flow five months of twelve and a hillslope cell never flows.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.display.figures._flow_persistence import cycles, flow_geometry
from hydromodpy.display.figures.flow_intermittence_map import FlowIntermittenceMap
from hydromodpy.display.figures.flow_persistence_map import FlowPersistenceMap
from tests._helpers.sealed_runs import sealed_search
from tests._helpers.transient_network_run import (
    HEAD,
    HILLSLOPE,
    MIDDLE,
    OUTLET,
    WINTER_MONTHS,
    transient_run,
)

SEASONAL_SHARE = 100.0 * len(WINTER_MONTHS) / 12.0


def _drawn(ax) -> np.ndarray:
    """Values handed to the face collection, masked where nothing was drawn."""
    return np.asarray(ax.collections[0].get_array())


def test_run_without_a_time_axis_keeps_one_block() -> None:
    blocks = cycles(transient_run(with_time=False), 27)
    assert list(blocks) == ["the whole run"]
    assert len(blocks["the whole run"]) == 27


def _sealed_heads_run(**map_knobs):
    """A transient run scored under the heads rule with the given settings."""
    run = transient_run()
    output = {
        "support": "network",
        "model": {"seepage_threshold": 0.0},
        "map": {"complete": "data.hydrography", "drawn_by": "heads", **map_knobs},
    }
    run.dir = sealed_search({"outputs": {"streams": output}})
    return run


def test_geometry_reads_the_sealed_heads_radius_and_area() -> None:
    # A run sealed under heads with a non-default radius must redraw with that
    # radius, or it counts flowing cells on a map the trial never scored.
    run = _sealed_heads_run(heads={"radius": 150.0, "min_drained_area": 0.06})

    geometry = flow_geometry(run)

    assert geometry.heads is not None
    assert geometry.heads.settings.snap_radius_m == pytest.approx(150.0)
    assert geometry.heads.settings.min_drained_area_m2 == pytest.approx(6.0e4)
    assert geometry.heads.head_cell.tolist() == [MIDDLE]


def test_persistence_share_is_the_fraction_of_steps_flowing(mpl) -> None:
    fig, ax = mpl.subplots()
    FlowPersistenceMap().render(transient_run(n_steps=24), ax, overlays=())
    drawn = _drawn(ax)

    assert drawn[OUTLET] == pytest.approx(100.0)
    assert drawn[HEAD] == pytest.approx(SEASONAL_SHARE)
    assert not np.isfinite(drawn[HILLSLOPE])
    note = ax.figure.legends[0].get_title().get_text()
    assert "a cell downstream of seepage flows from 1 L/s" in note
    assert "tau" not in note and "tau" not in ax.get_title()


def test_persistence_share_over_one_cycle(mpl) -> None:
    # Same window and cells as intermittence, the head flows five steps of twelve.
    fig, ax = mpl.subplots()
    FlowPersistenceMap().render(transient_run(), ax, cycle="2002", overlays=())
    drawn = _drawn(ax)

    assert drawn[OUTLET] == pytest.approx(100.0)
    assert drawn[HEAD] == pytest.approx(SEASONAL_SHARE)


def test_visible_flow_above_summer_release_makes_outlet_seasonal(mpl) -> None:
    fig, ax = mpl.subplots()
    FlowPersistenceMap().render(
        transient_run(), ax, cycle="2002", visible_flow="5 L/s", overlays=()
    )

    assert _drawn(ax)[OUTLET] == pytest.approx(SEASONAL_SHARE)


def test_persistence_refuses_a_missing_cycle(mpl) -> None:
    fig, ax = mpl.subplots()
    with pytest.raises(ValueError, match="no cycle"):
        FlowPersistenceMap().render(transient_run(), ax, cycle="1999", overlays=())


def test_intermittence_separates_stopping_cells(mpl) -> None:
    fig, ax = mpl.subplots()
    FlowIntermittenceMap().render(transient_run(), ax, cycle="2002", overlays=())
    drawn = _drawn(ax)

    assert drawn[OUTLET] == pytest.approx(0.0)
    assert drawn[HEAD] == pytest.approx(1.0)
    assert not np.isfinite(drawn[HILLSLOPE])


def test_intermittence_defaults_to_the_last_complete_cycle(mpl) -> None:
    # March 2003 alone would call the winter head perennial.
    fig, ax = mpl.subplots()
    FlowIntermittenceMap().render(transient_run(), ax, overlays=())

    assert "2002" in ax.get_title()
    assert _drawn(ax)[HEAD] == pytest.approx(1.0)


@pytest.mark.parametrize("figure", [FlowPersistenceMap, FlowIntermittenceMap])
def test_unavailable_reasons(figure) -> None:
    assert figure().unavailable_reason(transient_run()) is None
    assert "timestep" in figure().unavailable_reason(transient_run(n_steps=1))
    no_network = figure().unavailable_reason(transient_run(roles=()))
    assert no_network is not None
    assert "hydrographic network" in no_network
