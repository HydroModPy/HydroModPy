"""The cost profile of one calibrated parameter, and its asymmetry.

The figure is driven exactly as a session drives it: one row per trial, the
sampled parameter nested under ``parameters`` and the cost written at the top
level under ``objective_value``, which is where the session journal puts it.

The interval it shades is the one the calibration summary reports, read by the
same rule: one mesh cell on network distances in metres, five per cent of the
best cost otherwise. The trial it marks is the one the calibration returned.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.calibration_progress import _read_search
from hydromodpy.display.figures.parameter_cost_profile import ParameterCostProfileFigure
from hydromodpy.display.style import HIGH_CONTRAST_TRIPLET

from ._calibration_journal import (
    K_SPACE,
    NETWORK_CONFIG,
    TWO_ROOT_CONFIG,
    TWO_ROOTS,
    journal_run,
    steady_bisection_rows,
    two_root_rows,
)


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


class _Run(SimpleNamespace):
    """A Run carrying one calibration session and nothing else."""

    def has_table(self, name: str) -> bool:
        return name == "calibration_iterations"

    def has_field(self, name: str) -> bool:
        return False


def _session_run(
    parameter_values: list[float],
    costs: list[float | None],
    *,
    statuses: list[str] | None = None,
    parameter: str = "K_over_R",
    name: str = "cheze-sweep",
) -> _Run:
    """One row per trial, in the shape the session journal writes."""
    rows = []
    for index, (value, cost) in enumerate(zip(parameter_values, costs, strict=True)):
        rows.append(
            {
                "iteration": index,
                "parameters": {parameter: {"value": value}},
                "objective_value": cost,
                "status": (
                    statuses[index]
                    if statuses is not None
                    else ("completed" if cost is not None else "failed")
                ),
            }
        )
    return _Run(
        sim_id="sim-cheze",
        name=name,
        calibration_iterations=pd.DataFrame(rows),
    )


def _asymmetric_run(**kwargs) -> _Run:
    """A profile steep below the optimum and flat above it.

    Five per cent of the best cost puts the threshold at 1.05: the trials at
    3e-05, 1e-04, 1e-03 and 1e-02 stay under it, so the interval is a factor
    10/3 below the best and 100 above it.
    """
    return _session_run(
        [1e-6, 1e-5, 3e-5, 1e-4, 1e-3, 1e-2, 1e-1],
        [20.0, 3.0, 1.03, 1.0, 1.02, 1.04, 5.2],
        **kwargs,
    )


def _profile(ax):
    return next(line for line in ax.lines if str(line.get_label()).startswith("cost:"))


def _scatter(ax, prefix: str):
    return next(
        collection
        for collection in ax.collections
        if str(collection.get_label()).startswith(prefix)
    )


def _band_bounds(ax) -> tuple[float, float]:
    patch = next(item for item in ax.patches if str(item.get_label()).startswith("within"))
    if hasattr(patch, "get_width"):
        return float(patch.get_x()), float(patch.get_x() + patch.get_width())
    xs = np.asarray(patch.get_xy())[:, 0]
    return float(xs.min()), float(xs.max())


def _note(ax) -> str:
    return ax.texts[0].get_text()


# --------------------------------------------------------------------------- #
# the profile itself
# --------------------------------------------------------------------------- #


def test_profile_draws_the_cost_against_the_parameter(mpl) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(_asymmetric_run(), ax)

    try:
        assert ax.get_xlabel() == "K_over_R (-)"
        assert ax.get_ylabel() == "Cost (-)"
        assert _profile(ax).get_xdata().tolist() == [1e-6, 1e-5, 3e-5, 1e-4, 1e-3, 1e-2, 1e-1]
        assert _profile(ax).get_ydata().tolist() == [20.0, 3.0, 1.03, 1.0, 1.02, 1.04, 5.2]
        assert "cheze-sweep" in ax.get_title()
    finally:
        mpl.close(fig)


def test_profile_uses_a_log_axis_when_the_sweep_walked_the_decades(mpl) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(_asymmetric_run(), ax)

    try:
        assert ax.get_xscale() == "log"
    finally:
        mpl.close(fig)


def test_profile_stays_linear_when_the_sweep_stayed_inside_one_decade(mpl) -> None:
    run = _session_run([1.0, 2.0, 3.0, 4.0], [9.0, 1.0, 1.5, 8.0])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert ax.get_xscale() == "linear"
    finally:
        mpl.close(fig)


def test_profile_refuses_a_log_axis_over_a_non_positive_parameter(mpl) -> None:
    run = _session_run([0.0, 1.0, 2.0], [9.0, 1.0, 8.0])
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="non-positive"):
            ParameterCostProfileFigure().render(run, ax, log_scale=True)
    finally:
        mpl.close(fig)


def test_profile_sorts_the_trials_along_the_parameter(mpl) -> None:
    run = _session_run([1e-3, 1e-5, 1e-4], [1.2, 3.0, 1.0])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert _profile(ax).get_xdata().tolist() == [1e-5, 1e-4, 1e-3]
        assert _profile(ax).get_ydata().tolist() == [3.0, 1.0, 1.2]
    finally:
        mpl.close(fig)


def test_profile_marks_the_best_trial(mpl) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(_asymmetric_run(), ax)

    try:
        best = next(line for line in ax.lines if str(line.get_label()).startswith("best trial"))
        assert best.get_xdata().tolist() == [1e-4]
        assert best.get_ydata().tolist() == [1.0]
        assert "0.0001" in str(best.get_label())
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# a failed trial breaks the profile
# --------------------------------------------------------------------------- #


def test_profile_breaks_where_a_trial_failed_and_keeps_its_abscissa(mpl) -> None:
    run = _session_run([1e-5, 1e-4, 1e-3], [3.0, None, 1.2])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        costs = _profile(ax).get_ydata()
        assert np.isnan(costs[1]), "a failed trial must break the line, not read as zero"
        assert costs[0] == 3.0 and costs[2] == 1.2
        assert _profile(ax).get_xdata().tolist() == [1e-5, 1e-4, 1e-3]
    finally:
        mpl.close(fig)


def test_profile_marks_where_the_failures_are_along_the_axis(mpl) -> None:
    run = _session_run([1e-5, 1e-4, 1e-3, 1e-2], [None, 1.0, 1.2, None])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        failed = _scatter(ax, "failed trial")
        assert failed.get_offsets()[:, 0].tolist() == [1e-5, 1e-2]
    finally:
        mpl.close(fig)


def test_profile_drops_a_cost_the_session_did_not_complete(mpl) -> None:
    # A trial can carry a number and still have failed; the engine reads a
    # cost only from a completed trial, and so does the figure.
    run = _session_run(
        [1e-5, 1e-4, 1e-3],
        [3.0, 0.01, 1.2],
        statuses=["completed", "failed", "completed"],
    )
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert np.isnan(_profile(ax).get_ydata()[1])
        best = next(line for line in ax.lines if str(line.get_label()).startswith("best trial"))
        assert best.get_xdata().tolist() == [1e-3]
        assert _scatter(ax, "failed trial").get_offsets()[:, 0].tolist() == [1e-4]
    finally:
        mpl.close(fig)


def test_profile_says_so_when_no_trial_produced_a_cost(mpl) -> None:
    run = _session_run([1e-5, 1e-4], [None, None])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert "no trial produced a cost" in _note(ax)
        assert not ax.patches
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the asymmetry
# --------------------------------------------------------------------------- #


def test_profile_draws_the_interval_of_trials_within_five_per_cent(mpl) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(_asymmetric_run(), ax)

    try:
        low, high = _band_bounds(ax)
        assert (low, high) == pytest.approx((3e-5, 1e-2))
        labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert "within 5% of the best" in labels
    finally:
        mpl.close(fig)


def test_profile_names_both_half_widths_and_which_one_is_wider(mpl) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(_asymmetric_run(), ax)

    try:
        note = _note(ax)
        assert "K_over_R in [3e-05, 0.01]: 4 of 7 trials scored within 5% of the best" in note
        assert "/3.333 below" in note
        assert "x100 above" in note
        assert "30x wider above" in note
    finally:
        mpl.close(fig)


def test_profile_reports_half_widths_as_differences_on_a_linear_axis(mpl) -> None:
    run = _session_run([0.0, 1.0, 2.0, 3.0, 4.0], [5.0, 1.02, 1.0, 1.04, 3.0])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        note = _note(ax)
        assert "-1 below" in note
        assert "+1 above" in note
    finally:
        mpl.close(fig)


def test_profile_says_so_when_the_sweep_never_rises_above_the_tolerance(mpl) -> None:
    run = _session_run([1e-5, 1e-4, 1e-3], [1.0, 1.0, 1.0])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        note = _note(ax)
        assert "no trial rose above the tolerance" in note
        low, high = _band_bounds(ax)
        assert (low, high) == pytest.approx((1e-5, 1e-3))
    finally:
        mpl.close(fig)


def test_profile_says_which_side_is_open(mpl) -> None:
    run = _session_run([1e-5, 1e-4, 1e-3], [9.0, 1.0, 1.04])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert "above is open" in _note(ax)
    finally:
        mpl.close(fig)


def test_profile_says_when_an_end_stops_at_a_failed_trial(mpl) -> None:
    run = _session_run([1e-5, 3e-5, 1e-4, 1e-3, 1e-2], [9.0, 1.02, 1.0, None, 1.5])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert "above stops at a failed trial" in _note(ax)
    finally:
        mpl.close(fig)


def test_profile_says_so_when_no_other_trial_is_within_the_tolerance(mpl) -> None:
    run = _session_run([1e-5, 1e-4, 1e-3], [9.0, 1.0, 2.0])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert "no other trial within 5% of the best, over 3 trials" in _note(ax)
        assert not ax.patches
    finally:
        mpl.close(fig)


def test_profile_says_so_when_the_best_sits_on_a_search_bound(mpl) -> None:
    # Example 04's grid: K = 1e-06 is the lowest cost and the lower bound, which
    # the calibration warns about and the profile said nothing of.
    run = _session_run([1e-6, 3.16e-6, 1e-5], [0.358, 0.464, 0.521], parameter="K")
    run.calibration_iterations["parameters"] = [
        {"K": {**block["K"], "bounds": [1e-6, 1e-4], "units": "m/s"}}
        for block in run.calibration_iterations["parameters"]
    ]
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert "on the lower search bound" in _note(ax)
    finally:
        mpl.close(fig)


def test_profile_says_so_when_the_optimum_cost_is_not_positive(mpl) -> None:
    run = _session_run([1e-5, 1e-4, 1e-3], [1.0, 0.0, 2.0])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert "a relative width is a fraction of the best cost" in _note(ax)
        assert not ax.patches
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the calibration's own interval and returned trial (example 04)
# --------------------------------------------------------------------------- #


def _steady_run(tmp_path):
    return journal_run(
        tmp_path,
        steady_bisection_rows(),
        method="bisection",
        phase="steady_conductivity",
        config=NETWORK_CONFIG,
        search_space=K_SPACE,
        best_trial=15,
        root_search={"bracket": {"parameter": "K", "low": 8.0584e-05, "high": 8.1069e-05}},
    )


def test_a_distance_cost_reads_the_interval_of_the_calibration_summary(mpl, tmp_path) -> None:
    # Example 04 reported [7.499e-05, 0.0001] on the console and on the
    # progress slide, and the profile drew [8.094e-05, 8.115e-05], a +10 %
    # rise of a 1.965 m cost. One mesh cell is the width, as in the summary.
    from hydromodpy.calibration.optim.tolerance import tolerance_intervals

    run = _steady_run(tmp_path)
    rows = steady_bisection_rows()
    summary = tolerance_intervals(
        [{"K": row["parameters"]["K"]["value"], **row} for row in rows],
        ["K"],
        tolerance=75.0,
        mode="absolute",
    )[0]
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert _band_bounds(ax) == pytest.approx((summary.lower, summary.upper))
        assert (summary.lower, summary.upper) == pytest.approx((7.4989e-05, 1e-4))
        assert _read_search(run, session_id=None, output=None).intervals["K"] == pytest.approx(
            (summary.lower, summary.upper)
        )
        labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert "within one mesh cell (75 m) of the best" in labels
        note = _note(ax)
        assert "K in [7.499e-05, 0.0001] m/s: 7 of 15 trials scored within one mesh cell" in note
    finally:
        mpl.close(fig)


def test_the_axes_name_the_units_of_the_parameter_and_of_the_cost(mpl, tmp_path) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(_steady_run(tmp_path), ax)

    try:
        assert ax.get_xlabel() == "K (m/s)"
        assert ax.get_ylabel() == "|D_so - D_os| (m)"
    finally:
        mpl.close(fig)


def test_an_efficiency_cost_is_dimensionless(mpl, tmp_path) -> None:
    config = {
        "method": "scipy_nelder_mead",
        "parameters": {"Sy": {"bounds": [0.005, 0.35], "transform": "log", "units": "-"}},
        "objective_blocks": [
            {"name": "hydrograph", "metric": "nse_log", "weight": 1.0, "normalize_cost": False}
        ],
    }
    values = [0.028, 0.042, 0.044, 0.045, 0.047, 0.052, 0.064]
    costs = [0.118, 0.0846, 0.0840, 0.0840, 0.0842, 0.0863, 0.0973]
    rows = [
        {
            "trial": trial,
            "status": "completed",
            "objective_value": cost,
            "parameters": {"Sy": {"value": value, "units": "-"}},
            "metrics": {"hydrograph.raw_cost": cost},
        }
        for trial, (value, cost) in enumerate(zip(values, costs, strict=True), start=1)
    ]
    run = journal_run(
        tmp_path,
        rows,
        method="scipy_nelder_mead",
        phase="transient_storage",
        config=config,
        search_space={"Sy": {"bounds": [0.005, 0.35], "units": "-"}},
        best_trial=4,
    )
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert ax.get_ylabel() == "1 - NSElog (-)"
        assert ax.get_xlabel() == "Sy (-)"
        # Five per cent of 0.084, the width the summary and the slide read.
        assert _band_bounds(ax) == pytest.approx((0.042, 0.052))
        assert _read_search(run, session_id=None, output=None).intervals["Sy"] == pytest.approx(
            (0.042, 0.052)
        )
    finally:
        mpl.close(fig)


def _two_root_run(tmp_path):
    return journal_run(
        tmp_path,
        two_root_rows(),
        method="bisection",
        phase="transient_conductivity",
        config=TWO_ROOT_CONFIG,
        search_space=K_SPACE,
        best_trial=24,
        root_search=TWO_ROOTS,
    )


def test_the_marked_trial_is_the_one_the_calibration_returned(mpl, tmp_path) -> None:
    # The lowest cost of that search is trial 1, K = 1e-07. The calibration
    # returned the combined value of its two roots, K = 5.9e-06, trial 24.
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(_two_root_run(tmp_path), ax)

    try:
        marked = next(line for line in ax.lines if str(line.get_label()).startswith("returned"))
        assert marked.get_xdata().tolist() == [5.9e-06]
        assert "K = 5.9e-06 m/s" in str(marked.get_label())
        assert not [line for line in ax.lines if str(line.get_label()).startswith("best trial")]
    finally:
        mpl.close(fig)


def test_a_value_combined_from_two_roots_gets_no_interval(mpl, tmp_path) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(_two_root_run(tmp_path), ax)

    try:
        assert not ax.patches
        note = " ".join(_note(ax).split())
        assert "no interval of trials around a value combined from two roots" in note
        assert "Delta = -1.28 decade(s)" in note
        roots = [str(line.get_label()) for line in ax.lines if "*_" in str(line.get_label())]
        assert roots == ["K*_minimal = 2.564e-05", "K*_maximal = 1.358e-06"]
    finally:
        mpl.close(fig)


def test_the_session_best_trial_wins_over_the_lowest_cost(mpl) -> None:
    run = _asymmetric_run()
    run.calibration_iterations["session_id"] = "s-1"
    run.calibration_sessions = pd.DataFrame([{"session_id": "s-1", "best_trial": 2}])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        marked = next(line for line in ax.lines if str(line.get_label()).startswith("returned"))
        assert marked.get_xdata().tolist() == [3e-5]
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the note covers neither the legend nor a trial
# --------------------------------------------------------------------------- #


def _storage_run() -> _Run:
    """The transient storage profile of example 04: its first trial sat under the note."""
    return _session_run(
        [0.02738, 0.04183, 0.04424, 0.045, 0.04653, 0.05173, 0.06398, 0.045],
        [0.1182, 0.08459, 0.08402, 0.08398, 0.08417, 0.08634, 0.09733, 0.08398],
        parameter="Sy",
    )


def test_the_note_overlaps_neither_the_legend_nor_a_trial(mpl) -> None:
    fig = ParameterCostProfileFigure().plot(_storage_run())

    try:
        fig.canvas.draw()
        ax = fig.axes[0]
        note = ax.texts[0].get_bbox_patch().get_window_extent()
        legend = ax.get_legend().get_window_extent()
        assert not note.overlaps(legend)
        points = ax.transData.transform(np.asarray(_profile(ax).get_xydata()))
        assert not any(note.contains(x, y) for x, y in points)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# one axis, one parameter
# --------------------------------------------------------------------------- #


def test_profile_refuses_a_session_that_moved_several_parameters(mpl) -> None:
    run = _asymmetric_run()
    frame = run.calibration_iterations
    frame["parameters"] = [{**block, "porosity": {"value": 0.1}} for block in frame["parameters"]]
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="K_over_R, porosity"):
            ParameterCostProfileFigure().render(run, ax)
    finally:
        mpl.close(fig)


def test_profile_reads_the_parameter_it_is_given(mpl) -> None:
    run = _asymmetric_run()
    frame = run.calibration_iterations
    frame["parameters"] = [{**block, "porosity": {"value": 0.1}} for block in frame["parameters"]]
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax, parameter="K_over_R")

    try:
        assert ax.get_xlabel() == "K_over_R (-)"
        assert _profile(ax).get_ydata().tolist() == [20.0, 3.0, 1.03, 1.0, 1.02, 1.04, 5.2]
    finally:
        mpl.close(fig)


def test_profile_reads_the_json_blocks_the_index_hands_back(mpl) -> None:
    run = _asymmetric_run()
    frame = run.calibration_iterations
    frame["parameters"] = [json.dumps(block) for block in frame["parameters"]]
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert ax.get_xlabel() == "K_over_R (-)"
        assert _profile(ax).get_ydata().tolist() == [20.0, 3.0, 1.03, 1.0, 1.02, 1.04, 5.2]
    finally:
        mpl.close(fig)


def test_profile_refuses_a_session_with_no_trial(mpl) -> None:
    run = _session_run([], [])
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="no trial"):
            ParameterCostProfileFigure().render(run, ax)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# colours, registration, availability
# --------------------------------------------------------------------------- #


def test_profile_only_uses_the_high_contrast_triplet(mpl) -> None:
    from matplotlib.colors import to_hex

    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(_asymmetric_run(), ax)

    try:
        triplet = {color.lower() for color in HIGH_CONTRAST_TRIPLET}
        drawn = {to_hex(_profile(ax).get_color()).lower()}
        best = next(line for line in ax.lines if str(line.get_label()).startswith("best trial"))
        drawn.add(to_hex(best.get_color()).lower())
        band = next(item for item in ax.patches if str(item.get_label()).startswith("within"))
        drawn.add(to_hex(band.get_facecolor()).lower())
        assert drawn <= triplet
    finally:
        mpl.close(fig)


def test_profile_is_available_on_a_run_carrying_a_session() -> None:
    assert ParameterCostProfileFigure().unavailable_reason(_asymmetric_run()) is None


def test_profile_is_skipped_on_a_run_without_a_session() -> None:
    run = SimpleNamespace(
        sim_id="sim-plain",
        name="plain",
        has_table=lambda name: False,
        has_field=lambda name: False,
    )

    reason = ParameterCostProfileFigure().unavailable_reason(run)

    assert reason is not None
    assert "calibration_iterations" in reason
