"""Shared helpers for solver intercomparison regression tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.regression.golden_utils import (
    assert_required_executables,
    load_json_payload,
    resolve_tiered_golden_file,
    resolve_tiered_results_dir,
    update_or_assert_goldens,
)

SUMMARY_METRIC_FIELDS = (
    "bias",
    "mae",
    "rmse",
    "max_abs_error",
    "mean_relative_error",
)


def metric_key(*, variant_id: str, observable: str) -> str:
    """Return the stable key used in intercomparison signatures."""
    return f"{variant_id}::{observable}"


def build_intercomparison_signature(
    *,
    metrics_json: Path,
    audit_json: Path,
) -> dict[str, Any]:
    """Build a compact, stable signature from comparison outputs."""
    metrics = load_json_payload(metrics_json)
    audit = load_json_payload(audit_json)
    summary_rows = sorted(
        metrics.get("summary", []),
        key=lambda row: (
            str(row.get("variant_id", "")),
            str(row.get("observable", "")),
        ),
    )

    summary: dict[str, dict[str, Any]] = {}
    for row in summary_rows:
        key = metric_key(
            variant_id=str(row.get("variant_id", "")),
            observable=str(row.get("observable", "")),
        )
        summary[key] = {
            "unit": str(row.get("unit", "")),
            "n_pairs": int(row.get("n_pairs", 0)),
        }
        for field in SUMMARY_METRIC_FIELDS:
            value = row.get(field)
            summary[key][field] = None if value is None else float(value)

    return {
        "signature_schema_version": "intercomparison_signature_v1",
        "metrics_schema_version": str(metrics.get("schema_version", "")),
        "audit_schema_version": str(audit.get("schema_version", "")),
        "comparison_id": str(metrics.get("comparison_id", "")),
        "reference_variant": str(metrics.get("reference_variant", "")),
        "audit_status": str(audit.get("status", "")),
        "summary": summary,
    }


def assert_intercomparison_limits(
    signature: dict[str, Any],
    *,
    limits: dict[str, dict[str, float]],
) -> None:
    """Assert explicit numerical acceptability limits before golden comparison."""
    summary = signature.get("summary", {})
    assert isinstance(summary, dict)
    for key, field_limits in limits.items():
        assert key in summary, f"Missing intercomparison metric row: {key}"
        row = summary[key]
        assert isinstance(row, dict)
        for field, upper_bound in field_limits.items():
            assert field in row, f"Missing metric field '{field}' in row {key}"
            value = row[field]
            assert value is not None, f"Metric field '{field}' in row {key} is null"
            assert abs(float(value)) <= float(upper_bound), (
                f"Metric {key}.{field}={value} exceeds limit {upper_bound}"
            )


def _toml_path(path: Path) -> str:
    return path.expanduser().resolve().as_posix()


def _append_workspace_overlay(lines: list[str], *, workspace_root: Path) -> None:
    lines.extend(
        [
            "",
            "[comparison.simulation.overlay.workspace]",
            f'project_root = "{_toml_path(workspace_root)}"',
            f'root = "{_toml_path(workspace_root)}"',
        ]
    )


def write_isolated_comparison_config(
    *,
    source_config: Path,
    target_config: Path,
    base_simulation_config: Path,
    comparison_root: Path,
    workspace_root: Path,
    timeout_seconds: float | None,
) -> Path:
    """Copy one comparison TOML while redirecting outputs and child workspaces."""
    source_lines = source_config.read_text(encoding="utf-8").splitlines()
    output_lines: list[str] = []
    in_simulation = False
    workspace_inserted = False
    timeout_inserted = False

    for line in source_lines:
        stripped = line.strip()
        if stripped == "[[comparison.simulation]]":
            if in_simulation and not workspace_inserted:
                _append_workspace_overlay(output_lines, workspace_root=workspace_root)
            in_simulation = True
            workspace_inserted = False
            output_lines.append(line)
            continue

        if (
            in_simulation
            and stripped.startswith("[comparison.simulation.overlay.")
            and not workspace_inserted
        ):
            _append_workspace_overlay(output_lines, workspace_root=workspace_root)
            workspace_inserted = True

        if stripped.startswith("base_simulation_config"):
            output_lines.append(f'base_simulation_config = "{_toml_path(base_simulation_config)}"')
            continue
        if stripped.startswith("output_root"):
            output_lines.append(f'output_root = "{_toml_path(comparison_root)}"')
            continue
        if stripped == "[comparison.execution]" and timeout_seconds is not None:
            output_lines.append(line)
            output_lines.append(f"timeout_seconds = {float(timeout_seconds)}")
            timeout_inserted = True
            continue
        if stripped.startswith("timeout_seconds") and timeout_inserted:
            continue
        output_lines.append(line)

    if in_simulation and not workspace_inserted:
        _append_workspace_overlay(output_lines, workspace_root=workspace_root)

    target_config.parent.mkdir(parents=True, exist_ok=True)
    target_config.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    return target_config


def run_intercomparison_regression(
    *,
    test_file: str | Path,
    source_config: Path,
    base_simulation_config: Path,
    golden_filename: str,
    run_name: str,
    update_goldens: bool,
    limits: dict[str, dict[str, float]],
    require_modflow: bool = False,
    require_modflow6: bool = False,
    require_modpath: bool = False,
    require_mt3dms: bool = False,
    timeout_seconds: float | None = 1800.0,
) -> dict[str, Any]:
    """Run one comparison workflow and compare its compact metric signature."""
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=require_modpath,
        require_mt3dms=require_mt3dms,
    )
    out_path = resolve_tiered_results_dir(test_file=test_file, run_name=run_name)
    comparison_root = out_path / "comparison"
    workspace_root = out_path / "workspace"
    config_path = write_isolated_comparison_config(
        source_config=source_config,
        target_config=out_path / "comparison_regression.toml",
        base_simulation_config=base_simulation_config,
        comparison_root=comparison_root,
        workspace_root=workspace_root,
        timeout_seconds=timeout_seconds,
    )

    try:
        from hydromodpy.analysis.comparison.experiment_launcher import (
            SimulationComparisonLauncher,
        )
    except ModuleNotFoundError as exc:
        pytest.skip(f"Comparison runtime dependency is missing: {exc.name}")

    manifest = SimulationComparisonLauncher(config_path).run()
    signature = build_intercomparison_signature(
        metrics_json=Path(str(manifest["comparison_metrics_json"])),
        audit_json=Path(str(manifest["comparison_audit_json"])),
    )
    assert signature["audit_status"] == "pass"
    assert_intercomparison_limits(signature, limits=limits)
    update_or_assert_goldens(
        actual={"intercomparison_expected": signature},
        golden_reference_file=resolve_tiered_golden_file(
            test_file=test_file,
            filename=golden_filename,
        ),
        update_goldens=update_goldens,
    )
    return signature
