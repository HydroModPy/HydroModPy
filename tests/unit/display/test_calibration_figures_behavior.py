"""Behavioral coverage for calibration display figures."""

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


def test_calibration_convergence_plots_iteration_and_best_so_far(mpl, tmp_path) -> None:
    session = flat_session(
        tmp_path,
        {"trial": [1, 2, 3, 4], "kh": [1.0, 2.0, 3.0, 4.0], "cost": [9.0] * 4},
        name="calibration-a",
        components=[{"rmse": value} for value in (5.0, 3.0, 4.0, 2.0)],
    )
    fig, ax = mpl.subplots()

    CalibrationConvergenceFigure().render(session, ax, objective="rmse")

    try:
        assert [line.get_label() for line in ax.lines] == ["iteration", "best so far"]
        assert ax.lines[0].get_ydata().tolist() == [5.0, 3.0, 4.0, 2.0]
        assert ax.lines[1].get_ydata().tolist() == [5.0, 3.0, 3.0, 2.0]
        assert ax.get_ylabel() == "rmse"
        assert "calibration-a" in ax.get_title()
    finally:
        mpl.close(fig)


@pytest.mark.parametrize(
    ("cost", "status", "best"),
    [
        ([4.0, 1.0, 2.0], ["ok"] * 3, [4.0, 1.0, 1.0]),
        ([2.0, 0.5, 1.5], ["ok"] * 3, [2.0, 0.5, 0.5]),
        # A trial that failed publishes no cost. Carrying its NaN forward would
        # flatten the best-so-far curve from that trial on.
        ([2.0, NAN, 1.5], ["ok", "failed", "ok"], [2.0, 2.0, 1.5]),
    ],
    ids=["falls-back-to-the-cost-column", "real-trial-table", "keeps-best-across-a-failed-trial"],
)
def test_calibration_convergence_reads_the_cost_column_of_the_trial_table(
    mpl, tmp_path, cost, status, best
) -> None:
    session = flat_session(
        tmp_path, {"trial": [1, 2, 3], "kh": [1.0, 2.0, 3.0], "cost": cost, "status": status}
    )
    fig, ax = mpl.subplots()

    CalibrationConvergenceFigure().render(session, ax)

    try:
        values = ax.lines[0].get_ydata().tolist()
        assert [v for v in values if v == v] == [v for v in cost if v == v]
        assert ax.lines[1].get_ydata().tolist() == best
        assert ax.get_ylabel() == "cost"
        assert ax.lines[0].get_xdata().tolist() == [1.0, 2.0, 3.0]
    finally:
        mpl.close(fig)


def test_calibration_convergence_rejects_a_session_with_no_trial(mpl, tmp_path) -> None:
    session = journal_session(tmp_path, [])
    fig, ax = mpl.subplots()

    try:
        # The one trial reader names what it could not read from.
        with pytest.raises(ValueError, match="no trial recorded"):
            CalibrationConvergenceFigure().render(session, ax)
    finally:
        mpl.close(fig)


def test_calibration_trace_draws_every_trial_and_saves_png(tmp_path, mpl) -> None:
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

    try:
        assert out.exists() and out.stat().st_size > 0
        assert len(fig.axes) == 2
        assert fig.axes[0].get_ylabel() == "kh"
        assert fig.axes[0].lines[0].get_xdata().tolist() == [10, 11, 12]
        assert fig.axes[0].lines[0].get_ydata().tolist() == [1.0, 9.0, 2.0]
        assert fig.axes[1].get_ylabel() == "cost"
        assert fig.axes[1].lines[0].get_ydata().tolist() == [5.0, 4.0, 3.0]
    finally:
        mpl.close(fig)


def test_calibration_trace_rejects_empty_or_parameterless_sessions(tmp_path) -> None:
    parameterless = flat_session(tmp_path / "a", {"trial": [1], "objective": [1.0]})
    with pytest.raises(ValueError, match="no parameter columns found"):
        CalibrationTraceFigure().plot(parameterless)

    empty = journal_session(tmp_path / "b", [])
    with pytest.raises(ValueError, match="no trial recorded"):
        CalibrationTraceFigure().plot(empty)


def _calibration_run(project, name="calibration-c", status_col=True):
    """Session of six trials with two parameters.

    Parameter samples and objective values are chosen so the minimum
    objective sits at the known point (kh=2.0, sy=0.20).
    """
    data = {
        "trial": [1, 2, 3, 4, 5, 6],
        "kh": [1.0, 1.0, 2.0, 2.0, 3.0, 3.0],
        "sy": [0.10, 0.30, 0.20, 0.40, 0.15, 0.35],
        "objective": [5.0, 4.0, 1.0, 6.0, 3.0, 7.0],
    }
    if status_col:
        data["status"] = ["ok"] * 6
    return flat_session(project, data, name=name)


# --------------------------------------------------------------------------- #
# calibration_trial_distribution
# --------------------------------------------------------------------------- #


def test_calibration_trial_distribution_builds_one_histogram_per_parameter(mpl, tmp_path) -> None:
    run = _calibration_run(tmp_path)

    fig = CalibrationTrialDistributionFigure().plot(run, bins=4, dpi=80)

    try:
        # Two parameter columns -> two used axes plus a colorbar axis.
        param_axes = [ax for ax in fig.axes if ax.get_xlabel() in {"kh", "sy"}]
        assert {ax.get_xlabel() for ax in param_axes} == {"kh", "sy"}
        assert all(ax.get_ylabel() == "count" for ax in param_axes)

        kh_ax = next(ax for ax in param_axes if ax.get_xlabel() == "kh")
        bars = kh_ax.patches
        # bins=4 requested; every sample must fall in exactly one bar.
        assert len(bars) == 4
        assert sum(int(round(b.get_height())) for b in bars) == 6
        assert f"distribution - {run.name}" in fig._suptitle.get_text()
    finally:
        mpl.close(fig)


def test_calibration_trial_distribution_colors_bins_by_mean_objective(mpl, tmp_path) -> None:
    run = _calibration_run(tmp_path)

    fig = CalibrationTrialDistributionFigure().plot(run, bins=4, cmap="viridis", dpi=80)

    try:
        # A colorbar axis appears only when the objective is finite.
        colorbar_axes = [ax for ax in fig.axes if "mean cost" in (ax.get_ylabel() or "")]
        assert len(colorbar_axes) == 1

        kh_ax = next(ax for ax in fig.axes if ax.get_xlabel() == "kh")
        # Bars holding samples must be recolored away from the default steelblue.
        from matplotlib.colors import to_rgba

        steelblue = to_rgba("steelblue")
        non_empty = [b for b in kh_ax.patches if b.get_height() > 0]
        assert any(b.get_facecolor() != steelblue for b in non_empty)
    finally:
        mpl.close(fig)


def test_calibration_trial_distribution_respects_explicit_parameter_list(mpl, tmp_path) -> None:
    run = _calibration_run(tmp_path)

    fig = CalibrationTrialDistributionFigure().plot(run, parameters=["sy"], bins=3, dpi=80)

    try:
        labels = {ax.get_xlabel() for ax in fig.axes if ax.get_xlabel()}
        assert "sy" in labels
        assert "kh" not in labels
    finally:
        mpl.close(fig)


def test_calibration_trial_distribution_rejects_empty_and_parameterless_sessions(tmp_path) -> None:
    empty = journal_session(tmp_path / "a", [])
    with pytest.raises(ValueError, match="no trial recorded"):
        CalibrationTrialDistributionFigure().plot(empty)

    no_params = flat_session(tmp_path / "b", {"trial": [1], "objective": [1.0]})
    with pytest.raises(ValueError, match="no parameter columns found"):
        CalibrationTrialDistributionFigure().plot(no_params)


def test_calibration_trial_distribution_pads_grid_and_saves_png(tmp_path, mpl) -> None:
    # Four parameters with ncols=3 -> a 2x3 grid, so two trailing cells stay
    # empty (axis off). Exercises both the padding loop and the save path.
    run = flat_session(
        tmp_path,
        {
            "trial": list(range(1, 7)),
            "a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "b": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            "c": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
            "d": [0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
            "objective": [5.0, 4.0, 1.0, 6.0, 3.0, 7.0],
        },
        name="cal-4p",
    )
    out = tmp_path / "posterior.png"

    fig = CalibrationTrialDistributionFigure().plot(run, bins=3, save_path=out, dpi=80)

    try:
        assert out.exists() and out.stat().st_size > 0
        labelled = {ax.get_xlabel() for ax in fig.axes if ax.get_xlabel()}
        assert {"a", "b", "c", "d"} <= labelled
        # The two padding cells are switched off (axison False, no patches).
        off_axes = [ax for ax in fig.axes if not ax.axison and not ax.patches]
        assert len(off_axes) >= 2
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# calibration_pairplot
# --------------------------------------------------------------------------- #


def test_calibration_pairplot_grid_shape_and_diagonal_vs_offdiagonal(mpl, tmp_path) -> None:
    run = _calibration_run(tmp_path, status_col=False)
    kh = trial_table(run).frame["kh"].to_numpy(dtype=float)
    sy = trial_table(run).frame["sy"].to_numpy(dtype=float)

    fig = CalibrationPairplotFigure().plot(run, dpi=80)

    try:
        # n_params == 2 -> a 2x2 grid of axes (plus a colorbar axis).
        grid_axes = [ax for ax in fig.axes if ax.collections or ax.patches]
        assert len(grid_axes) >= 4

        # The diagonal cells are histograms (patches, no scatter collection);
        # the off-diagonal cells are scatters with offsets = (x=pj, y=pi).
        diagonal = [ax for ax in grid_axes if ax.patches and not ax.collections]
        scatter = [ax for ax in grid_axes if ax.collections]
        assert len(diagonal) == 2
        assert len(scatter) == 2

        # Off-diagonal (i=1, j=0) plots x=kh (pj), y=sy (pi).
        lower_left = next(
            ax for ax in scatter if ax.get_xlabel() == "kh" and ax.get_ylabel() == "sy"
        )
        offsets = lower_left.collections[0].get_offsets()
        assert sorted(offsets[:, 0].tolist()) == sorted(kh.tolist())
        assert sorted(offsets[:, 1].tolist()) == sorted(sy.tolist())
    finally:
        mpl.close(fig)


def test_calibration_pairplot_colors_scatter_by_objective(mpl, tmp_path) -> None:
    run = _calibration_run(tmp_path, status_col=False)
    obj = trial_table(run).frame["cost"].to_numpy(dtype=float)

    fig = CalibrationPairplotFigure().plot(run, dpi=80)

    try:
        scatter = next(ax for ax in fig.axes if ax.collections)
        coll = scatter.collections[0]
        # The scatter color array is the objective, in row order.
        assert coll.get_array().tolist() == obj.tolist()
        assert coll.get_cmap().name == "viridis"
    finally:
        mpl.close(fig)


def test_calibration_pairplot_rejects_empty_and_too_few_parameters(tmp_path) -> None:
    empty = journal_session(tmp_path / "a", [])
    with pytest.raises(ValueError, match="no trial recorded"):
        CalibrationPairplotFigure().plot(empty)

    one_param = flat_session(tmp_path / "b", {"trial": [1, 2], "kh": [1.0, 2.0]})
    with pytest.raises(ValueError, match="at least two parameter columns"):
        CalibrationPairplotFigure().plot(one_param)


def test_calibration_pairplot_saves_png(tmp_path, mpl) -> None:
    run = _calibration_run(tmp_path, status_col=False)
    out = tmp_path / "pairplot.png"

    fig = CalibrationPairplotFigure().plot(run, save_path=out, dpi=80)

    try:
        assert out.exists() and out.stat().st_size > 0
        assert "pairplot" in fig._suptitle.get_text().lower()
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# calibration_landscape
# --------------------------------------------------------------------------- #


def test_calibration_landscape_two_params_single_scatter_carries_minimum(mpl, tmp_path) -> None:
    run = _calibration_run(tmp_path)
    df = trial_table(run).frame
    obj = df["cost"].to_numpy(dtype=float)
    best = int(obj.argmin())
    best_kh = df["kh"].to_numpy(dtype=float)[best]
    best_sy = df["sy"].to_numpy(dtype=float)[best]

    fig = CalibrationLandscapeFigure().plot(run, cmap="viridis", dpi=80)

    try:
        ax = next(a for a in fig.axes if a.collections)
        assert ax.get_xlabel() == "kh"
        assert ax.get_ylabel() == "sy"

        coll = ax.collections[0]
        # Objective array drives the colormap.
        c = coll.get_array().tolist()
        assert sorted(c) == sorted(obj.tolist())

        # The known minimum (kh=2.0, sy=0.20, obj=1.0) is plotted.
        offsets = coll.get_offsets()
        idx = c.index(min(c))
        assert offsets[idx, 0] == best_kh
        assert offsets[idx, 1] == best_sy
        assert min(c) == 1.0

        assert coll.get_cmap().name == "viridis"
        assert any("cost" in (a.get_ylabel() or "") for a in fig.axes)
        assert f"landscape - {run.name}" in fig._suptitle.get_text()
    finally:
        mpl.close(fig)


def test_calibration_landscape_three_params_upper_triangle_grid(tmp_path, mpl) -> None:
    run = flat_session(
        tmp_path,
        {
            "trial": list(range(1, 7)),
            "kh": [1.0, 1.0, 2.0, 2.0, 3.0, 3.0],
            "sy": [0.1, 0.3, 0.2, 0.4, 0.15, 0.35],
            "rech": [10.0, 20.0, 15.0, 25.0, 12.0, 22.0],
            "objective": [5.0, 4.0, 1.0, 6.0, 3.0, 7.0],
        },
        name="cal-3p",
    )
    out = tmp_path / "landscape_grid.png"

    fig = CalibrationLandscapeFigure().plot(run, save_path=out, dpi=80)

    try:
        assert out.exists() and out.stat().st_size > 0
        # n=3 -> (n-1)x(n-1) = 2x2 grid. The strict upper triangle (j>i)
        # is switched off, leaving exactly 3 active scatter cells (the
        # colorbar axis is excluded by its label).
        scatter_axes = [ax for ax in fig.axes if ax.collections and ax.get_label() != "<colorbar>"]
        assert len(scatter_axes) == 3
        # The three scatter cells each carry all six iteration points.
        assert all(len(ax.collections[0].get_offsets()) == 6 for ax in scatter_axes)
        # Parameters are ordered by name: the bottom row labels the first two.
        xlabels = {ax.get_xlabel() for ax in scatter_axes}
        assert {"kh", "rech"} <= xlabels
    finally:
        mpl.close(fig)


def test_calibration_landscape_reads_the_trials_of_one_phase_of_the_session(tmp_path, mpl) -> None:
    rows = [
        {
            "trial": number,
            "phase": phase,
            "cost": cost,
            "parameters": {"kh": kh, "sy": sy},
        }
        for number, phase, cost, kh, sy in [
            (1, "p1", 5.0, 1.0, 0.1),
            (2, "p1", 4.0, 1.0, 0.3),
            (3, "p1", 1.0, 2.0, 0.2),
            (4, "p2", 6.0, 2.0, 0.4),
        ]
    ]
    session = journal_session(tmp_path, rows, phases=["p1", "p2"])
    table = trial_table(session, phase="p1")

    assert table.frame["kh"].tolist() == [1.0, 1.0, 2.0]
    with pytest.raises(ValueError, match="no trial recorded in phase 'missing'"):
        trial_table(session, phase="missing")


def test_calibration_landscape_rejects_empty_and_too_few_params(tmp_path) -> None:
    empty = journal_session(tmp_path / "a", [])
    with pytest.raises(ValueError, match="no trial recorded"):
        CalibrationLandscapeFigure().plot(empty)

    one_param = flat_session(tmp_path / "b", {"trial": [1, 2], "kh": [1.0, 2.0]})
    with pytest.raises(ValueError, match="need at least two parameter columns"):
        CalibrationLandscapeFigure().plot(one_param)


def test_calibration_landscape_saves_png(tmp_path, mpl) -> None:
    run = _calibration_run(tmp_path)
    out = tmp_path / "landscape.png"

    fig = CalibrationLandscapeFigure().plot(run, save_path=out, dpi=80)

    try:
        assert out.exists() and out.stat().st_size > 0
    finally:
        mpl.close(fig)


def test_calibration_trial_distribution_and_pairplot_render_is_placeholder(mpl, tmp_path) -> None:
    # The grid figures override plot(); render() is a documented no-op that
    # only draws a placeholder note onto a single axis.
    for figure_cls in (
        CalibrationTrialDistributionFigure,
        CalibrationPairplotFigure,
        CalibrationLandscapeFigure,
    ):
        fig, ax = mpl.subplots()
        figure_cls().render(_calibration_run(tmp_path), ax)
        try:
            assert not ax.get_frame_on() or not ax.axison
            assert ax.texts and "own plot()" in ax.texts[0].get_text()
        finally:
            mpl.close(fig)


# --------------------------------------------------------------------------- #
# the row shape a promoted run really carries
# --------------------------------------------------------------------------- #

# One row per trial exactly as the catalog stores it: the sampled parameters
# stay nested in a JSON block, the cost sits in ``cost``, and no
# parameter is spelled as a bare column. The three value sets are disjoint, so
# a panel drawn from the cost cannot be mistaken for a panel drawn from a
# parameter, and a figure that never opens the block has nothing to draw.
CATALOG_KH = [1e-5, 2e-5, 3e-5, 4e-5, 5e-5, 6e-5]
CATALOG_SY = [0.05, 0.30, 0.15, 0.20, 0.10, 0.25]
CATALOG_COST = [5.0, 4.0, 1.0, 6.0, 3.0, 7.0]


def _catalog_run(project, name: str = "calibration-real"):
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


def test_calibration_trace_traces_the_sampled_parameters_not_the_cost(mpl, tmp_path) -> None:
    fig = CalibrationTraceFigure().plot(_catalog_run(tmp_path), dpi=80)

    try:
        # Two parameters were sampled, so two parameter panels then the cost.
        assert [ax.get_ylabel() for ax in fig.axes] == ["kh", "sy", "cost"]
        assert fig.axes[0].lines[0].get_ydata().tolist() == CATALOG_KH
        assert fig.axes[1].lines[0].get_ydata().tolist() == CATALOG_SY
        assert fig.axes[2].lines[0].get_ydata().tolist() == CATALOG_COST
        assert fig.axes[0].lines[0].get_xdata().tolist() == [1, 2, 3, 4, 5, 6]
    finally:
        mpl.close(fig)


def test_calibration_trial_distribution_histograms_the_parameters_not_the_cost(
    mpl, tmp_path
) -> None:
    fig = CalibrationTrialDistributionFigure().plot(_catalog_run(tmp_path), bins=3, dpi=80)

    try:
        assert {ax.get_xlabel() for ax in fig.axes if ax.get_xlabel()} == {"kh", "sy"}
        kh_ax = next(ax for ax in fig.axes if ax.get_xlabel() == "kh")
        # The bars span the sampled range, which no cost value lies in.
        left = min(bar.get_x() for bar in kh_ax.patches)
        right = max(bar.get_x() + bar.get_width() for bar in kh_ax.patches)
        assert left == pytest.approx(min(CATALOG_KH))
        assert right == pytest.approx(max(CATALOG_KH))
        assert sum(int(round(bar.get_height())) for bar in kh_ax.patches) == len(CATALOG_KH)
    finally:
        mpl.close(fig)


def test_calibration_landscape_spans_the_two_sampled_parameters(mpl, tmp_path) -> None:
    fig = CalibrationLandscapeFigure().plot(_catalog_run(tmp_path), dpi=80)

    try:
        ax = next(a for a in fig.axes if a.collections)
        assert (ax.get_xlabel(), ax.get_ylabel()) == ("kh", "sy")
        offsets = ax.collections[0].get_offsets()
        assert offsets[:, 0].tolist() == CATALOG_KH
        assert offsets[:, 1].tolist() == CATALOG_SY
        # The cost colors the points; it is never one of the two axes.
        assert ax.collections[0].get_array().tolist() == CATALOG_COST
    finally:
        mpl.close(fig)


def test_calibration_pairplot_reads_the_nested_parameter_block(mpl, tmp_path) -> None:
    fig = CalibrationPairplotFigure().plot(_catalog_run(tmp_path), dpi=80)

    try:
        assert {ax.get_xlabel() for ax in fig.axes if ax.get_xlabel()} == {"kh", "sy"}
        scatter = next(ax for ax in fig.axes if ax.collections and ax.get_xlabel() == "kh")
        offsets = scatter.collections[0].get_offsets()
        assert offsets[:, 0].tolist() == CATALOG_KH
        assert offsets[:, 1].tolist() == CATALOG_SY
    finally:
        mpl.close(fig)


def test_calibration_objective_surface_spans_the_nested_parameters(mpl, tmp_path) -> None:
    pytest.importorskip("scipy")

    fig = CalibrationObjectiveSurfaceFigure().plot(_catalog_run(tmp_path), dpi=80)

    try:
        surface = fig.axes[0]
        assert (surface.get_xlabel(), surface.get_ylabel()) == ("kh", "sy")
        assert any("cost" in (ax.get_ylabel() or "") for ax in fig.axes)
        # The best trial is the one the cost says, and it is marked there.
        best = CATALOG_COST.index(min(CATALOG_COST))
        star = next(
            coll
            for coll in surface.collections
            if len(coll.get_offsets()) == 1 and coll.get_offsets()[0][0] > 0.0
        )
        assert star.get_offsets()[0].tolist() == [CATALOG_KH[best], CATALOG_SY[best]]
    finally:
        mpl.close(fig)


def test_a_calibration_that_sampled_nothing_is_refused_by_every_grid_figure(tmp_path) -> None:
    # A trial table whose only numeric column is the cost: the figures must
    # say so instead of drawing the cost under a parameter label.
    costs_only = journal_session(
        tmp_path,
        [
            {"trial": 1, "parameters": {}, "cost": 2.0},
            {"trial": 2, "parameters": {}, "cost": 1.0},
        ],
    )

    with pytest.raises(ValueError, match="no parameter columns found"):
        CalibrationTraceFigure().plot(costs_only)
    with pytest.raises(ValueError, match="no parameter columns found"):
        CalibrationTrialDistributionFigure().plot(costs_only)
    with pytest.raises(ValueError, match="at least two parameter columns"):
        CalibrationLandscapeFigure().plot(costs_only)
    with pytest.raises(ValueError, match="at least two parameter columns"):
        CalibrationPairplotFigure().plot(costs_only)
    with pytest.raises(ValueError, match="spans exactly two parameters"):
        CalibrationObjectiveSurfaceFigure().plot(costs_only)


@pytest.mark.parametrize(
    "figure",
    [
        CalibrationConvergenceFigure,
        CalibrationTraceFigure,
        CalibrationLandscapeFigure,
        CalibrationPairplotFigure,
        CalibrationTrialDistributionFigure,
        CalibrationObjectiveSurfaceFigure,
    ],
)
def test_the_calibration_figures_draw_a_session_and_refuse_one_without_trials(
    figure, tmp_path
) -> None:
    """The subject is the session, and its journal is the only source of trials."""
    assert figure.spec.subject == "session"
    assert figure().unavailable_reason(_calibration_run(tmp_path)) is None
