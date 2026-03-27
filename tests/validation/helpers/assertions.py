"""Assertion helpers for validation tests."""

from __future__ import annotations


def assert_metric_below(metric_name: str, actual: float, threshold: float, *, unit: str = "") -> None:
    """Assert that one scalar metric is below the configured threshold."""
    unit_suffix = f" {unit}".rstrip() if unit else ""
    assert actual < threshold, (
        f"{metric_name} too high: {actual:.6g}{unit_suffix} "
        f"(threshold {threshold:.6g}{unit_suffix})"
    )
