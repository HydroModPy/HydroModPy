"""Behavioral coverage for calibration display figures."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.display.figures.calibration_convergence import CalibrationConvergenceFigure
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
