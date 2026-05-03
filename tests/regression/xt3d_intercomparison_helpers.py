"""Shared helpers for XT3D method-choice intercomparison regressions."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from tests.regression.golden_utils import (
    assert_required_executables,
    resolve_tiered_golden_file,
    update_or_assert_goldens,
)

ROW_NUMERIC_FIELDS = (
    "rmse_without_xt3d",
    "rmse_with_xt3d",
    "rmse_delta",
    "rmse_improvement_factor",
    "max_error_without_xt3d",
    "max_error_with_xt3d",
)


def build_xt3d_method_choice_signature(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic signature from an XT3D method-choice payload."""
    rows: dict[str, dict[str, Any]] = {}
    for row in sorted(payload.get("rows", []), key=lambda item: str(item.get("slug", ""))):
        slug = str(row.get("slug", ""))
        rows[slug] = {
            "title": str(row.get("title", "")),
            "improved": bool(row.get("improved", False)),
        }
        for field in ROW_NUMERIC_FIELDS:
            rows[slug][field] = float(row[field])

    return {
        "signature_schema_version": "xt3d_method_choice_signature_v1",
        "comparison_label": str(payload.get("comparison_label", "")),
        "case_count": int(payload.get("case_count", 0)),
        "improved_count": int(payload.get("improved_count", 0)),
        "regressed_count": int(payload.get("regressed_count", 0)),
        "strong_improvement_count": int(payload.get("strong_improvement_count", 0)),
        "rows": rows,
    }


def assert_xt3d_method_choice_limits(
    signature: dict[str, Any],
    *,
    limits: dict[str, dict[str, float]],
) -> None:
    """Assert explicit acceptability limits for selected XT3D comparison rows."""
    rows = signature.get("rows", {})
    assert isinstance(rows, dict)
    for slug, row_limits in limits.items():
        assert slug in rows, f"Missing XT3D comparison row: {slug}"
        row = rows[slug]
        assert isinstance(row, dict)
        assert row["improved"] is True
        if "rmse_with_xt3d_max" in row_limits:
            assert float(row["rmse_with_xt3d"]) <= row_limits["rmse_with_xt3d_max"]
        if "max_error_with_xt3d_max" in row_limits:
            assert float(row["max_error_with_xt3d"]) <= row_limits["max_error_with_xt3d_max"]
        if "rmse_improvement_factor_min" in row_limits:
            assert (
                float(row["rmse_improvement_factor"]) >= row_limits["rmse_improvement_factor_min"]
            )


def run_xt3d_method_choice_regression(
    *,
    test_file: str | Path,
    case_slugs: Iterable[str],
    golden_filename: str,
    update_goldens: bool,
    limits: dict[str, dict[str, float]],
    timeout: int = 1800,
) -> dict[str, Any]:
    """Run selected XT3D method-choice cases and compare compact signatures."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )
    try:
        from tools.doc_gallery.xt3d_irregular_tri_diagnostics import (
            build_xt3d_method_choice_payload,
            rounded_xt3d_method_choice_payload,
        )

        payload = rounded_xt3d_method_choice_payload(
            build_xt3d_method_choice_payload(case_slugs=tuple(case_slugs), timeout=timeout)
        )
    except ModuleNotFoundError as exc:
        pytest.skip(f"XT3D comparison dependency is missing: {exc.name}")

    signature = build_xt3d_method_choice_signature(payload)
    assert_xt3d_method_choice_limits(signature, limits=limits)
    update_or_assert_goldens(
        actual={"intercomparison_expected": signature},
        golden_reference_file=resolve_tiered_golden_file(
            test_file=test_file,
            filename=golden_filename,
        ),
        update_goldens=update_goldens,
    )
    return signature
