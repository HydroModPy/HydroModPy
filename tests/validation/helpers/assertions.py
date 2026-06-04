"""Assertion helpers for validation tests."""

from __future__ import annotations

from typing import Any


def assert_metric_below(
    metric_name: str, actual: float, threshold: float, *, unit: str = ""
) -> None:
    """Assert that one scalar metric is below the configured threshold."""
    unit_suffix = f" {unit}".rstrip() if unit else ""
    assert actual < threshold, (
        f"{metric_name} too high: {actual:.6g}{unit_suffix} "
        f"(threshold {threshold:.6g}{unit_suffix})"
    )


def assert_space_time_metrics(comparison: Any) -> None:
    """Assert the space-time RMSE, max abs error, and cross-row spread of one comparison.

    Each tolerance is read from the comparison's own ``space_time`` block, so every
    scenario keeps its own thresholds (including its cross-row spread envelope).
    """
    space_time_tol = dict(comparison.tolerances.get("space_time", {}))
    assert_metric_below(
        "Space-time RMSE",
        comparison.space_time_rmse,
        float(space_time_tol["rmse"]),
        unit="m",
    )
    assert_metric_below(
        "Space-time max abs error",
        comparison.space_time_max_error,
        float(space_time_tol["max_abs_error"]),
        unit="m",
    )
    assert_metric_below(
        "Cross-row head spread",
        comparison.row_spread,
        float(space_time_tol["row_spread"]),
        unit="m",
    )


def assert_profile_metrics(comparison: Any) -> None:
    """Assert the final-profile RMSE of one comparison against its own tolerance."""
    final_profile_tol = dict(comparison.tolerances.get("final_profile", {}))
    assert_metric_below(
        "Final-profile RMSE",
        comparison.final_profile_rmse,
        float(final_profile_tol["rmse"]),
        unit="m",
    )
