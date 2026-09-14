"""Regression test for calibration diagnostics and figure rendering.

Runs :func:`hydromodpy.calibration.cases.recession_brutsaert.calibrate_brutsaert`
for each runnable method, builds a synthetic iteration trace matching the
``calibration_iterations`` schema, and verifies:

1. :func:`hydromodpy.calibration.optim.diagnostics.parameter_correlation` returns a
   sane matrix (diagonal = 1, symmetric, finite).
2. :func:`hydromodpy.calibration.optim.diagnostics.convergence_rate` yields a finite
   improvement rate.
3. Each of the five registered calibration figures (``calibration_convergence``,
   ``calibration_trace``, ``calibration_landscape``, ``calibration_posterior``,
   ``calibration_pairplot``, ``calibration_objective_surface``) renders a PNG
   via its public ``plot()`` when given a ``Run``-shaped stub.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from hydromodpy.calibration.cases.recession_brutsaert import (  # noqa: E402
    _DEFAULT_CHRONICLE_TEST,
    BaseflowConfig,
    build_noisy_coarse_sand_chronicle,
    calibrate_brutsaert,
    make_baseflow_simulator,
)
from hydromodpy.calibration.optim.diagnostics import (  # noqa: E402
    convergence_rate,
    iterations_to_dataframe,
    parameter_correlation,
)
from hydromodpy.core.metrics import kge as _kge_metric  # noqa: E402
from hydromodpy.display import get as get_figure  # noqa: E402

GOLDEN_FILE = (
    Path(__file__).resolve().parent / "golden" / "calibration_brutsaert_methods_golden.json"
)
RUNNABLE_METHODS = ("grid_search", "random_search", "scipy_nelder_mead")
FIGURE_NAMES = (
    "calibration_convergence",
    "calibration_trace",
    "calibration_landscape",
    "calibration_posterior",
    "calibration_pairplot",
    "calibration_objective_surface",
)
BOUNDS = {"K": (1.0e-5, 1.0e-3), "Sy": (0.20, 0.35)}

# Figures that don't auto-filter meta columns need explicit ``parameters=``.
_FIGURE_KWARGS: dict[str, dict] = {"calibration_pairplot": {"parameters": ["K", "Sy"]}}


def _kge_cost(observed: np.ndarray, simulated: np.ndarray) -> float:
    """Mirror ``calibrate_brutsaert`` which minimises ``1 - KGE``."""
    return 1.0 - float(_kge_metric(simulated, observed)["kge"])


@pytest.fixture(scope="module")
def _chronicle() -> dict:
    return build_noisy_coarse_sand_chronicle(_DEFAULT_CHRONICLE_TEST)


@pytest.fixture(scope="module")
def _simulator(_chronicle: dict):
    params = _chronicle["params"]
    config = BaseflowConfig(
        Q0=float(params["Q0"]),
        solution=str(params["solution"]),
        b=params.get("b"),
        A=params.get("A"),
        L=params.get("L"),
        ag=float(params.get("ag", 0.7)),
        p=float(params.get("p", 0.346)),
    )
    return make_baseflow_simulator(t_seconds=_chronicle["t_seconds"], model_config=config)


@pytest.fixture(scope="module")
def _golden() -> dict:
    with GOLDEN_FILE.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _build_iteration_trace(
    method: str,
    *,
    golden_row: Mapping,
    simulator,
    q_observed: np.ndarray,
    seed: int,
) -> list[dict]:
    """Build a deterministic iteration trace converging on ``golden_row['x_best']``.

    Matches the ``calibration_iterations`` schema exposed by
    :meth:`CalibrationPersistence.load_iterations`. Parameters are sampled
    log-uniformly over ``K`` and uniformly over ``Sy``; the last row is
    pinned to ``golden_row['x_best']`` so the figure's "best" marker is real.
    """
    n_iter = max(int(golden_row["n_evaluations"]), 4)
    x_best = np.asarray(golden_row["x_best"], dtype=float)
    rng = np.random.default_rng(seed)
    log_lo, log_hi = np.log10(BOUNDS["K"][0]), np.log10(BOUNDS["K"][1])
    k_samples = 10.0 ** rng.uniform(log_lo, log_hi, size=n_iter)
    sy_samples = rng.uniform(BOUNDS["Sy"][0], BOUNDS["Sy"][1], size=n_iter)
    k_samples[-1], sy_samples[-1] = float(x_best[0]), float(x_best[1])

    rows: list[dict] = []
    session_id = f"{method}-session"
    for i, (k, sy) in enumerate(zip(k_samples, sy_samples)):
        cost = _kge_cost(q_observed, simulator(float(k), float(sy)))
        rows.append(
            {
                "iteration": i,
                "sim_id": None,
                "params_hash": None,
                "parameters": {"K": float(k), "Sy": float(sy)},
                "objective_value": float(cost),
                "metrics": None,
                "status": "completed",
                "from_cache": False,
                "duration_s": 0.0,
                "session_id": session_id,
                # Flat columns so figures can read parameters directly.
                "K": float(k),
                "Sy": float(sy),
                "objective": float(cost),
            }
        )
    return rows


class _RunStub:
    """Minimal ``Run``-shaped adapter for figure rendering tests."""

    def __init__(self, session_id: str, iterations: list[dict]) -> None:
        self.sim_id = session_id
        self.name = f"brutsaert-{session_id}"
        self.calibration_iterations = iterations

    def timeseries(self, variable: str, station: str) -> pd.DataFrame:  # noqa: ARG002
        values = [row["objective_value"] for row in self.calibration_iterations]
        idx = pd.date_range("2024-01-01", periods=len(values), freq="D", name="datetime")
        return pd.DataFrame({variable: values}, index=idx)


@pytest.fixture(scope="module")
def _sample_trace(_simulator, _chronicle, _golden) -> list[dict]:
    """Single deterministic trace reused for the figure-rendering sweep."""
    return _build_iteration_trace(
        "grid_search",
        golden_row=_golden["grid_search"],
        simulator=_simulator,
        q_observed=_chronicle["q_observed"],
        seed=11,
    )


def _trace_arrays(trace: list[dict]) -> dict[str, np.ndarray]:
    """Flatten a trace into the arrays a figure's drawn data is checked against."""
    return {
        "K": np.array([row["K"] for row in trace], dtype=float),
        "Sy": np.array([row["Sy"] for row in trace], dtype=float),
        "objective_value": np.array([row["objective_value"] for row in trace], dtype=float),
        "objective": np.array([row["objective"] for row in trace], dtype=float),
    }


def _series(ax, index: int = 0) -> np.ndarray:
    """Return the y-data of the ``index``-th line drawn on ``ax``."""
    return np.asarray(ax.get_lines()[index].get_ydata(), dtype=float)


def _scatter(ax, size: int):
    """Return the PathCollection on ``ax`` whose point count is ``size``.

    An axis can carry several collections (a colorbar's QuadMesh, a
    single-point "best" marker); the trials scatter is the PathCollection
    whose offsets count matches the number of trials fed in.
    """
    for collection in ax.collections:
        if type(collection).__name__ != "PathCollection":
            continue
        if np.asarray(collection.get_offsets()).shape[0] == size:
            return collection
    raise AssertionError(f"no PathCollection with {size} points found on {ax}")


def _check_convergence_figure(fig, arrays: dict[str, np.ndarray]) -> None:
    """calibration_convergence: raw + best-so-far series must match the trace."""
    ax = fig.axes[0]
    lines = ax.get_lines()
    assert len(lines) == 2, "expected a raw objective series and a best-so-far series"
    np.testing.assert_allclose(_series(ax, 0), arrays["objective"])
    np.testing.assert_allclose(_series(ax, 1), np.minimum.accumulate(arrays["objective"]))
    assert ax.get_xlabel() == "Iteration"
    assert ax.get_ylabel() == "objective"


def _check_trace_figure(fig, arrays: dict[str, np.ndarray]) -> None:
    """calibration_trace: one panel per parameter plus the objective, in order."""
    axes = fig.axes
    assert len(axes) == 3, "expected a K panel, a Sy panel and an objective panel"
    for ax, key in zip(axes, ("K", "Sy", "objective_value"), strict=True):
        np.testing.assert_allclose(_series(ax), arrays[key])
        assert ax.get_ylabel() == key
    assert axes[-1].get_xlabel() == "Iteration"


def _check_landscape_figure(fig, arrays: dict[str, np.ndarray]) -> None:
    """calibration_landscape (2 params): scatter of (K, Sy) colored by objective."""
    ax = fig.axes[0]
    scatter = _scatter(ax, arrays["K"].size)
    offsets = np.asarray(scatter.get_offsets())
    np.testing.assert_allclose(offsets[:, 0], arrays["K"])
    np.testing.assert_allclose(offsets[:, 1], arrays["Sy"])
    np.testing.assert_allclose(np.asarray(scatter.get_array()), arrays["objective_value"])
    assert ax.get_xlabel() == "K"
    assert ax.get_ylabel() == "Sy"


def _check_posterior_figure(fig, arrays: dict[str, np.ndarray]) -> None:
    """calibration_posterior: one histogram per parameter, spanning its values."""
    checked = 0
    for ax in fig.axes:
        key = ax.get_xlabel()
        if key not in ("K", "Sy"):
            continue
        checked += 1
        assert sum(patch.get_height() for patch in ax.patches) == pytest.approx(arrays[key].size)
        lo = min(patch.get_x() for patch in ax.patches)
        hi = max(patch.get_x() + patch.get_width() for patch in ax.patches)
        assert lo <= arrays[key].min() and hi >= arrays[key].max()
    assert checked == 2, "expected a K histogram and a Sy histogram"


def _check_pairplot_figure(fig, arrays: dict[str, np.ndarray]) -> None:
    """calibration_pairplot: 2x2 grid, diagonal histograms and off-diagonal scatters."""
    names = ("K", "Sy")
    axes = np.asarray(fig.axes).reshape(2, 2)
    for i, pi in enumerate(names):
        for j, pj in enumerate(names):
            ax = axes[i, j]
            if i == j:
                heights = sum(patch.get_height() for patch in ax.patches)
                assert heights == pytest.approx(arrays[pi].size)
                continue
            scatter = _scatter(ax, arrays["K"].size)
            offsets = np.asarray(scatter.get_offsets())
            np.testing.assert_allclose(offsets[:, 0], arrays[pj])
            np.testing.assert_allclose(offsets[:, 1], arrays[pi])
            np.testing.assert_allclose(np.asarray(scatter.get_array()), arrays["objective_value"])


def _check_objective_surface_figure(fig, arrays: dict[str, np.ndarray]) -> None:
    """calibration_objective_surface: evaluated points and the best marker."""
    ax = fig.axes[0]
    scatter = _scatter(ax, arrays["K"].size)
    offsets = np.asarray(scatter.get_offsets())
    np.testing.assert_allclose(offsets[:, 0], arrays["K"])
    np.testing.assert_allclose(offsets[:, 1], arrays["Sy"])
    np.testing.assert_allclose(np.asarray(scatter.get_array()), arrays["objective_value"])
    best = int(np.argmin(arrays["objective_value"]))
    marker = _scatter(ax, 1)
    marker_xy = np.asarray(marker.get_offsets())[0]
    assert marker_xy == pytest.approx((arrays["K"][best], arrays["Sy"][best]))
    assert ax.get_xlabel() == "K"
    assert ax.get_ylabel() == "Sy"


_FIGURE_CHECKS = {
    "calibration_convergence": _check_convergence_figure,
    "calibration_trace": _check_trace_figure,
    "calibration_landscape": _check_landscape_figure,
    "calibration_posterior": _check_posterior_figure,
    "calibration_pairplot": _check_pairplot_figure,
    "calibration_objective_surface": _check_objective_surface_figure,
}


# ---------------------------------------------------------------------------
# Regression: diagnostics on each method's trace
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", RUNNABLE_METHODS)
def test_calibrate_brutsaert_runs_and_yields_valid_diagnostics(
    method: str,
    _simulator,
    _chronicle,
    _golden,
) -> None:
    if method == "scipy_nelder_mead":
        import scipy  # noqa: F401

    # Confirm the calibration still runs through the new architecture.
    result = calibrate_brutsaert(method=method, objective_metric="kge")
    assert result["method"] == method
    assert len(result["x_best"]) == 2

    trace = _build_iteration_trace(
        method,
        golden_row=_golden[method],
        simulator=_simulator,
        q_observed=_chronicle["q_observed"],
        seed=7 + RUNNABLE_METHODS.index(method),
    )

    corr = parameter_correlation(trace, parameters=["K", "Sy"])
    assert corr.shape == (2, 2)
    assert np.all(np.isfinite(corr.values))
    assert corr.loc["K", "K"] == pytest.approx(1.0, abs=1e-9)
    assert corr.loc["Sy", "Sy"] == pytest.approx(1.0, abs=1e-9)
    assert corr.loc["K", "Sy"] == pytest.approx(corr.loc["Sy", "K"])

    rate = convergence_rate(pd.DataFrame(trace))
    assert np.isfinite(rate["slope"])
    assert np.isfinite(rate["intercept"])
    assert rate["n_points"] >= 2.0


# ---------------------------------------------------------------------------
# Figure rendering (5 + 1 calibration figures)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("figure_name", FIGURE_NAMES)
def test_calibration_figure_renders_png(
    figure_name: str,
    _sample_trace: list[dict],
    tmp_path: Path,
) -> None:
    stub = _RunStub(session_id="grid_search-session", iterations=_sample_trace)
    out_path = tmp_path / f"{figure_name}.png"
    try:
        fig = get_figure(figure_name).plot(
            stub, save_path=out_path, **_FIGURE_KWARGS.get(figure_name, {})
        )
        # A blank axes with only a title would also write a PNG, so the real
        # check is on the Figure's data, not on the file it was saved to.
        _FIGURE_CHECKS[figure_name](fig, _trace_arrays(_sample_trace))
    finally:
        plt.close("all")
    assert out_path.exists(), f"{figure_name} did not write {out_path}"


def test_iterations_dataframe_roundtrip(_sample_trace: list[dict]) -> None:
    df = iterations_to_dataframe(_sample_trace)
    for column in ("iteration", "objective_value", "K", "Sy", "status"):
        assert column in df.columns
    assert len(df) == len(_sample_trace)
