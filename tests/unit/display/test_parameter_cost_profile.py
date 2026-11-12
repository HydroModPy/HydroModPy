"""Cost profile of one calibrated parameter and its acceptable interval.

The figure plots the cost of each trial (m for a network distance, 1 - NSE for
an efficiency) against the sampled parameter (for example K in m/s). It shades
the trials within one margin of the best total cost: one mesh cell on network
distances, five per cent of the best cost otherwise.
"""

from __future__ import annotations

import uuid
from pathlib import Path

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


def session_run(
    project: Path,
    parameter_values: list[float],
    costs: list[float | None],
    *,
    parameter: str = "K_over_R",
    block: dict | None = None,
    extra: dict[str, float] | None = None,
) -> Session:
    """One row per trial, in the shape the session journal writes.

    ``block`` adds keys to the block of the sampled parameter (its bounds, its
    unit) and ``extra`` adds parameters the session moved as well.
    """
    rows = [
        {
            "trial": index + 1,
            "parameters": {
                parameter: {"value": value, **(block or {})},
                **{key: {"value": number} for key, number in (extra or {}).items()},
            },
            "cost": cost,
            "status": "completed" if cost is not None else "failed",
        }
        for index, (value, cost) in enumerate(zip(parameter_values, costs, strict=True))
    ]
    return journal_session(project / uuid.uuid4().hex, rows, name="cheze-sweep")


def asymmetric_run(project: Path) -> Session:
    """A profile steep below the optimum and flat above it.

    Five per cent of the best cost puts the threshold at 1.05. The trials at
    3e-05, 1e-04, 1e-03 and 1e-02 stay under it, so the interval is a factor
    10/3 below the best and 100 above it.
    """
    return session_run(
        project,
        [1e-6, 1e-5, 3e-5, 1e-4, 1e-3, 1e-2, 1e-1],
        [20.0, 3.0, 1.03, 1.0, 1.02, 1.04, 5.2],
    )


def steady_run(tmp_path: Path) -> Session:
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


def two_root_run(tmp_path: Path) -> Session:
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


# Two objective blocks that disagree on their best trial. The hydrograph is
# best at K = 1e-4 and within 5 % of it nowhere else. The heads are best at
# 1e-2 and within 5 % of it at 1e-1 as well.
VALUES = [1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0]
HYDROGRAPH = [9.0, 4.0, 1.0, 1.5, 2.5, 6.0, 9.0]
HEADS = [8.0, 6.0, 3.0, 1.5, 0.5, 0.51, 8.0]
TOTAL = [h + w for h, w in zip(HYDROGRAPH, HEADS, strict=True)]

TWO_BLOCK_CONFIG = {
    "method": "scipy_nelder_mead",
    "parameters": {"K": {"bounds": [1e-7, 10.0], "search_space": "log", "units": "m/s"}},
    "objective_blocks": [
        {"name": "hydrograph", "metric": "rmse", "weight": 1.0, "normalize_cost": False},
        {"name": "heads", "metric": "rmse", "weight": 1.0, "normalize_cost": False},
    ],
    "uncertainty": {"method": "cost_profile", "cost_margin": None},
}


def two_block_run(tmp_path: Path) -> Session:
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
        config=TWO_BLOCK_CONFIG,
        bounds={"K": ParameterBound(lower=1e-7, upper=10.0, search_space="identity", units="m/s")},
        best_trial=4,
    )


def profile_line(ax):
    return next(line for line in ax.lines if str(line.get_label()).startswith("cost:"))


def band_bounds(ax) -> tuple[float, float] | None:
    """Lower and upper end of the shaded interval, or None when nothing is shaded."""
    for patch in ax.patches:
        if str(patch.get_label()).startswith("within"):
            if hasattr(patch, "get_width"):
                return float(patch.get_x()), float(patch.get_x() + patch.get_width())
            xs = patch.get_xy()[:, 0]
            return float(xs.min()), float(xs.max())
    return None


def note_of(ax) -> str:
    return ax.texts[0].get_text()


def test_profile_stays_linear_inside_one_decade(mpl, tmp_path) -> None:
    run = session_run(tmp_path, [1.0, 2.0, 3.0, 4.0], [9.0, 1.0, 1.5, 8.0])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    assert ax.get_xscale() == "linear"


def test_trials_are_sorted_along_the_parameter(mpl, tmp_path) -> None:
    run = session_run(tmp_path, [1e-3, 1e-5, 1e-4], [1.2, 3.0, 1.0])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    assert profile_line(ax).get_xdata().tolist() == [1e-5, 1e-4, 1e-3]
    assert profile_line(ax).get_ydata().tolist() == [3.0, 1.0, 1.2]


def test_interval_within_five_per_cent(mpl, tmp_path) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(asymmetric_run(tmp_path), ax)

    assert band_bounds(ax) == pytest.approx((3e-5, 1e-2))
    labels = [text.get_text() for text in ax.get_legend().get_texts()]
    assert "within 5% of the best" in labels


# Each row is a sweep of one parameter and the fragments the note must say.
NOTES = [
    pytest.param(
        {"parameter_values": [0.0, 1.0, 2.0, 3.0, 4.0], "costs": [5.0, 1.02, 1.0, 1.04, 3.0]},
        ("-1 below", "+1 above"),
        id="half widths are differences on a linear axis",
    ),
    pytest.param(
        {"parameter_values": [1e-5, 1e-4, 1e-3], "costs": [9.0, 1.0, 1.04]},
        ("above is open",),
        id="side left open",
    ),
    pytest.param(
        {
            "parameter_values": [1e-5, 3e-5, 1e-4, 1e-3, 1e-2],
            "costs": [9.0, 1.02, 1.0, None, 1.5],
        },
        ("above stops at a failed trial",),
        id="end stops at a failed trial",
    ),
    pytest.param(
        # Example 04's grid, where the lowest cost sits on the lower bound.
        {
            "parameter_values": [1e-6, 3.16e-6, 1e-5],
            "costs": [0.358, 0.464, 0.521],
            "parameter": "K",
            "block": {"bounds": [1e-6, 1e-4], "units": "m/s"},
        },
        ("on the lower search bound",),
        id="best on a search bound",
    ),
]


@pytest.mark.parametrize(("sweep", "fragments"), NOTES)
def test_note_under_the_profile(mpl, tmp_path, sweep, fragments) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(session_run(tmp_path, **sweep), ax)

    for fragment in fragments:
        assert fragment in note_of(ax)


# Sweeps that draw no interval, with the sentence that says why.
NO_INTERVAL = [
    pytest.param([1e-5, 1e-4], [None, None], "no trial produced a cost", id="no cost at all"),
    pytest.param(
        [1e-5, 1e-4, 1e-3],
        [1.0, 0.0, 2.0],
        "a relative width is a fraction of the best cost",
        id="best cost not positive",
    ),
]


@pytest.mark.parametrize(("values", "costs", "sentence"), NO_INTERVAL)
def test_no_interval_is_drawn(mpl, tmp_path, values, costs, sentence) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(session_run(tmp_path, values, costs), ax)

    assert sentence in note_of(ax)
    assert not ax.patches


def test_sweep_that_never_rises_above_the_tolerance(mpl, tmp_path) -> None:
    run = session_run(tmp_path, [1e-5, 1e-4, 1e-3], [1.0, 1.0, 1.0])
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    assert "no trial rose above the tolerance" in note_of(ax)
    assert band_bounds(ax) == pytest.approx((1e-5, 1e-3))


def test_distance_cost_reads_the_calibration_summary_interval(mpl, tmp_path) -> None:
    # Example 04 reported [7.499e-05, 0.0001] on the console and on the
    # progress slide, and the profile drew [8.094e-05, 8.115e-05], a +10 %
    # rise of a 1.965 m cost. One mesh cell is the width, as in the summary.
    run = steady_run(tmp_path)
    rows = steady_bisection_rows()
    summary = margin_intervals(
        [{"K": row["parameters"]["K"]["value"], **row} for row in rows],
        ["K"],
        margin=75.0,
        kind="absolute",
    )[0]
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    assert band_bounds(ax) == pytest.approx((summary.lower, summary.upper))
    assert (summary.lower, summary.upper) == pytest.approx((7.4989e-05, 1e-4))
    assert _read_search(run, output=None).intervals["K"] == pytest.approx(
        (summary.lower, summary.upper)
    )
    labels = [text.get_text() for text in ax.get_legend().get_texts()]
    assert "within one mesh cell (75 m) of the best" in labels
    assert "K in [7.499e-05, 0.0001] m/s: 7 of 15 trials scored within one mesh cell" in note_of(ax)


def test_axes_name_the_units(mpl, tmp_path) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(steady_run(tmp_path), ax)

    assert ax.get_xlabel() == "K (m/s)"
    assert ax.get_ylabel() == "|D_so - D_os| (m)"


def test_efficiency_cost_is_dimensionless(mpl, tmp_path) -> None:
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

    assert ax.get_ylabel() == "1 - NSElog (-)"
    assert ax.get_xlabel() == "Sy (-)"
    # Five per cent of 0.084, the width the summary and the slide read.
    assert band_bounds(ax) == pytest.approx((0.042, 0.052))
    assert _read_search(run, output=None).intervals["Sy"] == pytest.approx((0.042, 0.052))


def test_marked_trial_is_the_one_the_calibration_returned(mpl, tmp_path) -> None:
    # The lowest cost of that search is trial 1, K = 1e-07. The calibration
    # returned the combined value of its two roots, K = 5.9e-06, trial 24.
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(two_root_run(tmp_path), ax)

    marked = next(line for line in ax.lines if str(line.get_label()).startswith("returned"))
    assert marked.get_xdata().tolist() == [5.9e-06]
    assert "K = 5.9e-06 m/s" in str(marked.get_label())
    assert not [line for line in ax.lines if str(line.get_label()).startswith("best trial")]


def test_value_combined_from_two_roots_has_no_interval(mpl, tmp_path) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(two_root_run(tmp_path), ax)

    assert not ax.patches
    note = " ".join(note_of(ax).split())
    assert "no interval of trials around a value combined from two roots" in note
    assert "Delta = -1.28 decade(s)" in note
    roots = [str(line.get_label()) for line in ax.lines if "*_" in str(line.get_label())]
    assert roots == ["K*_minimal = 2.564e-05", "K*_maximal = 1.358e-06"]


# The interval is a margin on the total cost, never on one block. Two blocks that
# disagree on their best trial still give one interval, the one read on ``cost``.
def test_interval_is_a_margin_on_the_total_cost(mpl, tmp_path) -> None:
    run = two_block_run(tmp_path)
    total = margin_intervals(
        [{"K": v, "cost": c} for v, c in zip(VALUES, TOTAL, strict=True)], ["K"], margin=0.05
    )[0]
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    assert band_bounds(ax) == pytest.approx((total.lower, total.upper))
    assert _read_search(run, output=None).intervals["K"] == pytest.approx(
        (total.lower, total.upper)
    )


def test_blocks_do_not_make_their_own_interval(mpl, tmp_path) -> None:
    per_block = [
        margin_intervals(
            [{"K": v, "cost": c} for v, c in zip(VALUES, costs, strict=True)], ["K"], margin=0.05
        )[0]
        for costs in (HYDROGRAPH, HEADS)
    ]
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(two_block_run(tmp_path), ax)

    drawn = band_bounds(ax)
    assert drawn is not None
    for block in per_block:
        assert drawn != pytest.approx((block.lower, block.upper))
    joined = (min(b.lower for b in per_block), max(b.upper for b in per_block))
    assert drawn != pytest.approx(joined)


def test_block_cost_drawn_alone_gets_no_interval(mpl, tmp_path) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(two_block_run(tmp_path), ax, objective="heads.raw_cost")

    assert band_bounds(ax) is None


def test_available_on_a_session_with_trials(tmp_path) -> None:
    assert ParameterCostProfileFigure().unavailable_reason(asymmetric_run(tmp_path)) is None


def test_unavailable_on_a_session_without_trial(tmp_path) -> None:
    reason = ParameterCostProfileFigure().unavailable_reason(journal_session(tmp_path, []))

    assert reason is not None
    assert "no trial recorded" in reason


def test_figure_draws_a_session() -> None:
    assert ParameterCostProfileFigure.spec.subject == "session"


# Each row is the session to draw, the render keywords and the start of the message.
REFUSALS = [
    pytest.param(
        {"parameter_values": [0.0, 1.0, 2.0], "costs": [9.0, 1.0, 8.0]},
        {"log_scale": True},
        "non-positive",
        id="log axis over a non-positive parameter",
    ),
    pytest.param(
        {
            "parameter_values": [1e-6, 1e-5, 3e-5, 1e-4, 1e-3, 1e-2, 1e-1],
            "costs": [20.0, 3.0, 1.03, 1.0, 1.02, 1.04, 5.2],
            "extra": {"porosity": 0.1},
        },
        {},
        "K_over_R, porosity",
        id="several parameters moved",
    ),
    pytest.param({"parameter_values": [], "costs": []}, {}, "no trial", id="session with no trial"),
]


@pytest.mark.parametrize(("sweep", "render_kwargs", "message"), REFUSALS)
def test_refusals(mpl, tmp_path, sweep, render_kwargs, message) -> None:
    fig, ax = mpl.subplots()

    with pytest.raises(ValueError, match=message):
        ParameterCostProfileFigure().render(session_run(tmp_path, **sweep), ax, **render_kwargs)
