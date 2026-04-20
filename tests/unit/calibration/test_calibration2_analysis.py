"""Unit tests for calibration2 analysis helpers."""

from __future__ import annotations

import pytest

pytest.skip(
    "legacy analysis/calibration superseded by P09 hydromodpy/calibration",
    allow_module_level=True,
)


import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from hydromodpy.analysis.calibration.analysis.diagnostics import (
    build_calibration_result_view,
)
from hydromodpy.analysis.calibration.analysis.objective_surface import (
    build_objective_surface_approximation,
)
from hydromodpy.analysis.calibration.analysis.plotting import (
    apply_parameter_axis_scales,
    build_calibration_performance_lines,
    build_parameter_summary_lines,
    build_posterior_summary_lines,
    plot_objective_surface,
)
from hydromodpy.analysis.calibration.core.results import CalibrationResults


def test_build_calibration_result_view_prefers_chain_when_posterior_not_diverse():
    """Posterior with too few unique states should fallback to chain samples."""
    posterior_samples = np.array([[0.30, 2.00], [0.30, 2.00]], dtype=float)
    chain_samples = np.array([[0.29, 1.90], [0.31, 2.10]], dtype=float)

    result = CalibrationResults(
        method="da_mh_gp",
        x_best=np.array([0.30, 2.00], dtype=float),
        params_best={"a": 0.30, "Kq": 2.00},
        cost_best=0.12,
        score_best=0.88,
        n_evaluations=40,
        samples=posterior_samples,
        metadata={"chain_samples": chain_samples},
    )

    view = build_calibration_result_view(
        result,
        parameter_names=("a", "Kq"),
        posterior_unique_threshold=2,
        rounding_decimals=10,
    )

    assert view["method"] == "da_mh_gp"
    assert view["n_evaluations"] == 40
    assert view["calibration_time_seconds"] is None
    assert np.array_equal(view["posterior_samples"], posterior_samples)
    assert np.array_equal(view["chain_samples"], chain_samples)
    assert np.array_equal(view["sample_source"], chain_samples)


def test_build_parameter_summary_lines_supports_format_overrides():
    """Parameter summary lines should support per-parameter formatting."""
    lines = build_parameter_summary_lines(
        params_true={"K": 1.0e-4, "Sy": 0.28},
        params_best={"K": 1.1e-4, "Sy": 0.30},
        parameter_names=("K", "Sy"),
        format_overrides={"K": ".2e"},
    )

    assert lines[0] == "K true=1.00e-04   K hat=1.10e-04"
    assert lines[1].startswith("Sy true=0.28")


def test_build_posterior_summary_lines_handles_deterministic_results():
    """Deterministic methods should emit a single explicit info line."""
    lines = build_posterior_summary_lines(
        {"has_posterior": False},
        parameter_names=("a", "Kq"),
    )
    assert lines == ["No posterior sample distribution (deterministic method)."]


def test_build_posterior_summary_lines_includes_unique_and_quantiles():
    """Posterior summary should include unique-state and quantile lines."""
    view = {
        "has_posterior": True,
        "posterior_unique": np.array([[0.1, 2.0], [0.2, 2.5]], dtype=float),
        "chain_unique": np.array([[0.1, 2.0]], dtype=float),
        "posterior_samples": np.array(
            [[0.1, 2.0], [0.2, 2.5], [0.3, 3.0]],
            dtype=float,
        ),
    }
    lines = build_posterior_summary_lines(
        view,
        parameter_names=("a", "Kq"),
        quantiles=(0.05, 0.50, 0.95),
        fmt=".3g",
    )

    assert lines[0] == "Unique states: posterior=2  chain=1"
    assert lines[1].startswith("a q05/q50/q95 = ")
    assert lines[2].startswith("Kq q05/q50/q95 = ")


def test_apply_parameter_axis_scales_supports_force_only_mode():
    """Force-only mode should log-scale only selected parameter names."""
    fig, ax = plt.subplots()
    try:
        samples = np.array([[1.0e-4, 0.20], [2.0e-4, 0.30]], dtype=float)
        apply_parameter_axis_scales(
            ax=ax,
            sample_source=samples,
            parameter_names=("K", "Sy"),
            params_true={"K": 1.0e-4, "Sy": 0.28},
            params_best={"K": 1.3e-4, "Sy": 0.30},
            force_log_parameter_names=("K",),
            auto_log_if_positive=False,
        )
        assert ax.get_xscale() == "log"
        assert ax.get_yscale() == "linear"
    finally:
        plt.close(fig)


def test_build_calibration_performance_lines_with_elapsed_time():
    """Performance lines should include both eval count and elapsed time."""
    lines = build_calibration_performance_lines(
        {"n_evaluations": 123, "calibration_time_seconds": 4.567},
        time_fmt=".3f",
    )
    assert lines == ["Calibration performance: n_direct_sim=123  time=4.567 s"]


def test_build_calibration_result_view_reads_elapsed_time_from_metadata():
    """Result-view should expose engine timing when present in metadata."""
    result = CalibrationResults(
        method="simplex",
        x_best=np.array([0.30, 2.00], dtype=float),
        params_best={"a": 0.30, "Kq": 2.00},
        cost_best=0.12,
        score_best=0.88,
        n_evaluations=40,
        samples=None,
        metadata={"calibration_time_seconds": 1.234},
    )
    view = build_calibration_result_view(
        result,
        parameter_names=("a", "Kq"),
    )
    assert view["calibration_time_seconds"] == 1.234


class _DummyEngine:
    """Small deterministic cost oracle for objective-surface tests."""

    @staticmethod
    def cost(vector):
        x = np.asarray(vector, dtype=float).ravel()
        if x.size == 1:
            return float((x[0] - 0.4) ** 2)
        if x.size == 2:
            return float((x[0] - 0.3) ** 2 + 4.0 * (x[1] - 0.7) ** 2)
        return float(np.sum(x**2))


def test_build_objective_surface_approximation_1d():
    surface = build_objective_surface_approximation(
        _DummyEngine(),
        parameter_names=("x",),
        bounds={"x": (0.0, 1.0)},
        n_evaluations=40,
        random_seed=1,
    )
    assert surface["enabled"] is True
    assert surface["n_parameters"] == 1
    assert int(surface["n_direct_evaluations"]) == 40
    assert np.asarray(surface["x_grid"]).ndim == 1
    assert np.asarray(surface["cost_grid"]).ndim == 1


def test_build_objective_surface_approximation_2d():
    surface = build_objective_surface_approximation(
        _DummyEngine(),
        parameter_names=("x", "y"),
        bounds={"x": (0.0, 1.0), "y": (0.0, 1.0)},
        n_evaluations=80,
        random_seed=1,
    )
    assert surface["enabled"] is True
    assert surface["n_parameters"] == 2
    z = np.asarray(surface["cost_grid"], dtype=float)
    assert z.ndim == 2
    assert z.shape[0] > 10 and z.shape[1] > 10


def test_build_objective_surface_approximation_disabled_for_3d():
    surface = build_objective_surface_approximation(
        _DummyEngine(),
        parameter_names=("x", "y", "z"),
        bounds={"x": (0.0, 1.0), "y": (0.0, 1.0), "z": (0.0, 1.0)},
        n_evaluations=50,
        random_seed=1,
    )
    assert surface["enabled"] is False
    assert surface["disabled_reason"] == "parameter_count_ge_3"


def test_plot_objective_surface_smoke_2d():
    surface = build_objective_surface_approximation(
        _DummyEngine(),
        parameter_names=("x", "y"),
        bounds={"x": (0.0, 1.0), "y": (0.0, 1.0)},
        n_evaluations=40,
        random_seed=2,
    )
    fig, ax = plt.subplots()
    try:
        plot_objective_surface(
            ax=ax,
            objective_surface=surface,
            params_true={"x": 0.3, "y": 0.7},
            params_best={"x": 0.28, "y": 0.68},
        )
        assert "Objective surface" in ax.get_title()
    finally:
        plt.close(fig)

