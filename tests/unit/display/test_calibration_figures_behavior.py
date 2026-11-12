"""The calibration figures drawn from a session of trials.

A session is a journal with one row per trial, holding the sampled parameters,
the cost and the status. The six figures are the convergence curve, the trace,
the trial histograms, the pairplot, the landscape grid and the objective
surface. Parameters are in the unit of the model (K in m/s, Sy without unit)
and the cost has no unit.
"""

from __future__ import annotations

import pytest

from hydromodpy.display.figures._trial_diagnostics import trial_table
from hydromodpy.display.figures.calibration_convergence import CalibrationConvergenceFigure
from hydromodpy.display.figures.calibration_landscape import CalibrationLandscapeFigure
from hydromodpy.display.figures.calibration_objective_surface import (
    CalibrationObjectiveSurfaceFigure,
)
from hydromodpy.display.figures.calibration_pairplot import CalibrationPairplotFigure
from hydromodpy.display.figures.calibration_trace import CalibrationTraceFigure
from hydromodpy.display.figures.calibration_trial_distribution import (
    CalibrationTrialDistributionFigure,
)

from ._calibration_journal import flat_session, journal_session

NAN = float("nan")

# Six trials on two parameters. The minimum objective sits at (kh=2.0, sy=0.20).
KH = [1.0, 1.0, 2.0, 2.0, 3.0, 3.0]
SY = [0.10, 0.30, 0.20, 0.40, 0.15, 0.35]
OBJECTIVE = [5.0, 4.0, 1.0, 6.0, 3.0, 7.0]

# One row per trial as the catalog stores it. The sampled parameters stay
# nested in a JSON block, the cost sits in ``cost`` and no parameter is a bare
# column. The three value sets are disjoint, so a panel drawn from the cost
# cannot be mistaken for a panel drawn from a parameter.
CATALOG_KH = [1e-5, 2e-5, 3e-5, 4e-5, 5e-5, 6e-5]
CATALOG_SY = [0.05, 0.30, 0.15, 0.20, 0.10, 0.25]
CATALOG_COST = [5.0, 4.0, 1.0, 6.0, 3.0, 7.0]


def calibration_run(project, name="calibration-c", status_col=True):
    data = {"trial": [1, 2, 3, 4, 5, 6], "kh": KH, "sy": SY, "objective": OBJECTIVE}
    if status_col:
        data["status"] = ["ok"] * 6
    return flat_session(project, data, name=name)


def catalog_run(project, name: str = "calibration-real"):
    rows = [
        {
            "trial": index,
            "parameters": {"kh": kh, "sy": sy},
            "cost": cost,
            "components": {"nse": 0.5},
            "status": "completed",
        }
        for index, (kh, sy, cost) in enumerate(
            zip(CATALOG_KH, CATALOG_SY, CATALOG_COST, strict=True), start=1
        )
    ]
    return journal_session(project, rows, name=name)


def empty_session(project):
    return journal_session(project, [])


def parameterless_session(project):
    return flat_session(project, {"trial": [1], "objective": [1.0]})


def one_parameter_session(project):
    return flat_session(project, {"trial": [1, 2], "kh": [1.0, 2.0]})


def costs_only_session(project):
    # The only numeric column is the cost: a figure must say so instead of
    # drawing the cost under a parameter label.
    rows = [
        {"trial": 1, "parameters": {}, "cost": 2.0},
        {"trial": 2, "parameters": {}, "cost": 1.0},
    ]
    return journal_session(project, rows)


def test_convergence_plots_iteration_and_best_so_far(mpl, tmp_path) -> None:
    session = flat_session(
        tmp_path,
        {"trial": [1, 2, 3, 4], "kh": [1.0, 2.0, 3.0, 4.0], "cost": [9.0] * 4},
        name="calibration-a",
        components=[{"rmse": value} for value in (5.0, 3.0, 4.0, 2.0)],
    )
    _, ax = mpl.subplots()

    CalibrationConvergenceFigure().render(session, ax, objective="rmse")

    assert [line.get_label() for line in ax.lines] == ["iteration", "best so far"]
    assert ax.lines[0].get_ydata().tolist() == [5.0, 3.0, 4.0, 2.0]
    assert ax.lines[1].get_ydata().tolist() == [5.0, 3.0, 3.0, 2.0]
    assert ax.get_ylabel() == "rmse"
    assert "calibration-a" in ax.get_title()


CONVERGENCE = [
    pytest.param([4.0, 1.0, 2.0], ["ok"] * 3, [4.0, 1.0, 1.0], id="falls back to the cost column"),
    pytest.param([2.0, 0.5, 1.5], ["ok"] * 3, [2.0, 0.5, 0.5], id="real trial table"),
    # A trial that failed publishes no cost. Carrying its NaN forward would
    # flatten the best-so-far curve from that trial on.
    pytest.param(
        [2.0, NAN, 1.5], ["ok", "failed", "ok"], [2.0, 2.0, 1.5], id="best kept across a failure"
    ),
]


@pytest.mark.parametrize(("cost", "status", "best"), CONVERGENCE)
def test_convergence_reads_the_cost_column(mpl, tmp_path, cost, status, best) -> None:
    session = flat_session(
        tmp_path, {"trial": [1, 2, 3], "kh": [1.0, 2.0, 3.0], "cost": cost, "status": status}
    )
    _, ax = mpl.subplots()

    CalibrationConvergenceFigure().render(session, ax)

    values = ax.lines[0].get_ydata().tolist()
    assert [v for v in values if v == v] == [v for v in cost if v == v]
    assert ax.lines[1].get_ydata().tolist() == best
    assert ax.get_ylabel() == "cost"
    assert ax.lines[0].get_xdata().tolist() == [1.0, 2.0, 3.0]


def test_trace_draws_every_trial_and_saves_png(mpl, tmp_path) -> None:
    session = flat_session(
        tmp_path,
        {
            "trial": [10, 11, 12],
            "kh": [1.0, 9.0, 2.0],
            "sy": [0.1, 0.9, 0.2],
            "objective": [5.0, 4.0, 3.0],
            "status": ["ok", "failed", "ok"],
        },
        name="calibration-a",
    )
    out = tmp_path / "trace.png"

    fig = CalibrationTraceFigure().plot(
        session, parameters=["kh"], objective="cost", save_path=out, dpi=80
    )

    assert out.stat().st_size > 0
    assert len(fig.axes) == 2
    assert fig.axes[0].get_ylabel() == "kh"
    assert fig.axes[0].lines[0].get_xdata().tolist() == [10, 11, 12]
    assert fig.axes[0].lines[0].get_ydata().tolist() == [1.0, 9.0, 2.0]
    assert fig.axes[1].get_ylabel() == "cost"
    assert fig.axes[1].lines[0].get_ydata().tolist() == [5.0, 4.0, 3.0]


def test_trace_follows_the_sampled_parameters_not_the_cost(mpl, tmp_path) -> None:
    fig = CalibrationTraceFigure().plot(catalog_run(tmp_path), dpi=80)

    # Two parameters were sampled, so two parameter panels then the cost.
    assert [ax.get_ylabel() for ax in fig.axes] == ["kh", "sy", "cost"]
    assert fig.axes[0].lines[0].get_ydata().tolist() == CATALOG_KH
    assert fig.axes[1].lines[0].get_ydata().tolist() == CATALOG_SY
    assert fig.axes[2].lines[0].get_ydata().tolist() == CATALOG_COST
    assert fig.axes[0].lines[0].get_xdata().tolist() == [1, 2, 3, 4, 5, 6]


def test_distribution_respects_the_parameter_list(mpl, tmp_path) -> None:
    fig = CalibrationTrialDistributionFigure().plot(
        calibration_run(tmp_path), parameters=["sy"], bins=3, dpi=80
    )

    labels = {ax.get_xlabel() for ax in fig.axes if ax.get_xlabel()}
    assert "sy" in labels
    assert "kh" not in labels


def test_distribution_pads_the_grid_and_saves_png(mpl, tmp_path) -> None:
    # Four parameters with ncols=3 give a 2x3 grid, so two trailing cells stay
    # empty (axis off).
    run = flat_session(
        tmp_path,
        {
            "trial": list(range(1, 7)),
            "a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "b": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            "c": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
            "d": [0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
            "objective": OBJECTIVE,
        },
        name="cal-4p",
    )
    out = tmp_path / "posterior.png"

    fig = CalibrationTrialDistributionFigure().plot(run, bins=3, save_path=out, dpi=80)

    assert out.stat().st_size > 0
    assert {"a", "b", "c", "d"} <= {ax.get_xlabel() for ax in fig.axes if ax.get_xlabel()}
    assert len([ax for ax in fig.axes if not ax.axison and not ax.patches]) >= 2


def test_distribution_histograms_the_parameters_not_the_cost(mpl, tmp_path) -> None:
    fig = CalibrationTrialDistributionFigure().plot(catalog_run(tmp_path), bins=3, dpi=80)

    assert {ax.get_xlabel() for ax in fig.axes if ax.get_xlabel()} == {"kh", "sy"}
    kh_ax = next(ax for ax in fig.axes if ax.get_xlabel() == "kh")
    # The bars span the sampled range, which no cost value lies in.
    left = min(bar.get_x() for bar in kh_ax.patches)
    right = max(bar.get_x() + bar.get_width() for bar in kh_ax.patches)
    assert left == pytest.approx(min(CATALOG_KH))
    assert right == pytest.approx(max(CATALOG_KH))
    assert sum(int(round(bar.get_height())) for bar in kh_ax.patches) == len(CATALOG_KH)


def test_pairplot_colors_the_scatter_by_objective(mpl, tmp_path) -> None:
    run = calibration_run(tmp_path, status_col=False)
    objective = trial_table(run).frame["cost"].to_numpy(dtype=float)

    fig = CalibrationPairplotFigure().plot(run, dpi=80)

    scatter = next(ax for ax in fig.axes if ax.collections).collections[0]
    assert scatter.get_array().tolist() == objective.tolist()  # row order
    assert scatter.get_cmap().name == "viridis"


def test_pairplot_reads_the_nested_parameter_block(mpl, tmp_path) -> None:
    fig = CalibrationPairplotFigure().plot(catalog_run(tmp_path), dpi=80)

    assert {ax.get_xlabel() for ax in fig.axes if ax.get_xlabel()} == {"kh", "sy"}
    scatter = next(ax for ax in fig.axes if ax.collections and ax.get_xlabel() == "kh")
    offsets = scatter.collections[0].get_offsets()
    assert offsets[:, 0].tolist() == CATALOG_KH
    assert offsets[:, 1].tolist() == CATALOG_SY


def test_landscape_of_two_parameters_carries_the_minimum(mpl, tmp_path) -> None:
    run = calibration_run(tmp_path)

    fig = CalibrationLandscapeFigure().plot(run, cmap="viridis", dpi=80)

    ax = next(a for a in fig.axes if a.collections)
    assert (ax.get_xlabel(), ax.get_ylabel()) == ("kh", "sy")
    scatter = ax.collections[0]
    colors = scatter.get_array().tolist()
    assert sorted(colors) == sorted(OBJECTIVE)
    # The known minimum (kh=2.0, sy=0.20, objective 1.0) is plotted.
    best = colors.index(min(colors))
    assert min(colors) == 1.0
    assert scatter.get_offsets()[best].tolist() == [2.0, 0.20]
    assert scatter.get_cmap().name == "viridis"
    assert any("cost" in (a.get_ylabel() or "") for a in fig.axes)
    assert f"landscape - {run.name}" in fig._suptitle.get_text()


def test_landscape_of_three_parameters_is_a_lower_triangle(mpl, tmp_path) -> None:
    run = flat_session(
        tmp_path,
        {
            "trial": list(range(1, 7)),
            "kh": KH,
            "sy": [0.1, 0.3, 0.2, 0.4, 0.15, 0.35],
            "rech": [10.0, 20.0, 15.0, 25.0, 12.0, 22.0],
            "objective": OBJECTIVE,
        },
        name="cal-3p",
    )
    out = tmp_path / "landscape_grid.png"

    fig = CalibrationLandscapeFigure().plot(run, save_path=out, dpi=80)

    assert out.stat().st_size > 0
    # n=3 gives a 2x2 grid. The strict upper triangle is switched off, which
    # leaves 3 scatter cells (the colorbar axis is excluded by its label).
    scatter_axes = [ax for ax in fig.axes if ax.collections and ax.get_label() != "<colorbar>"]
    assert len(scatter_axes) == 3
    assert all(len(ax.collections[0].get_offsets()) == 6 for ax in scatter_axes)
    # Parameters are ordered by name, so the bottom row labels the first two.
    assert {"kh", "rech"} <= {ax.get_xlabel() for ax in scatter_axes}


def test_landscape_spans_the_two_sampled_parameters(mpl, tmp_path) -> None:
    fig = CalibrationLandscapeFigure().plot(catalog_run(tmp_path), dpi=80)

    ax = next(a for a in fig.axes if a.collections)
    assert (ax.get_xlabel(), ax.get_ylabel()) == ("kh", "sy")
    offsets = ax.collections[0].get_offsets()
    assert offsets[:, 0].tolist() == CATALOG_KH
    assert offsets[:, 1].tolist() == CATALOG_SY
    # The cost colors the points and is never one of the two axes.
    assert ax.collections[0].get_array().tolist() == CATALOG_COST


SAVED = [
    pytest.param(CalibrationPairplotFigure, "pairplot", id="pairplot"),
    pytest.param(CalibrationLandscapeFigure, "landscape", id="landscape"),
]


@pytest.mark.parametrize(("figure", "word"), SAVED)
def test_saves_a_titled_png(mpl, tmp_path, figure, word) -> None:
    out = tmp_path / "figure.png"

    fig = figure().plot(calibration_run(tmp_path), save_path=out, dpi=80)

    assert out.stat().st_size > 0
    assert word in fig._suptitle.get_text().lower()


def test_objective_surface_spans_the_nested_parameters(mpl, tmp_path) -> None:
    pytest.importorskip("scipy")

    fig = CalibrationObjectiveSurfaceFigure().plot(catalog_run(tmp_path), dpi=80)

    surface = fig.axes[0]
    assert (surface.get_xlabel(), surface.get_ylabel()) == ("kh", "sy")
    assert any("cost" in (ax.get_ylabel() or "") for ax in fig.axes)
    # The best trial is the one the cost says, and it is marked there.
    best = CATALOG_COST.index(min(CATALOG_COST))
    star = next(
        item
        for item in surface.collections
        if len(item.get_offsets()) == 1 and item.get_offsets()[0][0] > 0.0
    )
    assert star.get_offsets()[0].tolist() == [CATALOG_KH[best], CATALOG_SY[best]]


GRID_FIGURES = [
    pytest.param(CalibrationTrialDistributionFigure, id="distribution"),
    pytest.param(CalibrationPairplotFigure, id="pairplot"),
    pytest.param(CalibrationLandscapeFigure, id="landscape"),
]


@pytest.mark.parametrize("figure", GRID_FIGURES)
def test_grid_figures_draw_in_their_own_plot(mpl, tmp_path, figure) -> None:
    # They override plot(). render() only draws a placeholder note on one axis.
    _, ax = mpl.subplots()

    figure().render(calibration_run(tmp_path), ax)

    assert not ax.get_frame_on() or not ax.axison
    assert ax.texts and "own plot()" in ax.texts[0].get_text()


REFUSALS = [
    pytest.param(
        CalibrationConvergenceFigure, empty_session, "no trial recorded", id="convergence"
    ),
    pytest.param(CalibrationTraceFigure, empty_session, "no trial recorded", id="trace, empty"),
    pytest.param(
        CalibrationTraceFigure,
        parameterless_session,
        "no parameter columns found",
        id="trace, none",
    ),
    pytest.param(
        CalibrationTraceFigure, costs_only_session, "no parameter columns found", id="trace, cost"
    ),
    pytest.param(
        CalibrationTrialDistributionFigure,
        empty_session,
        "no trial recorded",
        id="histogram, empty",
    ),
    pytest.param(
        CalibrationTrialDistributionFigure,
        parameterless_session,
        "no parameter columns found",
        id="histogram, none",
    ),
    pytest.param(
        CalibrationTrialDistributionFigure,
        costs_only_session,
        "no parameter columns found",
        id="histogram, cost",
    ),
    pytest.param(
        CalibrationPairplotFigure, empty_session, "no trial recorded", id="pairplot, empty"
    ),
    pytest.param(
        CalibrationPairplotFigure,
        one_parameter_session,
        "at least two parameter columns",
        id="pairplot, one",
    ),
    pytest.param(
        CalibrationPairplotFigure,
        costs_only_session,
        "at least two parameter columns",
        id="pairplot, cost",
    ),
    pytest.param(
        CalibrationLandscapeFigure, empty_session, "no trial recorded", id="landscape, empty"
    ),
    pytest.param(
        CalibrationLandscapeFigure,
        one_parameter_session,
        "at least two parameter columns",
        id="landscape, one",
    ),
    pytest.param(
        CalibrationLandscapeFigure,
        costs_only_session,
        "at least two parameter columns",
        id="landscape, cost",
    ),
    pytest.param(
        CalibrationObjectiveSurfaceFigure,
        costs_only_session,
        "spans exactly two parameters",
        id="surface, cost",
    ),
]


@pytest.mark.parametrize(("figure", "session", "message"), REFUSALS)
def test_refusals(mpl, tmp_path, figure, session, message) -> None:
    with pytest.raises(ValueError, match=message):
        figure().plot(session(tmp_path))


FIGURES = [
    CalibrationConvergenceFigure,
    CalibrationTraceFigure,
    CalibrationLandscapeFigure,
    CalibrationPairplotFigure,
    CalibrationTrialDistributionFigure,
    CalibrationObjectiveSurfaceFigure,
]


@pytest.mark.parametrize("figure", FIGURES)
def test_figures_subject_is_the_session(figure, tmp_path) -> None:
    # The journal is the only source of trials.
    assert figure.spec.subject == "session"
    assert figure().unavailable_reason(calibration_run(tmp_path)) is None
