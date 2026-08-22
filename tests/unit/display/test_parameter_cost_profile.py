"""The cost profile of one calibrated parameter, and its asymmetry.

The figure is driven exactly as a session drives it: one row per trial, the
sampled parameter nested under ``parameters`` and the cost written at the top
level under ``objective_value``, which is where the session journal puts it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.display.colormaps import HIGH_CONTRAST_TRIPLET
from hydromodpy.display.figure_registry import get as get_figure
from hydromodpy.display.figures.parameter_cost_profile import (
    ParameterCostProfileFigure,
    _tolerance_interval,
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
    import pandas as pd

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

    With a 100% rise the tolerance edges fall at 10**-4.5 and 10**-2.8, so the
    two half-widths are a factor 10**0.5 below and 10**1.2 above.
    """
    return _session_run(
        [1e-6, 1e-5, 1e-4, 1e-3, 1e-2],
        [20.0, 3.0, 1.0, 1.2, 5.2],
        **kwargs,
    )


def _profile(ax):
    return next(line for line in ax.lines if str(line.get_label()).startswith("objective"))


def _scatter(ax, prefix: str):
    return next(
        collection
        for collection in ax.collections
        if str(collection.get_label()).startswith(prefix)
    )


def _band_bounds(ax) -> tuple[float, float]:
    patch = next(item for item in ax.patches if str(item.get_label()).startswith("cost within"))
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
        assert ax.get_ylabel() == "Objective (-)"
        assert _profile(ax).get_xdata().tolist() == [1e-6, 1e-5, 1e-4, 1e-3, 1e-2]
        assert _profile(ax).get_ydata().tolist() == [20.0, 3.0, 1.0, 1.2, 5.2]
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


def test_tolerance_edges_are_interpolated_in_log_space() -> None:
    values = np.array([1e-6, 1e-5, 1e-4, 1e-3, 1e-2])
    cost = np.array([20.0, 3.0, 1.0, 1.2, 5.2])

    interval = _tolerance_interval(values, cost, best=2, threshold=2.0, log=True)

    assert interval.low == pytest.approx(10.0**-4.5)
    assert interval.high == pytest.approx(10.0**-2.8)
    assert interval.low_kind == "crossed"
    assert interval.high_kind == "crossed"


def test_tolerance_edges_are_interpolated_linearly_on_a_linear_axis() -> None:
    values = np.array([0.0, 1.0, 2.0, 3.0])
    cost = np.array([5.0, 1.0, 1.0, 3.0])

    interval = _tolerance_interval(values, cost, best=1, threshold=2.0, log=False)

    assert interval.low == pytest.approx(0.75)
    assert interval.high == pytest.approx(2.5)


def test_profile_draws_the_tolerance_band_around_the_optimum(mpl) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(_asymmetric_run(), ax, rise=1.0)

    try:
        low, high = _band_bounds(ax)
        assert low == pytest.approx(10.0**-4.5)
        assert high == pytest.approx(10.0**-2.8)
        labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert any(label.startswith("cost within +100%") for label in labels)
    finally:
        mpl.close(fig)


def test_profile_names_both_half_widths_and_which_one_is_wider(mpl) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(_asymmetric_run(), ax, rise=1.0)

    try:
        note = _note(ax)
        assert "K_over_R in [3.162e-05, 0.001585]" in note
        assert "/3.162 below" in note
        assert "x15.85 above" in note
        assert "5.012x wider above" in note
    finally:
        mpl.close(fig)


def test_profile_reports_half_widths_as_differences_on_a_linear_axis(mpl) -> None:
    run = _session_run([0.0, 1.0, 2.0, 3.0], [5.0, 1.0, 1.0, 3.0])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax, rise=1.0)

    try:
        note = _note(ax)
        assert "-0.25 below" in note
        assert "+1.5 above" in note
        assert "6x wider above" in note
    finally:
        mpl.close(fig)


def test_profile_says_so_when_the_sweep_never_rises_above_the_tolerance(mpl) -> None:
    run = _session_run([1e-5, 1e-4, 1e-3], [1.0, 1.0, 1.0])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax, rise=1.0)

    try:
        note = _note(ax)
        assert "no trial rose above the tolerance" in note
        low, high = _band_bounds(ax)
        assert (low, high) == pytest.approx((1e-5, 1e-3))
    finally:
        mpl.close(fig)


def test_profile_says_which_side_is_open(mpl) -> None:
    run = _session_run([1e-5, 1e-4, 1e-3], [9.0, 1.0, 1.5])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax, rise=1.0)

    try:
        assert "above is open" in _note(ax)
    finally:
        mpl.close(fig)


def test_profile_stops_the_interval_at_a_failed_trial(mpl) -> None:
    run = _session_run([1e-5, 1e-4, 1e-3, 1e-2], [9.0, 1.0, None, 1.5])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax, rise=1.0)

    try:
        note = _note(ax)
        assert "above stops at a failed trial" in note
        _low, high = _band_bounds(ax)
        assert high == pytest.approx(1e-4), "the interval may not step over a gap"
    finally:
        mpl.close(fig)


def test_profile_says_so_when_the_optimum_cost_is_not_positive(mpl) -> None:
    run = _session_run([1e-5, 1e-4, 1e-3], [1.0, 0.0, 2.0])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax, rise=1.0)

    try:
        assert "relative rise" in _note(ax)
        assert not ax.patches
    finally:
        mpl.close(fig)


def test_profile_refuses_a_rise_that_is_not_positive(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="rise"):
            ParameterCostProfileFigure().render(_asymmetric_run(), ax, rise=0.0)
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
        assert _profile(ax).get_ydata().tolist() == [20.0, 3.0, 1.0, 1.2, 5.2]
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
        assert _profile(ax).get_ydata().tolist() == [20.0, 3.0, 1.0, 1.2, 5.2]
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

    ParameterCostProfileFigure().render(_asymmetric_run(), ax, rise=1.0)

    try:
        triplet = {color.lower() for color in HIGH_CONTRAST_TRIPLET}
        drawn = {to_hex(_profile(ax).get_color()).lower()}
        best = next(line for line in ax.lines if str(line.get_label()).startswith("best trial"))
        drawn.add(to_hex(best.get_color()).lower())
        band = next(item for item in ax.patches if str(item.get_label()).startswith("cost within"))
        drawn.add(to_hex(band.get_facecolor()).lower())
        assert drawn <= triplet
    finally:
        mpl.close(fig)


def test_profile_is_registered_under_its_name() -> None:
    figure = get_figure("parameter_cost_profile")

    assert isinstance(figure, ParameterCostProfileFigure)
    assert figure.spec.name == "parameter_cost_profile"
    assert figure.spec.kind == "timeseries"


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
