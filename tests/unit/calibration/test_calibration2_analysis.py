"""Unit tests for calibration2 analysis helpers."""

from __future__ import annotations

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from hydromodpy.calibration2.analysis.diagnostics import (
    build_calibration_result_view,
)
from hydromodpy.calibration2.analysis.plotting import (
    apply_parameter_axis_scales,
    build_parameter_summary_lines,
    build_posterior_summary_lines,
)
from hydromodpy.calibration2.core.results import CalibrationResults


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
