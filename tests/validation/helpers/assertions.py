"""Assertion helpers for validation tests.

Each helper records the value and the threshold before it asserts, so the
documentation shows what the last run measured (see ``results.py``).
"""

from __future__ import annotations

from typing import Any

from .results import record_metric


def assert_metric_below(
    metric_name: str,
    actual: float,
    threshold: float,
    *,
    unit: str = "",
    inclusive: bool = False,
) -> None:
    """Assert that one scalar metric is below the configured threshold."""
    record_metric(metric_name, actual, threshold, op="<=" if inclusive else "<", unit=unit)
    unit_suffix = f" {unit}".rstrip() if unit else ""
    ok = actual <= threshold if inclusive else actual < threshold
    assert ok, (
        f"{metric_name} too high: {actual:.6g}{unit_suffix} "
        f"(threshold {threshold:.6g}{unit_suffix})"
    )


def assert_metric_above(
    metric_name: str,
    actual: float,
    threshold: float,
    *,
    unit: str = "",
    ideal: float | None = None,
) -> None:
    """Assert that one scalar metric is above the configured threshold.

    ``ideal`` is the value of a perfect result (1 for a Nash-Sutcliffe
    efficiency). It is recorded, not checked.
    """
    record_metric(metric_name, actual, threshold, op=">", unit=unit, ideal=ideal)
    unit_suffix = f" {unit}".rstrip() if unit else ""
    assert actual > threshold, (
        f"{metric_name} too low: {actual:.6g}{unit_suffix} (threshold {threshold:.6g}{unit_suffix})"
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
