"""Extent-bounds map: simulated and mapped network extents, minimal and maximal, side by side.

The run is the monthly V-valley of :mod:`tests._helpers.transient_network_run`.
The whole axis flows in winter and the outlet alone in summer, so the maximal
extent is the axis and the minimal one is the outlet. The maximal map is the
axis and the minimal map is its two southern cells.
"""

from __future__ import annotations

import pytest

from hydromodpy.display.figures.network_extent_bounds_map import NetworkExtentBoundsMap
from hydromodpy.results.run.descent import RunDescent
from tests._helpers.sealed_runs import sealed_search
from tests._helpers.transient_network_run import transient_run
from tests.unit.display._network_comparison_run import legend_labels, legend_note


def without_recharge():
    run = transient_run()
    kept = run.descent
    run.descent = RunDescent(
        kept.view,
        load_open_water=kept.open_water,
        load_catchment_cells=kept.catchment_cells,
        load_recharge=lambda: None,
    )
    return run


def sealed(**extent) -> dict:
    """A search whose one network output scored two bounds by ``extent``."""
    return {
        "outputs": {
            "streams": {
                "support": "network",
                "model": {"seepage_threshold": 0.0, "extent": extent},
                "map": {"complete": "data.hydrography", "permanent": "data.hydrography"},
            }
        }
    }


UNAVAILABLE = [
    pytest.param({"n_steps": 1}, "steady", id="steady run"),
    pytest.param({"with_minimal": False}, "one map only", id="one map missing"),
]


@pytest.mark.parametrize(("run_kwargs", "fragment"), UNAVAILABLE)
def test_unavailable_reason(run_kwargs, fragment) -> None:
    reason = NetworkExtentBoundsMap().unavailable_reason(transient_run(**run_kwargs))

    assert reason is not None
    assert fragment in reason


def test_zero_threshold_draws_a_run_without_recharge(mpl) -> None:
    # Tau zero needs no recharge, and the guard reads the tau the caller passed.
    fig, ax = mpl.subplots()

    NetworkExtentBoundsMap().render(without_recharge(), ax, tau_specific_ratio=0.0)

    assert "every cell releasing groundwater counts as seepage;" in legend_note(ax)


def test_guard_reads_the_threshold_the_run_was_scored_by() -> None:
    # A trial scored at tau = 0 needed no recharge, so the guard does not ask for one.
    run = without_recharge()
    assert NetworkExtentBoundsMap().unavailable_reason(run) is not None

    run.dir = sealed_search(sealed())

    assert NetworkExtentBoundsMap().unavailable_reason(run) is None


def test_one_bound_draws_valid_excess_and_missing_cells(mpl) -> None:
    fig, ax = mpl.subplots()

    NetworkExtentBoundsMap().render(transient_run(), ax, bound="minimal", year=2002)

    assert legend_labels(ax) == [
        "valid: simulated and mapped (1 cell)",
        "excess: simulated only (0 cells)",
        "missing: mapped only (1 cell)",
    ]
    assert "year 2002" in ax.get_title()


def test_years_are_those_of_the_sealed_scoring_window(mpl) -> None:
    # A trial that left 2001 out as spin-up scored 2002 alone, and so does the map.
    run = transient_run()
    run.dir = sealed_search({**sealed(), "window": {"start": "2002-01-01"}})
    fig, ax = mpl.subplots()

    NetworkExtentBoundsMap().render(run, ax)

    note = legend_note(ax)
    assert "kept in >= 1 of 1 complete year(s) (2002-2002" in note
    assert "outside the scoring window: 2001" in note
    assert "window 2002-01-01 to open" in note
    assert "climatological extents over 2002" in ax.get_title()


def test_window_without_a_complete_year_is_unavailable() -> None:
    run = transient_run()
    run.dir = sealed_search({**sealed(), "window": {"start": "2001-03-01", "end": "2002-06-30"}})

    reason = NetworkExtentBoundsMap().unavailable_reason(run)

    assert reason is not None
    assert "scoring window holds no complete calendar year" in reason
    assert "2001, 2002" in reason


REFUSALS = [
    pytest.param({"year": 2003}, "not a complete year", id="year not covered whole"),
    pytest.param({"bound": "permanent"}, "bound must be", id="unknown bound"),
]


@pytest.mark.parametrize(("kwargs", "message"), REFUSALS)
def test_refusals(mpl, kwargs, message) -> None:
    fig, ax = mpl.subplots()

    with pytest.raises(ValueError, match=message):
        NetworkExtentBoundsMap().render(transient_run(), ax, **kwargs)


def test_default_threshold_needs_the_recharge(mpl) -> None:
    fig, ax = mpl.subplots()

    with pytest.raises(ValueError, match="kept no criterion mean recharge"):
        NetworkExtentBoundsMap().render(without_recharge(), ax)
