"""Shared assertion helpers for the test suite.

The helpers collect *all* mismatches before raising, instead of short-
circuiting on the first failure, so a single assertion fail produces an
actionable diff across many statistics/columns.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from tests._helpers.signatures import FieldSignature


DEFAULT_SIGNATURE_FIELDS: tuple[str, ...] = (
    "min", "p05", "p25", "p50", "p75", "p95", "max",
    "mean", "std", "sum", "moment_1",
)


def assert_signature_matches(
    actual: FieldSignature,
    expected: FieldSignature,
    *,
    rel: float = 1e-4,
    abs_: float = 1e-6,
    fields: Iterable[str] = DEFAULT_SIGNATURE_FIELDS,
) -> None:
    """Fail if any listed statistic differs by more than ``rel`` or ``abs_``."""
    mismatches: list[str] = []
    if actual.shape != expected.shape:
        mismatches.append(f"shape: actual={actual.shape}, expected={expected.shape}")
    if actual.count != expected.count:
        mismatches.append(f"count: actual={actual.count}, expected={expected.count}")
    for field_name in fields:
        a = getattr(actual, field_name)
        e = getattr(expected, field_name)
        if not np.isclose(a, e, rtol=rel, atol=abs_, equal_nan=True):
            mismatches.append(f"{field_name}: actual={a:.6g}, expected={e:.6g}")
    if mismatches:
        raise AssertionError("Signature mismatch:\n  " + "\n  ".join(mismatches))


def assert_array_close(
    actual: np.ndarray,
    expected: np.ndarray,
    *,
    rel: float = 1e-6,
    abs_: float = 1e-9,
    name: str = "array",
) -> None:
    """Fail if arrays differ in shape or beyond the tolerance."""
    actual = np.asarray(actual)
    expected = np.asarray(expected)
    if actual.shape != expected.shape:
        raise AssertionError(
            f"{name}.shape mismatch: actual={actual.shape}, expected={expected.shape}"
        )
    diff = np.abs(actual - expected)
    tol = abs_ + rel * np.abs(expected)
    bad = diff > tol
    if np.any(bad):
        n_bad = int(bad.sum())
        max_err = float(diff.max())
        raise AssertionError(
            f"{name}: {n_bad}/{actual.size} values exceed tolerance "
            f"(rel={rel}, abs={abs_}). max_err={max_err:.6g}"
        )


def assert_dataframe_equal_modulo_dtype(
    actual: pd.DataFrame,
    expected: pd.DataFrame,
    *,
    rel: float = 1e-6,
    abs_: float = 1e-9,
) -> None:
    """Compare DataFrames ignoring column dtype (useful across DuckDB/Pandas)."""
    if list(actual.columns) != list(expected.columns):
        raise AssertionError(
            f"columns mismatch: actual={list(actual.columns)}, "
            f"expected={list(expected.columns)}"
        )
    if len(actual) != len(expected):
        raise AssertionError(
            f"row count mismatch: actual={len(actual)}, expected={len(expected)}"
        )
    for col in actual.columns:
        a = actual[col].to_numpy()
        e = expected[col].to_numpy()
        if np.issubdtype(a.dtype, np.number) and np.issubdtype(e.dtype, np.number):
            assert_array_close(a, e, rel=rel, abs_=abs_, name=f"column[{col}]")
        else:
            if not np.array_equal(a, e):
                raise AssertionError(f"column[{col}]: values differ")
