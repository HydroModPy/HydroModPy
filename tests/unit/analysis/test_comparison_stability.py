"""Unit tests for post-run comparison stability checks."""

from __future__ import annotations

import json
from pathlib import Path

from hydromodpy.analysis.comparison.stability import (
    format_stability_report,
    validate_stability_targets,
)


def test_validate_stability_targets_accepts_materialized_outputs(
    tmp_path: Path,
) -> None:
    root = tmp_path / "outputs" / "demo_compare"
    _write_minimal_comparison_output(root)
    targets = tmp_path / "stability_targets.toml"
    targets.write_text(
        "\n".join(
            [
                "[[case]]",
                'id = "demo_compare"',
                'comparison_root = "outputs/demo_compare"',
                'allowed_audit_status = ["pass"]',
                'required_simulations = ["mf6_ref", "bouss_candidate"]',
                'required_figures = ["head_map_last__triptych.png"]',
                "",
                "[[case.metric]]",
                'simulation_id = "bouss_candidate"',
                'observable = "head_map_last"',
                "n_pairs_min = 3",
                "rmse_max = 0.05",
                "max_abs_error_max = 0.10",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = validate_stability_targets(targets)

    assert report.ok
    assert "demo_compare: PASS" in format_stability_report(report)


def test_validate_stability_targets_reports_metric_regression(tmp_path: Path) -> None:
    root = tmp_path / "outputs" / "demo_compare"
    _write_minimal_comparison_output(root)
    targets = tmp_path / "stability_targets.toml"
    targets.write_text(
        "\n".join(
            [
                "[[case]]",
                'id = "demo_compare"',
                'comparison_root = "outputs/demo_compare"',
                'allowed_audit_status = ["pass"]',
                "",
                "[[case.metric]]",
                'simulation_id = "bouss_candidate"',
                'observable = "head_map_last"',
                "rmse_max = 0.005",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = validate_stability_targets(targets)

    assert not report.ok
    assert "exceeds" in format_stability_report(report)


def test_validate_stability_targets_accepts_legacy_variant_outputs(
    tmp_path: Path,
) -> None:
    root = tmp_path / "outputs" / "legacy_compare"
    _write_minimal_comparison_output(root)
    (root / "comparison_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "comparison_manifest_v1",
                "variants": [
                    {"variant_id": "mf6_ref", "status": "completed"},
                    {"variant_id": "bouss_candidate", "status": "completed"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "comparison_metrics.json").write_text(
        json.dumps(
            {
                "schema_version": "comparison_metrics_v1",
                "summary": [
                    {
                        "variant_id": "bouss_candidate",
                        "observable": "head_map_last",
                        "n_pairs": 3,
                        "rmse": 0.02,
                        "max_abs_error": 0.06,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    targets = tmp_path / "stability_targets.toml"
    targets.write_text(
        "\n".join(
            [
                "[[case]]",
                'id = "legacy_compare"',
                'comparison_root = "outputs/legacy_compare"',
                'allowed_audit_status = ["pass"]',
                'required_simulations = ["mf6_ref", "bouss_candidate"]',
                "",
                "[[case.metric]]",
                'simulation_id = "bouss_candidate"',
                'observable = "head_map_last"',
                "n_pairs_min = 3",
                "rmse_max = 0.05",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = validate_stability_targets(targets)

    assert report.ok


def _write_minimal_comparison_output(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "comparison_report.md").write_text("# Demo\n", encoding="utf-8")
    figure_root = root / "comparison_figures"
    figure_root.mkdir()
    (figure_root / "head_map_last__triptych.png").write_bytes(b"png")
    (root / "comparison_audit.json").write_text(
        json.dumps(
            {
                "schema_version": "simulation_comparison_audit_v1",
                "status": "pass",
            }
        ),
        encoding="utf-8",
    )
    (root / "comparison_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "simulation_comparison_manifest_v1",
                "simulations": [
                    {"id": "mf6_ref", "status": "completed"},
                    {"id": "bouss_candidate", "status": "completed"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "comparison_metrics.json").write_text(
        json.dumps(
            {
                "schema_version": "simulation_comparison_metrics_v1",
                "summary": [
                    {
                        "simulation_id": "bouss_candidate",
                        "observable": "head_map_last",
                        "n_pairs": 3,
                        "rmse": 0.02,
                        "max_abs_error": 0.06,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
