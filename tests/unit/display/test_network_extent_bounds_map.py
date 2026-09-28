"""The extent-bounds map draws both extents beside both maps, or refuses by name.

The run is the monthly V-valley of :mod:`tests.unit.results._transient_network_run`:
the whole axis flows in winter and the outlet alone in summer, so the maximal
extent is the axis and the minimal one the outlet. The maximal map is the axis,
the minimal map its two southern cells.
"""

from __future__ import annotations

import pytest

from hydromodpy.display.figures.network_extent_bounds_map import NetworkExtentBoundsMap
from tests.unit.display._network_comparison_run import legend_labels, legend_note
from tests.unit.results._transient_network_run import transient_run


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def test_a_transient_run_with_both_maps_is_drawn() -> None:
    assert NetworkExtentBoundsMap().unavailable_reason(transient_run()) is None


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
    run.has_field = lambda variable, **_: variable in {"release_flux", "topography"}
    return run


def test_a_geometric_threshold_draws_a_run_without_recharge(mpl) -> None:
    """Tau zero needs no recharge; the guard reads the tau the caller passed."""
    fig, ax = mpl.subplots()
    NetworkExtentBoundsMap().render(_without_recharge(), ax, tau_specific_ratio=0.0)

    assert "seepage closure, tau = 0," in legend_note(ax)


def test_the_default_threshold_on_a_run_without_recharge_is_told_so(mpl) -> None:
    fig, ax = mpl.subplots()
    with pytest.raises(ValueError, match="persisted no recharge budget"):
        NetworkExtentBoundsMap().render(_without_recharge(), ax)


def test_both_bounds_count_each_extent_and_each_map(mpl) -> None:
    fig, ax = mpl.subplots()
    NetworkExtentBoundsMap().render(transient_run(), ax)

    assert legend_labels(ax) == [
        "simulated minimal extent (1 cell)",
        "maximal extent beyond it (2 cells)",
        "minimal map (2 cells)",
        "maximal map beyond it (1 cell)",
    ]
    note = legend_note(ax)
    assert "minimal: 1 valid, 0 excess, 1 missing" in note
    assert "maximal: 3 valid, 0 excess, 0 missing" in note
    assert "kept in >= 1 of 2 complete year(s) (2001-2002" in note
    assert "visible flow 1 L/s" in note
    assert "climatological extents over 2001-2002" in ax.get_title()


def test_one_bound_draws_its_valid_excess_and_missing_cells(mpl) -> None:
    fig, ax = mpl.subplots()
    NetworkExtentBoundsMap().render(transient_run(), ax, bound="minimal", year=2002)

    assert legend_labels(ax) == [
        "valid: simulated and mapped (1 cell)",
        "excess: simulated only (0 cells)",
        "missing: mapped only (1 cell)",
    ]
    assert "year 2002" in ax.get_title()


def test_the_rules_move_the_extents(mpl) -> None:
    """A visible flow above the summer release leaves no minimal extent."""
    fig, ax = mpl.subplots()
    NetworkExtentBoundsMap().render(transient_run(), ax, visible_flow="5 L/s")

    assert legend_labels(ax)[0] == "simulated minimal extent (0 cells)"


def test_a_year_the_run_does_not_cover_whole_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()
    with pytest.raises(ValueError, match="not a complete year"):
        NetworkExtentBoundsMap().render(transient_run(), ax, year=2003)


def test_an_unknown_bound_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()
    with pytest.raises(ValueError, match="bound must be"):
        NetworkExtentBoundsMap().render(transient_run(), ax, bound="permanent")


def _sealed(**extent) -> dict:
    """A snapshot whose one network output scored two bounds by ``extent``."""
    return {
        "calibration": {
            "outputs": {
                "streams": {
                    "support": "network",
                    "observed_network": "data.hydrography",
                    "minimal_observed_network": "data.hydrography",
                    "tau_specific_ratio": 0.0,
                    "extent": extent,
                }
            }
        }
    }


def test_the_counts_are_said_to_be_scored_cells(mpl) -> None:
    fig, ax = mpl.subplots()
    NetworkExtentBoundsMap().render(transient_run(), ax)

    note = legend_note(ax)
    assert "maximal: 3 valid, 0 excess, 0 missing scored cell(s)" in note
    assert "in the catchment" not in note


def test_the_map_draws_the_rules_the_run_was_scored_by(mpl) -> None:
    run = transient_run()
    run.config_snapshot = _sealed(visible_flow="5 L/s")
    fig, ax = mpl.subplots()
    NetworkExtentBoundsMap().render(run, ax)

    assert legend_labels(ax)[0] == "simulated minimal extent (0 cells)"
    note = legend_note(ax)
    assert "seepage closure, tau = 0, visible flow 5 L/s" in note
    assert "criterion settings: calibration output 'streams'" in note


def test_a_rule_the_caller_names_wins_over_the_run(mpl) -> None:
    run = transient_run()
    run.config_snapshot = _sealed(visible_flow="5 L/s")
    fig, ax = mpl.subplots()
    NetworkExtentBoundsMap().render(run, ax, visible_flow="1 L/s")

    assert legend_labels(ax)[0] == "simulated minimal extent (1 cell)"


def test_a_run_without_a_sealed_output_says_it_reads_the_defaults(mpl) -> None:
    fig, ax = mpl.subplots()
    NetworkExtentBoundsMap().render(transient_run(), ax)

    assert "criterion settings: the defaults" in legend_note(ax)


def test_the_guard_reads_the_threshold_the_run_was_scored_by() -> None:
    """A trial scored at tau = 0 needed no recharge; the guard does not ask for one."""
    run = _without_recharge()
    assert NetworkExtentBoundsMap().unavailable_reason(run) is not None

    run.config_snapshot = _sealed()
    assert NetworkExtentBoundsMap().unavailable_reason(run) is None


def test_the_years_are_those_of_the_scoring_window_the_run_sealed(mpl) -> None:
    """A trial that left 2001 out as spin-up scored 2002 alone; so does the map."""
    run = transient_run()
    run.config_snapshot = _sealed()
    run.config_snapshot["calibration"]["scoring_window"] = {"start": "2002-01-01", "end": None}
    fig, ax = mpl.subplots()
    NetworkExtentBoundsMap().render(run, ax)

    note = legend_note(ax)
    assert "kept in >= 1 of 1 complete year(s) (2002-2002" in note
    assert "outside the scoring window: 2001" in note
    assert "scoring_window 2002-01-01 to open" in note
    assert "climatological extents over 2002" in ax.get_title()


def test_a_scoring_window_holding_no_complete_year_is_told_so() -> None:
    run = transient_run()
    run.config_snapshot = _sealed()
    run.config_snapshot["calibration"]["scoring_window"] = {
        "start": "2001-03-01",
        "end": "2002-06-30",
    }

    reason = NetworkExtentBoundsMap().unavailable_reason(run)

    assert reason is not None
    assert "scoring window holds no complete calendar year" in reason
    assert "2001, 2002" in reason
