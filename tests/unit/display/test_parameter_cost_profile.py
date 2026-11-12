"""The parameter cost profile and its acceptable interval."""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.calibration.optim.cost_margin import margin_intervals
from hydromodpy.display.figures.calibration_progress import _read_search
from hydromodpy.display.figures.parameter_cost_profile import ParameterCostProfileFigure
from hydromodpy.results.session.descriptor import ParameterBound
from hydromodpy.results.session.view import Session

from ._calibration_journal import (
    K_BOUNDS,
    NETWORK_CONFIG,
    TWO_ROOT_CONFIG,
    TWO_ROOTS,
    journal_session,
    steady_bisection_rows,
    two_root_rows,
)

# The cost profile of one calibrated parameter, and its asymmetry.
#
# The figure is driven exactly as a session drives it: one row per trial, the
# sampled parameter nested under ``parameters`` and the cost written at the top
# level under ``cost``, which is where the session journal puts it.
#
# The interval it shades is the one the calibration summary reports, read by the
# same rule: one mesh cell on network distances in meters, five per cent of the
# best cost otherwise. The trial it marks is the one the calibration returned.


def _session_run(
    project: Path,
    parameter_values: list[float],
    costs: list[float | None],
    *,
    statuses: list[str] | None = None,
    parameter: str = "K_over_R",
    name: str = "cheze-sweep",
    block: dict | None = None,
    extra: dict[str, float] | None = None,
    best_trial: int | None = None,
) -> Session:
    """One row per trial, in the shape the session journal writes.

    ``block`` adds keys to the block of the sampled parameter (its bounds, its
    unit) and ``extra`` adds parameters the session moved as well.
    """
    rows = []
    for index, (value, cost) in enumerate(zip(parameter_values, costs, strict=True)):
        rows.append(
            {
                "trial": index + 1,
                "parameters": {
                    parameter: {"value": value, **(block or {})},
                    **{key: {"value": number} for key, number in (extra or {}).items()},
                },
                "cost": cost,
                "status": (
                    statuses[index]
                    if statuses is not None
                    else ("completed" if cost is not None else "failed")
                ),
            }
        )
    return journal_session(project / uuid.uuid4().hex, rows, name=name, best_trial=best_trial)


def _asymmetric_run(project: Path, **kwargs) -> Session:
    """A profile steep below the optimum and flat above it.

    Five per cent of the best cost puts the threshold at 1.05: the trials at
    3e-05, 1e-04, 1e-03 and 1e-02 stay under it, so the interval is a factor
    10/3 below the best and 100 above it.
    """
    return _session_run(
        project,
        [1e-6, 1e-5, 3e-5, 1e-4, 1e-3, 1e-2, 1e-1],
        [20.0, 3.0, 1.03, 1.0, 1.02, 1.04, 5.2],
        **kwargs,
    )


def _several_parameters_run(project: Path) -> Session:
    """The asymmetric sweep, with a second parameter the session moved as well."""
    return _session_run(
        project,
        [1e-6, 1e-5, 3e-5, 1e-4, 1e-3, 1e-2, 1e-1],
        [20.0, 3.0, 1.03, 1.0, 1.02, 1.04, 5.2],
        extra={"porosity": 0.1},
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


def test_profile_stays_linear_when_the_sweep_stayed_inside_one_decade(mpl, tmp_path) -> None:
    run = _session_run(tmp_path, [1.0, 2.0, 3.0, 4.0], [9.0, 1.0, 1.5, 8.0])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert ax.get_xscale() == "linear"
    finally:
        mpl.close(fig)


def test_profile_refuses_a_log_axis_over_a_non_positive_parameter(mpl, tmp_path) -> None:
    run = _session_run(tmp_path, [0.0, 1.0, 2.0], [9.0, 1.0, 8.0])
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="non-positive"):
            ParameterCostProfileFigure().render(run, ax, log_scale=True)
    finally:
        mpl.close(fig)


def test_profile_sorts_the_trials_along_the_parameter(mpl, tmp_path) -> None:
    run = _session_run(tmp_path, [1e-3, 1e-5, 1e-4], [1.2, 3.0, 1.0])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert _profile(ax).get_xdata().tolist() == [1e-5, 1e-4, 1e-3]
        assert _profile(ax).get_ydata().tolist() == [3.0, 1.0, 1.2]
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# a failed trial breaks the profile
# --------------------------------------------------------------------------- #


def test_profile_says_so_when_no_trial_produced_a_cost(mpl, tmp_path) -> None:
    run = _session_run(tmp_path, [1e-5, 1e-4], [None, None])
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


def test_profile_draws_the_interval_of_trials_within_five_per_cent(mpl, tmp_path) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(_asymmetric_run(tmp_path), ax)

    try:
        low, high = _band_bounds(ax)
        assert (low, high) == pytest.approx((3e-5, 1e-2))
        labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert "within 5% of the best" in labels
    finally:
        mpl.close(fig)


def test_profile_reports_half_widths_as_differences_on_a_linear_axis(mpl, tmp_path) -> None:
    run = _session_run(tmp_path, [0.0, 1.0, 2.0, 3.0, 4.0], [5.0, 1.02, 1.0, 1.04, 3.0])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        note = _note(ax)
        assert "-1 below" in note
        assert "+1 above" in note
    finally:
        mpl.close(fig)


def test_profile_says_so_when_the_sweep_never_rises_above_the_tolerance(mpl, tmp_path) -> None:
    run = _session_run(tmp_path, [1e-5, 1e-4, 1e-3], [1.0, 1.0, 1.0])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        note = _note(ax)
        assert "no trial rose above the tolerance" in note
        low, high = _band_bounds(ax)
        assert (low, high) == pytest.approx((1e-5, 1e-3))
    finally:
        mpl.close(fig)


def test_profile_says_which_side_is_open(mpl, tmp_path) -> None:
    run = _session_run(tmp_path, [1e-5, 1e-4, 1e-3], [9.0, 1.0, 1.04])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert "above is open" in _note(ax)
    finally:
        mpl.close(fig)


def test_profile_says_when_an_end_stops_at_a_failed_trial(mpl, tmp_path) -> None:
    run = _session_run(tmp_path, [1e-5, 3e-5, 1e-4, 1e-3, 1e-2], [9.0, 1.02, 1.0, None, 1.5])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert "above stops at a failed trial" in _note(ax)
    finally:
        mpl.close(fig)


def test_profile_says_so_when_the_best_sits_on_a_search_bound(mpl, tmp_path) -> None:
    # Example 04's grid: K = 1e-06 is the lowest cost and the lower bound, which
    # the calibration warns about and the profile said nothing of.
    run = _session_run(
        tmp_path,
        [1e-6, 3.16e-6, 1e-5],
        [0.358, 0.464, 0.521],
        parameter="K",
        block={"bounds": [1e-6, 1e-4], "units": "m/s"},
    )
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert "on the lower search bound" in _note(ax)
    finally:
        mpl.close(fig)


def test_profile_says_so_when_the_optimum_cost_is_not_positive(mpl, tmp_path) -> None:
    run = _session_run(tmp_path, [1e-5, 1e-4, 1e-3], [1.0, 0.0, 2.0])
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
    return journal_session(
        tmp_path,
        steady_bisection_rows(),
        method="bisection",
        phase="steady_conductivity",
        config=NETWORK_CONFIG,
        bounds=K_BOUNDS,
        best_trial=15,
        root_search={"bracket": {"parameter": "K", "low": 8.0584e-05, "high": 8.1069e-05}},
    )


def test_a_distance_cost_reads_the_interval_of_the_calibration_summary(mpl, tmp_path) -> None:
    # Example 04 reported [7.499e-05, 0.0001] on the console and on the
    # progress slide, and the profile drew [8.094e-05, 8.115e-05], a +10 %
    # rise of a 1.965 m cost. One mesh cell is the width, as in the summary.
    from hydromodpy.calibration.optim.cost_margin import margin_intervals

    run = _steady_run(tmp_path)
    rows = steady_bisection_rows()
    summary = margin_intervals(
        [{"K": row["parameters"]["K"]["value"], **row} for row in rows],
        ["K"],
        margin=75.0,
        kind="absolute",
    )[0]
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert _band_bounds(ax) == pytest.approx((summary.lower, summary.upper))
        assert (summary.lower, summary.upper) == pytest.approx((7.4989e-05, 1e-4))
        assert _read_search(run, output=None).intervals["K"] == pytest.approx(
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
        "parameters": {"Sy": {"bounds": [0.005, 0.35], "search_space": "log", "units": "-"}},
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
            "cost": cost,
            "parameters": {"Sy": {"value": value, "units": "-"}},
            "components": {"hydrograph.raw_cost": cost},
        }
        for trial, (value, cost) in enumerate(zip(values, costs, strict=True), start=1)
    ]
    run = journal_session(
        tmp_path,
        rows,
        method="scipy_nelder_mead",
        phase="transient_storage",
        config=config,
        bounds={"Sy": ParameterBound(lower=0.005, upper=0.35, search_space="identity", units="-")},
        best_trial=4,
    )
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert ax.get_ylabel() == "1 - NSElog (-)"
        assert ax.get_xlabel() == "Sy (-)"
        # Five per cent of 0.084, the width the summary and the slide read.
        assert _band_bounds(ax) == pytest.approx((0.042, 0.052))
        assert _read_search(run, output=None).intervals["Sy"] == pytest.approx((0.042, 0.052))
    finally:
        mpl.close(fig)


def _two_root_run(tmp_path):
    return journal_session(
        tmp_path,
        two_root_rows(),
        method="bisection",
        phase="transient_conductivity",
        config=TWO_ROOT_CONFIG,
        bounds=K_BOUNDS,
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


# --------------------------------------------------------------------------- #
# the note covers neither the legend nor a trial
# --------------------------------------------------------------------------- #


def _storage_run(project: Path) -> Session:
    """The transient storage profile of example 04: its first trial sat under the note."""
    return _session_run(
        project,
        [0.02738, 0.04183, 0.04424, 0.045, 0.04653, 0.05173, 0.06398, 0.045],
        [0.1182, 0.08459, 0.08402, 0.08398, 0.08417, 0.08634, 0.09733, 0.08398],
        parameter="Sy",
    )


# --------------------------------------------------------------------------- #
# one axis, one parameter
# --------------------------------------------------------------------------- #


def test_profile_refuses_a_session_that_moved_several_parameters(mpl, tmp_path) -> None:
    run = _several_parameters_run(tmp_path)
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="K_over_R, porosity"):
            ParameterCostProfileFigure().render(run, ax)
    finally:
        mpl.close(fig)


def test_profile_refuses_a_session_with_no_trial(mpl, tmp_path) -> None:
    run = journal_session(tmp_path, [])
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="no trial"):
            ParameterCostProfileFigure().render(run, ax)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# colors, registration, availability
# --------------------------------------------------------------------------- #


def test_profile_is_available_on_a_run_carrying_a_session(tmp_path) -> None:
    assert ParameterCostProfileFigure().unavailable_reason(_asymmetric_run(tmp_path)) is None


def test_profile_is_skipped_on_a_session_without_trial(tmp_path) -> None:
    reason = ParameterCostProfileFigure().unavailable_reason(journal_session(tmp_path, []))

    assert reason is not None
    assert "no trial recorded" in reason


def test_profile_draws_a_session() -> None:
    assert ParameterCostProfileFigure.spec.subject == "session"


# The interval around a calibrated value is a margin on the TOTAL cost, never on a block.
#
# Audit decision m27: the acceptable set of a calibration is the trials whose
# total cost stays within one margin of the best total cost. There is no threshold
# per objective block. Two blocks that disagree on their best trial must still
# give one interval, the one read on ``cost``, and a block cost drawn
# on its own gets none.

VALUES = [1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0]


HYDROGRAPH = [9.0, 4.0, 1.0, 1.5, 2.5, 6.0, 9.0]


"""Best at 1e-4, and within 5 % of its best nowhere else."""


HEADS = [8.0, 6.0, 3.0, 1.5, 0.5, 0.51, 8.0]


"""Best at 1e-2, and within 5 % of its best at 1e-1 as well."""


TOTAL = [h + w for h, w in zip(HYDROGRAPH, HEADS, strict=True)]


CONFIG = {
    "method": "scipy_nelder_mead",
    "parameters": {"K": {"bounds": [1e-7, 10.0], "search_space": "log", "units": "m/s"}},
    "objective_blocks": [
        {"name": "hydrograph", "metric": "rmse", "weight": 1.0, "normalize_cost": False},
        {"name": "heads", "metric": "rmse", "weight": 1.0, "normalize_cost": False},
    ],
    "uncertainty": {"method": "cost_profile", "cost_margin": None},
}


def _run(tmp_path):
    rows = [
        {
            "trial": trial,
            "status": "completed",
            "cost": total,
            "parameters": {"K": {"value": value, "units": "m/s"}},
            "components": {"hydrograph.raw_cost": hydrograph, "heads.raw_cost": heads},
        }
        for trial, (value, total, hydrograph, heads) in enumerate(
            zip(VALUES, TOTAL, HYDROGRAPH, HEADS, strict=True), start=1
        )
    ]
    return journal_session(
        tmp_path,
        rows,
        method="scipy_nelder_mead",
        phase="transient_conductivity",
        config=CONFIG,
        bounds={"K": ParameterBound(lower=1e-7, upper=10.0, search_space="identity", units="m/s")},
        best_trial=4,
    )


def _band(ax) -> tuple[float, float] | None:
    for patch in ax.patches:
        if str(patch.get_label()).startswith("within"):
            return float(patch.get_x()), float(patch.get_x() + patch.get_width())
    return None


def test_the_figure_shades_the_margin_on_the_total_cost(mpl, tmp_path) -> None:
    run = _run(tmp_path)
    total = margin_intervals(
        [{"K": v, "cost": c} for v, c in zip(VALUES, TOTAL, strict=True)],
        ["K"],
        margin=0.05,
    )[0]
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert _band(ax) == pytest.approx((total.lower, total.upper))
        assert _read_search(run, output=None).intervals["K"] == pytest.approx(
            (total.lower, total.upper)
        )
    finally:
        mpl.close(fig)


def test_the_blocks_do_not_each_make_their_own_interval(mpl, tmp_path) -> None:
    """Neither block interval, alone or joined, is the interval drawn."""
    per_block = [
        margin_intervals(
            [{"K": v, "cost": c} for v, c in zip(VALUES, costs, strict=True)],
            ["K"],
            margin=0.05,
        )[0]
        for costs in (HYDROGRAPH, HEADS)
    ]
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(_run(tmp_path), ax)

    try:
        drawn = _band(ax)
        assert drawn is not None
        for block in per_block:
            assert drawn != pytest.approx((block.lower, block.upper))
        joined = (min(b.lower for b in per_block), max(b.upper for b in per_block))
        assert drawn != pytest.approx(joined)
    finally:
        mpl.close(fig)


def test_a_block_cost_drawn_alone_gets_no_interval(mpl, tmp_path) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(_run(tmp_path), ax, objective="heads.raw_cost")

    try:
        assert _band(ax) is None
    finally:
        mpl.close(fig)
