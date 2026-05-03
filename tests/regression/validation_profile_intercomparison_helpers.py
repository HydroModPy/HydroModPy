"""Helpers for validation-case profile intercomparison regressions."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.regression.golden_utils import (
    assert_required_executables,
    resolve_tiered_golden_file,
    update_or_assert_goldens,
)


def _profile_error_stats(reference_values: np.ndarray, candidate_values: np.ndarray) -> dict[str, Any]:
    reference = np.asarray(reference_values, dtype=float).reshape(-1)
    candidate = np.asarray(candidate_values, dtype=float).reshape(-1)
    assert reference.shape == candidate.shape, (
        f"Profile shape mismatch: {reference.shape} != {candidate.shape}"
    )
    signed = candidate - reference
    abs_err = np.abs(signed)
    return {
        "n_points": int(reference.size),
        "bias": float(np.mean(signed)),
        "mae": float(np.mean(abs_err)),
        "rmse": float(np.sqrt(np.mean(signed**2))),
        "max_abs_error": float(np.max(abs_err)),
    }


def build_validation_profile_intercomparison_signature(
    *,
    case_id: str,
    reference_solver: str,
    candidate_solver: str,
    reference_comparison: Any,
    candidate_comparison: Any,
) -> dict[str, Any]:
    """Build a compact signature comparing two validation-case profiles."""
    return {
        "signature_schema_version": "validation_profile_intercomparison_v1",
        "case_id": str(case_id),
        "reference_solver": str(reference_solver),
        "candidate_solver": str(candidate_solver),
        "observable": str(getattr(reference_comparison, "observable_name", "")),
        "profile_pair": _profile_error_stats(
            np.asarray(reference_comparison.numerical_profile, dtype=float),
            np.asarray(candidate_comparison.numerical_profile, dtype=float),
        ),
        "reference_against_analytical": {
            "rmse": float(reference_comparison.rms_error),
            "max_abs_error": float(reference_comparison.max_error),
            "row_spread": float(reference_comparison.row_spread),
        },
        "candidate_against_analytical": {
            "rmse": float(candidate_comparison.rms_error),
            "max_abs_error": float(candidate_comparison.max_error),
            "row_spread": float(candidate_comparison.row_spread),
        },
    }


def assert_validation_profile_intercomparison_limits(
    signature: dict[str, Any],
    *,
    limits: dict[str, float],
) -> None:
    """Assert explicit acceptability limits for profile intercomparisons."""
    pair = signature["profile_pair"]
    reference = signature["reference_against_analytical"]
    candidate = signature["candidate_against_analytical"]
    if "pair_rmse_max" in limits:
        assert float(pair["rmse"]) <= limits["pair_rmse_max"]
    if "pair_max_abs_error_max" in limits:
        assert float(pair["max_abs_error"]) <= limits["pair_max_abs_error_max"]
    if "reference_rmse_max" in limits:
        assert float(reference["rmse"]) <= limits["reference_rmse_max"]
    if "candidate_rmse_max" in limits:
        assert float(candidate["rmse"]) <= limits["candidate_rmse_max"]
    if "candidate_max_abs_error_max" in limits:
        assert float(candidate["max_abs_error"]) <= limits["candidate_max_abs_error_max"]


def _close_comparison_store(comparison: Any) -> None:
    result = getattr(comparison, "result", None)
    store = getattr(result, "store", None)
    if store is None:
        return
    close = getattr(store, "close", None)
    if close is not None:
        close()


def run_validation_profile_intercomparison_regression(
    *,
    test_file: str | Path,
    comparison_module: str,
    comparison_function: str,
    case_id: str,
    reference_solver: str,
    candidate_solver: str,
    golden_filename: str,
    update_goldens: bool,
    limits: dict[str, float],
    timeout: int = 1800,
) -> dict[str, Any]:
    """Run two validation variants and compare their final head profiles."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )
    try:
        runner = getattr(importlib.import_module(comparison_module), comparison_function)
    except ModuleNotFoundError as exc:
        pytest.skip(f"Validation profile intercomparison dependency is missing: {exc.name}")

    reference_comparison = None
    candidate_comparison = None
    try:
        reference_comparison = runner(
            caller_file=test_file,
            solver=reference_solver,
            timeout=timeout,
        )
        candidate_comparison = runner(
            caller_file=test_file,
            solver=candidate_solver,
            timeout=timeout,
        )
        signature = build_validation_profile_intercomparison_signature(
            case_id=case_id,
            reference_solver=reference_solver,
            candidate_solver=candidate_solver,
            reference_comparison=reference_comparison,
            candidate_comparison=candidate_comparison,
        )
    finally:
        if reference_comparison is not None:
            _close_comparison_store(reference_comparison)
        if candidate_comparison is not None:
            _close_comparison_store(candidate_comparison)

    assert_validation_profile_intercomparison_limits(signature, limits=limits)
    update_or_assert_goldens(
        actual={"intercomparison_expected": signature},
        golden_reference_file=resolve_tiered_golden_file(
            test_file=test_file,
            filename=golden_filename,
        ),
        update_goldens=update_goldens,
    )
    return signature
