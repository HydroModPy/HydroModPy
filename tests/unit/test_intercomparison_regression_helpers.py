from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.regression.intercomparison_helpers import (
    build_intercomparison_signature,
    metric_key,
    write_isolated_comparison_config,
)


def test_build_intercomparison_signature_is_compact_and_ordered(tmp_path: Path) -> None:
    metrics_path = tmp_path / "comparison_metrics.json"
    audit_path = tmp_path / "comparison_audit.json"
    metrics_path.write_text(
        json.dumps(
            {
                "schema_version": "simulation_comparison_metrics_v1",
                "comparison_id": "case_a",
                "reference_simulation": "mf6_ref",
                "summary": [
                    {
                        "simulation_id": "bouss_candidate",
                        "reference_simulation": "mf6_ref",
                        "observable": "head_point",
                        "unit": "m",
                        "n_pairs": 1,
                        "bias": 0.1,
                        "mae": 0.1,
                        "rmse": 0.1,
                        "max_abs_error": 0.1,
                        "mean_relative_error": 0.01,
                    }
                ],
                "differences": [{"large": "not retained"}],
            }
        ),
        encoding="utf-8",
    )
    audit_path.write_text(
        json.dumps(
            {
                "schema_version": "simulation_comparison_audit_v1",
                "status": "pass",
            }
        ),
        encoding="utf-8",
    )

    signature = build_intercomparison_signature(
        metrics_json=metrics_path,
        audit_json=audit_path,
    )

    key = metric_key(simulation_id="bouss_candidate", observable="head_point")
    assert signature["comparison_id"] == "case_a"
    assert signature["reference_simulation"] == "mf6_ref"
    assert signature["audit_status"] == "pass"
    assert list(signature["summary"]) == [key]
    assert signature["summary"][key]["max_abs_error"] == 0.1
    assert "differences" not in signature


def test_build_intercomparison_signature_requires_current_simulation_id_schema(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "comparison_metrics.json"
    audit_path = tmp_path / "comparison_audit.json"
    metrics_path.write_text(
        json.dumps(
            {
                "schema_version": "simulation_comparison_metrics_v1",
                "comparison_id": "case_a",
                "reference_simulation": "mf6_ref",
                "summary": [
                    {
                        "reference_simulation": "mf6_ref",
                        "observable": "head_point",
                        "unit": "m",
                        "n_pairs": 1,
                        "bias": 0.1,
                        "mae": 0.1,
                        "rmse": 0.1,
                        "max_abs_error": 0.1,
                        "mean_relative_error": 0.01,
                    }
                ],
                "differences": [{"large": "not retained"}],
            }
        ),
        encoding="utf-8",
    )
    audit_path.write_text(
        json.dumps(
            {
                "schema_version": "simulation_comparison_audit_v1",
                "status": "pass",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="simulation_id"):
        build_intercomparison_signature(
            metrics_json=metrics_path,
            audit_json=audit_path,
        )


def test_write_isolated_comparison_config_redirects_outputs_and_workspace(
    tmp_path: Path,
) -> None:
    source_config = tmp_path / "source.toml"
    source_config.write_text(
        "\n".join(
            [
                'workflow = "comparison"',
                "",
                "[comparison]",
                'base_simulation_config = "base.toml"',
                'output_root = "outputs/original"',
                "",
                "[comparison.execution]",
                'backend = "subprocess_hmp_run"',
                "",
                "[[comparison.simulation]]",
                'id = "mf6_ref"',
                'solver = "modflow6"',
                "",
                "[comparison.simulation.overlay.modflow6.runtime]",
                'mf6_ims_complexity = "SIMPLE"',
                "",
                "[[comparison.simulation]]",
                'id = "bouss_candidate"',
                'solver = "boussinesq"',
                "",
                "[comparison.simulation.overlay.flow]",
                'runtime_backend = "scipy_sparse"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    target_config = write_isolated_comparison_config(
        source_config=source_config,
        target_config=tmp_path / "target.toml",
        base_simulation_config=tmp_path / "base.toml",
        comparison_root=tmp_path / "comparison",
        workspace_root=tmp_path / "workspace",
        timeout_seconds=123.0,
    )

    text = target_config.read_text(encoding="utf-8")
    expected_base = (tmp_path / "base.toml").resolve().as_posix()
    expected_comparison = (tmp_path / "comparison").resolve().as_posix()
    expected_workspace = (tmp_path / "workspace").resolve().as_posix()
    assert f'base_simulation_config = "{expected_base}"' in text
    assert f'output_root = "{expected_comparison}"' in text
    assert text.count("[comparison.simulation.overlay.workspace]") == 2
    assert f'root = "{expected_workspace}"' in text
    assert "timeout_seconds = 123.0" in text
