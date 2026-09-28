"""Persistence and intermittence count flowing as the network criterion does.

The run is the monthly V-valley of :mod:`tests.unit.results._transient_network_run`:
the outlet releases two litres per second in summer and floods from the head
of the axis in winter, so it flows every month; the two upper axis cells flow
five months of twelve; a hillslope cell never flows. "Flowing" is the seepage
closure on the criterion graph above the visible flow, so a visible flow above
two litres per second makes the outlet seasonal too. The answers are written
here rather than read back from the figure, because the whole point of both
maps is the count.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.display.figures._flow_persistence import cycle_flow, cycles
from hydromodpy.display.figures.flow_intermittence_map import FlowIntermittenceMap
from hydromodpy.display.figures.flow_persistence_map import FlowPersistenceMap
from tests.unit.results._transient_network_run import (
    HEAD,
    HILLSLOPE,
    MIDDLE,
    OUTLET,
    WINTER_MONTHS,
    transient_run,
)

SEASONAL_SHARE = 100.0 * len(WINTER_MONTHS) / 12.0


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _drawn(ax) -> np.ndarray:
    """Values the face collection was handed, masked where nothing was drawn."""
    return np.asarray(ax.collections[0].get_array())


def test_the_cycles_follow_the_calendar_and_not_a_fixed_block_length() -> None:
    blocks = cycles(transient_run(n_steps=24), 24)
    assert list(blocks) == ["2001", "2002"]
    assert [len(steps) for steps in blocks.values()] == [12, 12]


def test_a_period_end_on_the_next_month_does_not_open_a_thirteenth_cycle() -> None:
    """The December of a run stamped on period bounds belongs to its own year."""
    blocks = cycles(transient_run(n_steps=24, exclusive_bounds=True), 24)
    assert list(blocks) == ["2001", "2002"]
    assert [len(steps) for steps in blocks.values()] == [12, 12]


def test_a_run_without_a_time_axis_keeps_one_block_and_says_so() -> None:
    blocks = cycles(transient_run(with_time=False), 27)
    assert list(blocks) == ["the whole run"]
    assert len(blocks["the whole run"]) == 27


def test_each_cycle_counts_the_steps_a_cell_flows() -> None:
    flow = cycle_flow(transient_run())

    assert flow.labels == ("2001", "2002", "2003")
    steps, counts = flow.block("2002")
    assert steps.size == 12
    assert counts[[OUTLET, MIDDLE, HEAD, HILLSLOPE]].tolist() == [12, 5, 5, 0]


def test_the_persistence_share_is_the_fraction_of_steps_flowing(mpl) -> None:
    fig, ax = mpl.subplots()
    FlowPersistenceMap().render(transient_run(n_steps=24), ax, overlays=())
    drawn = _drawn(ax)

    assert drawn[OUTLET] == pytest.approx(100.0)
    assert drawn[HEAD] == pytest.approx(SEASONAL_SHARE)
    assert not np.isfinite(drawn[HILLSLOPE])
    note = ax.figure.legends[0].get_title().get_text()
    assert "a cell downstream of seepage flows from 1 L/s" in note
    assert "tau" not in note and "tau" not in ax.get_title()


def test_the_persistence_share_can_be_read_over_one_cycle_like_intermittence(mpl) -> None:
    """Same window, same cells: the head flows five steps of twelve."""
    fig, ax = mpl.subplots()
    FlowPersistenceMap().render(transient_run(), ax, cycle="2002", overlays=())
    drawn = _drawn(ax)

    assert drawn[OUTLET] == pytest.approx(100.0)
    assert drawn[HEAD] == pytest.approx(SEASONAL_SHARE)


def test_a_visible_flow_above_the_summer_release_makes_the_outlet_seasonal(mpl) -> None:
    fig, ax = mpl.subplots()
    FlowPersistenceMap().render(
        transient_run(), ax, cycle="2002", visible_flow="5 L/s", overlays=()
    )

    assert _drawn(ax)[OUTLET] == pytest.approx(SEASONAL_SHARE)


def test_persistence_refuses_a_cycle_the_run_does_not_have(mpl) -> None:
    fig, ax = mpl.subplots()
    with pytest.raises(ValueError, match="no cycle"):
        FlowPersistenceMap().render(transient_run(), ax, cycle="1999", overlays=())


def test_intermittence_separates_the_cell_that_stops_from_the_one_that_does_not(mpl) -> None:
    fig, ax = mpl.subplots()
    FlowIntermittenceMap().render(transient_run(), ax, cycle="2002", overlays=())
    drawn = _drawn(ax)

    assert drawn[OUTLET] == pytest.approx(0.0)
    assert drawn[HEAD] == pytest.approx(1.0)
    assert not np.isfinite(drawn[HILLSLOPE])


def test_intermittence_defaults_to_the_last_complete_cycle(mpl) -> None:
    """March 2003 alone would call the winter head perennial."""
    fig, ax = mpl.subplots()
    FlowIntermittenceMap().render(transient_run(), ax, overlays=())

    assert "2002" in ax.get_title()
    assert _drawn(ax)[HEAD] == pytest.approx(1.0)


@pytest.mark.parametrize("figure", [FlowPersistenceMap, FlowIntermittenceMap])
def test_both_maps_refuse_a_run_they_cannot_count_on(figure) -> None:
    assert figure().unavailable_reason(transient_run()) is None
    assert "timestep" in figure().unavailable_reason(transient_run(n_steps=1))
    no_network = figure().unavailable_reason(transient_run(roles=()))
    assert no_network is not None
    assert "hydrographic network" in no_network
