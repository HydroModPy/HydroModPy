"""The extent-bounds map draws both extents beside both maps, or refuses by name.

The run is the monthly V-valley of :mod:`tests._helpers.transient_network_run`:
the whole axis flows in winter and the outlet alone in summer, so the maximal
extent is the axis and the minimal one the outlet. The maximal map is the axis,
the minimal map its two southern cells.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.display.figures.network_extent_bounds_map import NetworkExtentBoundsMap
from hydromodpy.results.run.descent import RunDescent
from tests._helpers.sealed_runs import sealed_search
from tests._helpers.transient_network_run import transient_run
from tests.unit.display._network_comparison_run import legend_labels, legend_note


def test_a_steady_run_is_told_so() -> None:
    reason = NetworkExtentBoundsMap().unavailable_reason(transient_run(n_steps=1))

    assert reason is not None
    assert "steady" in reason


def test_a_run_with_one_map_is_told_which_one_is_missing() -> None:
    reason = NetworkExtentBoundsMap().unavailable_reason(transient_run(with_minimal=False))

    assert reason is not None
    assert "one map only" in reason


def _without_recharge():
    run = transient_run()
    kept = run.descent
    run.descent = RunDescent(
        kept.view,
        load_open_water=kept.open_water,
        load_catchment_cells=kept.catchment_cells,
        load_recharge=lambda: None,
    )
    return run


def test_a_geometric_threshold_draws_a_run_without_recharge(mpl) -> None:
    """Tau zero needs no recharge; the guard reads the tau the caller passed."""
    fig, ax = mpl.subplots()
    NetworkExtentBoundsMap().render(_without_recharge(), ax, tau_specific_ratio=0.0)

    assert "every cell releasing groundwater counts as seepage;" in legend_note(ax)


def test_the_default_threshold_on_a_run_without_recharge_is_told_so(mpl) -> None:
    fig, ax = mpl.subplots()
    with pytest.raises(ValueError, match="kept no criterion mean recharge"):
        NetworkExtentBoundsMap().render(_without_recharge(), ax)


def test_one_bound_draws_its_valid_excess_and_missing_cells(mpl) -> None:
    fig, ax = mpl.subplots()
    NetworkExtentBoundsMap().render(transient_run(), ax, bound="minimal", year=2002)

    assert legend_labels(ax) == [
        "valid: simulated and mapped (1 cell)",
        "excess: simulated only (0 cells)",
        "missing: mapped only (1 cell)",
    ]
    assert "year 2002" in ax.get_title()


def test_a_year_the_run_does_not_cover_whole_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()
    with pytest.raises(ValueError, match="not a complete year"):
        NetworkExtentBoundsMap().render(transient_run(), ax, year=2003)


def test_an_unknown_bound_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()
    with pytest.raises(ValueError, match="bound must be"):
        NetworkExtentBoundsMap().render(transient_run(), ax, bound="permanent")


def _sealed(**extent) -> dict:
    """A search whose one network output scored two bounds by ``extent``."""
    return {
        "outputs": {
            "streams": {
                "support": "network",
                "model": {"seepage_threshold": 0.0, "extent": extent},
                "map": {
                    "complete": "data.hydrography",
                    "permanent": "data.hydrography",
                },
            }
        }
    }


def test_the_guard_reads_the_threshold_the_run_was_scored_by() -> None:
    """A trial scored at tau = 0 needed no recharge; the guard does not ask for one."""
    run = _without_recharge()
    assert NetworkExtentBoundsMap().unavailable_reason(run) is not None

    run.dir = sealed_search(_sealed())
    assert NetworkExtentBoundsMap().unavailable_reason(run) is None


def test_the_years_are_those_of_the_scoring_window_the_run_sealed(mpl) -> None:
    """A trial that left 2001 out as spin-up scored 2002 alone; so does the map."""
    run = transient_run()
    run.dir = sealed_search({**_sealed(), "window": {"start": "2002-01-01"}})
    fig, ax = mpl.subplots()
    NetworkExtentBoundsMap().render(run, ax)

    note = legend_note(ax)
    assert "kept in >= 1 of 1 complete year(s) (2002-2002" in note
    assert "outside the scoring window: 2001" in note
    assert "window 2002-01-01 to open" in note
    assert "climatological extents over 2002" in ax.get_title()


def test_a_scoring_window_holding_no_complete_year_is_told_so() -> None:
    run = transient_run()
    run.dir = sealed_search({**_sealed(), "window": {"start": "2001-03-01", "end": "2002-06-30"}})

    reason = NetworkExtentBoundsMap().unavailable_reason(run)

    assert reason is not None
    assert "scoring window holds no complete calendar year" in reason
    assert "2001, 2002" in reason


def _square(i: int) -> np.ndarray:
    return np.array([[i, 0], [i + 1, 0], [i + 1, 1], [i, 1]], dtype=float)


class _FakeExtents:
    """A stand-in exposing only what ``_draw_both`` reads."""

    def __init__(
        self, sim_min: np.ndarray, sim_max: np.ndarray, obs_min: np.ndarray, obs_max: np.ndarray
    ) -> None:
        self._sim = {"minimal": sim_min, "maximal": sim_max}
        self._obs = {"minimal": obs_min, "maximal": obs_max}

    def simulated(self, bound: str, *, year: int | None = None) -> np.ndarray:
        return self._sim[bound]

    def observed(self, bound: str) -> np.ndarray:
        return self._obs[bound]
