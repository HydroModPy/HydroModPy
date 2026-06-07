"""Behavioral coverage for calibration display figures."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.display.figures.calibration_convergence import CalibrationConvergenceFigure
from hydromodpy.display.figures.calibration_landscape import CalibrationLandscapeFigure
from hydromodpy.display.figures.calibration_pairplot import CalibrationPairplotFigure
from hydromodpy.display.figures.calibration_posterior import CalibrationPosteriorFigure
from hydromodpy.display.figures.calibration_trace import CalibrationTraceFigure


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


class _ConvergenceRun:
    sim_id = "sim-a"
    name = "calibration-a"

    def timeseries(self, variable: str, *, station: str):
        assert variable == "rmse"
        assert station == "_calibration"
        return pd.Series([5.0, 3.0, 4.0, 2.0], name=variable)


def test_calibration_convergence_plots_iteration_and_best_so_far(mpl) -> None:
    fig, ax = mpl.subplots()

    CalibrationConvergenceFigure().render(_ConvergenceRun(), ax, objective="rmse")

    try:
        assert [line.get_label() for line in ax.lines] == ["iteration", "best so far"]
        assert ax.lines[0].get_ydata().tolist() == [5.0, 3.0, 4.0, 2.0]
        assert ax.lines[1].get_ydata().tolist() == [5.0, 3.0, 3.0, 2.0]
        assert ax.get_ylabel() == "rmse"
        assert "calibration-a" in ax.get_title()
    finally:
        mpl.close(fig)


def test_calibration_convergence_falls_back_to_iteration_table(mpl) -> None:
    run = SimpleNamespace(
        sim_id="sim-a",
        name=None,
        calibration_iterations=pd.Series([4.0, 1.0, 2.0]),
        timeseries=lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyError("missing")),
    )
    fig, ax = mpl.subplots()

    CalibrationConvergenceFigure().render(run, ax)

    try:
        assert ax.lines[0].get_ydata().tolist() == [4.0, 1.0, 2.0]
        assert ax.lines[1].get_ydata().tolist() == [4.0, 1.0, 1.0]
    finally:
        mpl.close(fig)


def test_calibration_convergence_rejects_missing_iteration_data(mpl) -> None:
    run = SimpleNamespace(
        sim_id="sim-a",
        name=None,
        timeseries=lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyError("missing")),
    )
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="no iteration data available"):
            CalibrationConvergenceFigure().render(run, ax)
    finally:
        mpl.close(fig)


def test_calibration_trace_filters_session_and_saves_png(tmp_path, mpl) -> None:
    run = SimpleNamespace(
        sim_id="sim-a",
        name="calibration-a",
        calibration_iterations=pd.DataFrame(
            {
                "iter": [10, 11, 12],
                "session_id": ["accepted", "rejected", "accepted"],
                "kh": [1.0, 9.0, 2.0],
                "sy": [0.1, 0.9, 0.2],
                "objective": [5.0, 4.0, 3.0],
                "status": ["ok", "failed", "ok"],
            }
        ),
    )
    out = tmp_path / "trace.png"

    fig = CalibrationTraceFigure().plot(
        run,
        parameters=["kh"],
        objective="objective",
        session_id="accepted",
        save_path=out,
        dpi=80,
    )

    try:
        assert out.exists() and out.stat().st_size > 0
        assert len(fig.axes) == 2
        assert fig.axes[0].get_ylabel() == "kh"
        assert fig.axes[0].lines[0].get_xdata().tolist() == [10, 12]
        assert fig.axes[0].lines[0].get_ydata().tolist() == [1.0, 2.0]
        assert fig.axes[1].get_ylabel() == "objective"
        assert fig.axes[1].lines[0].get_ydata().tolist() == [5.0, 3.0]
    finally:
        mpl.close(fig)


def test_calibration_trace_rejects_empty_or_parameterless_iteration_rows() -> None:
    parameterless = SimpleNamespace(
        sim_id="sim-a",
        name=None,
        calibration_iterations=pd.DataFrame({"iter": [0], "objective": [1.0], "status": ["ok"]}),
    )
    with pytest.raises(ValueError, match="no parameter columns found"):
        CalibrationTraceFigure().plot(parameterless)

    rows = SimpleNamespace(
        sim_id="sim-a",
        name=None,
        calibration_iterations=pd.DataFrame(
            {
                "iter": [0],
                "session_id": ["present"],
                "kh": [1.0],
                "objective": [2.0],
            }
        ),
    )
    with pytest.raises(ValueError, match="no iteration rows available"):
        CalibrationTraceFigure().plot(rows, session_id="missing")


def _calibration_run(name="calibration-c", session_col=False, status_col=True):
    """Fake Run carrying a calibration_iterations table with two parameters.

    Parameter samples and objective values are chosen so the minimum
    objective sits at the known point (kh=2.0, sy=0.20).
    """
    data = {
        "iter": [0, 1, 2, 3, 4, 5],
        "kh": [1.0, 1.0, 2.0, 2.0, 3.0, 3.0],
        "sy": [0.10, 0.30, 0.20, 0.40, 0.15, 0.35],
        "objective": [5.0, 4.0, 1.0, 6.0, 3.0, 7.0],
    }
    if status_col:
        data["status"] = ["ok"] * 6
    if session_col:
        data["session_id"] = ["s1", "s1", "s1", "s2", "s2", "s2"]
    return SimpleNamespace(
        sim_id="sim-c",
        name=name,
        calibration_iterations=pd.DataFrame(data),
    )


# --------------------------------------------------------------------------- #
# calibration_posterior
# --------------------------------------------------------------------------- #


def test_calibration_posterior_builds_one_histogram_per_parameter(mpl) -> None:
    run = _calibration_run()

    fig = CalibrationPosteriorFigure().plot(run, bins=4, dpi=80)

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
        assert f"posteriors - {run.name}" in fig._suptitle.get_text()
    finally:
        mpl.close(fig)


def test_calibration_posterior_colors_bins_by_mean_objective(mpl) -> None:
    run = _calibration_run()

    fig = CalibrationPosteriorFigure().plot(run, bins=4, cmap="viridis", dpi=80)

    try:
        # A colorbar axis appears only when the objective is finite.
        colorbar_axes = [ax for ax in fig.axes if "mean objective" in (ax.get_ylabel() or "")]
        assert len(colorbar_axes) == 1

        kh_ax = next(ax for ax in fig.axes if ax.get_xlabel() == "kh")
        # Bars holding samples must be recolored away from the default steelblue.
        from matplotlib.colors import to_rgba

        steelblue = to_rgba("steelblue")
        non_empty = [b for b in kh_ax.patches if b.get_height() > 0]
        assert any(b.get_facecolor() != steelblue for b in non_empty)
    finally:
        mpl.close(fig)


def test_calibration_posterior_respects_explicit_parameter_list(mpl) -> None:
    run = _calibration_run()

    fig = CalibrationPosteriorFigure().plot(run, parameters=["sy"], bins=3, dpi=80)

    try:
        labels = {ax.get_xlabel() for ax in fig.axes if ax.get_xlabel()}
        assert "sy" in labels
        assert "kh" not in labels
    finally:
        mpl.close(fig)


def test_calibration_posterior_rejects_missing_and_empty_tables() -> None:
    no_table = SimpleNamespace(sim_id="sim-c", name=None, calibration_iterations=None)
    with pytest.raises(ValueError, match="no calibration_iterations"):
        CalibrationPosteriorFigure().plot(no_table)

    empty_session = _calibration_run(session_col=True)
    with pytest.raises(ValueError, match="no iteration rows available"):
        CalibrationPosteriorFigure().plot(empty_session, session_id="missing")

    no_params = SimpleNamespace(
        sim_id="sim-c",
        name=None,
        calibration_iterations=pd.DataFrame({"iter": [0], "objective": [1.0]}),
    )
    with pytest.raises(ValueError, match="no parameter columns found"):
        CalibrationPosteriorFigure().plot(no_params)


def test_calibration_posterior_pads_grid_and_saves_png(tmp_path, mpl) -> None:
    # Four parameters with ncols=3 -> a 2x3 grid, so two trailing cells stay
    # empty (axis off). Exercises both the padding loop and the save path.
    df = pd.DataFrame(
        {
            "iter": list(range(6)),
            "a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "b": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            "c": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
            "d": [0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
            "objective": [5.0, 4.0, 1.0, 6.0, 3.0, 7.0],
        }
    )
    run = SimpleNamespace(sim_id="sim-e", name="cal-4p", calibration_iterations=df)
    out = tmp_path / "posterior.png"

    fig = CalibrationPosteriorFigure().plot(run, bins=3, save_path=out, dpi=80)

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


def test_calibration_pairplot_grid_shape_and_diagonal_vs_offdiagonal(mpl) -> None:
    run = _calibration_run(status_col=False)
    kh = run.calibration_iterations["kh"].to_numpy(dtype=float)
    sy = run.calibration_iterations["sy"].to_numpy(dtype=float)

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


def test_calibration_pairplot_colors_scatter_by_objective(mpl) -> None:
    run = _calibration_run(status_col=False)
    obj = run.calibration_iterations["objective"].to_numpy(dtype=float)

    fig = CalibrationPairplotFigure().plot(run, dpi=80)

    try:
        scatter = next(ax for ax in fig.axes if ax.collections)
        coll = scatter.collections[0]
        # The scatter color array is the objective, in row order.
        assert coll.get_array().tolist() == obj.tolist()
        assert coll.get_cmap().name == "viridis"
    finally:
        mpl.close(fig)


def test_calibration_pairplot_rejects_too_few_parameters() -> None:
    no_table = SimpleNamespace(sim_id="sim-c", name=None, calibration_iterations=None)
    with pytest.raises(ValueError, match="no calibration_iterations"):
        CalibrationPairplotFigure().plot(no_table)

    one_param = SimpleNamespace(
        sim_id="sim-c",
        name=None,
        calibration_iterations=pd.DataFrame({"iter": [0, 1], "kh": [1.0, 2.0]}),
    )
    with pytest.raises(ValueError, match="at least two parameter columns"):
        CalibrationPairplotFigure().plot(one_param)


def test_calibration_pairplot_saves_png(tmp_path, mpl) -> None:
    run = _calibration_run(status_col=False)
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


def test_calibration_landscape_two_params_single_scatter_carries_minimum(mpl) -> None:
    run = _calibration_run()
    df = run.calibration_iterations
    obj = df["objective"].to_numpy(dtype=float)
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
        assert any("objective" in (a.get_ylabel() or "") for a in fig.axes)
        assert f"landscape - {run.name}" in fig._suptitle.get_text()
    finally:
        mpl.close(fig)


def test_calibration_landscape_three_params_upper_triangle_grid(tmp_path, mpl) -> None:
    df = pd.DataFrame(
        {
            "iter": list(range(6)),
            "kh": [1.0, 1.0, 2.0, 2.0, 3.0, 3.0],
            "sy": [0.1, 0.3, 0.2, 0.4, 0.15, 0.35],
            "rech": [10.0, 20.0, 15.0, 25.0, 12.0, 22.0],
            "objective": [5.0, 4.0, 1.0, 6.0, 3.0, 7.0],
        }
    )
    run = SimpleNamespace(sim_id="sim-d", name="cal-3p", calibration_iterations=df)
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
        # Bottom row carries x labels for the first two parameters.
        xlabels = {ax.get_xlabel() for ax in scatter_axes}
        assert {"kh", "sy"} <= xlabels
    finally:
        mpl.close(fig)


def test_calibration_landscape_filters_session(mpl) -> None:
    run = _calibration_run(session_col=True)

    fig = CalibrationLandscapeFigure().plot(run, session_id="s1", dpi=80)

    try:
        ax = next(a for a in fig.axes if a.collections)
        offsets = ax.collections[0].get_offsets()
        # Only the three s1 rows survive the session filter.
        assert len(offsets) == 3
        assert sorted(offsets[:, 0].tolist()) == [1.0, 1.0, 2.0]
    finally:
        mpl.close(fig)


def test_calibration_landscape_rejects_missing_empty_and_too_few_params() -> None:
    no_table = SimpleNamespace(sim_id="sim-c", name=None, calibration_iterations=None)
    with pytest.raises(ValueError, match="no calibration_iterations"):
        CalibrationLandscapeFigure().plot(no_table)

    empty_session = _calibration_run(session_col=True)
    with pytest.raises(ValueError, match="no iteration rows available"):
        CalibrationLandscapeFigure().plot(empty_session, session_id="missing")

    one_param = SimpleNamespace(
        sim_id="sim-c",
        name=None,
        calibration_iterations=pd.DataFrame({"iter": [0, 1], "kh": [1.0, 2.0]}),
    )
    with pytest.raises(ValueError, match="need at least two parameter columns"):
        CalibrationLandscapeFigure().plot(one_param)


def test_calibration_landscape_saves_png(tmp_path, mpl) -> None:
    run = _calibration_run()
    out = tmp_path / "landscape.png"

    fig = CalibrationLandscapeFigure().plot(run, save_path=out, dpi=80)

    try:
        assert out.exists() and out.stat().st_size > 0
    finally:
        mpl.close(fig)


def test_calibration_posterior_and_pairplot_render_is_placeholder(mpl) -> None:
    # The grid figures override plot(); render() is a documented no-op that
    # only draws a placeholder note onto a single axis.
    for figure_cls in (
        CalibrationPosteriorFigure,
        CalibrationPairplotFigure,
        CalibrationLandscapeFigure,
    ):
        fig, ax = mpl.subplots()
        figure_cls().render(_calibration_run(), ax)
        try:
            assert not ax.get_frame_on() or not ax.axison
            assert ax.texts and "own plot()" in ax.texts[0].get_text()
        finally:
            mpl.close(fig)
