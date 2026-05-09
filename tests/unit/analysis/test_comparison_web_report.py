"""Unit tests for static comparison HTML report generation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from hydromodpy.analysis.comparison.web_report import write_comparison_web_report


def test_write_comparison_web_report_links_key_outputs(tmp_path: Path) -> None:
    root = tmp_path / "comparison"
    figure_root = root / "comparison_figures"
    figure_root.mkdir(parents=True)
    (figure_root / "case_configuration.png").write_bytes(b"png")
    (figure_root / "comparable_outflow_dashboard.png").write_bytes(b"png")
    (root / "comparison_report.md").write_text("# report\n", encoding="utf-8")
    (root / "comparison_audit.json").write_text(
        json.dumps({"status": "warn", "issues": [{"message": "demo issue"}]}),
        encoding="utf-8",
    )
    _write_csv(
        root / "comparison_metrics.csv",
        [
            {
                "simulation_id": "candidate",
                "observable": "head",
                "n_pairs": "2",
                "rmse": "0.1",
            }
        ],
    )
    _write_csv(
        root / "budget_timeseries_wide.csv",
        [
            {
                "component": "comparable_outflow_total_m3_s",
                "period_index": "0",
                "time_label": "1.0 d",
                "value__mf6_ref": "1.0",
                "value__bouss_candidate": "1.1",
            }
        ],
    )

    path = write_comparison_web_report(
        comparison_root=root,
        manifest={
            "comparison_id": "demo_compare",
            "audit_status": "warn",
            "reference_simulation": "mf6_ref",
            "simulations": [
                {"id": "mf6_ref", "solver": "modflow6", "status": "completed"},
                {
                    "id": "bouss_candidate",
                    "solver": "boussinesq",
                    "status": "completed",
                },
            ],
        },
    )

    text = path.read_text(encoding="utf-8")
    assert "demo compare" in text
    assert "Contexte du cas" in text
    assert "Comparaisons de resultats" in text
    assert "Flux agrege et chroniques" in text
    assert "comparable_outflow_dashboard.png" in text
    assert "comparison_report.md" in text


def test_synthetic_web_report_splits_hydraulic_and_numerical_settings(
    tmp_path: Path,
) -> None:
    root = tmp_path / "comparison"
    root.mkdir()
    base_config = root / "base.toml"
    base_config.write_text(
        """
[flow]
flow_regime = "transient"
runtime_backend = "petsc"
surface_interaction_model = "ts_vi_obstacle"
active_bc = ["drainage"]
ts_vi_type = "beuler"
ts_vi_snes_type = "vinewtonrsls"
ts_vi_steps_per_period = 4
runtime_tol_residual_inf = 1.0e-6

[flow.ic]
type = "steady_state"

[flow.sinks_sources.recharge]
first_clim = "first"
negative_to_evt = true

[flow.bc.cauchy.drainage]
value = "0.2 m2/s"
""",
        encoding="utf-8",
    )

    path = write_comparison_web_report(
        comparison_root=root,
        manifest={
            "comparison_id": "synthetic_patchy_unit",
            "base_simulation_config": "base.toml",
            "reference_simulation": "mf6_ref",
            "simulations": [],
        },
    )

    text = path.read_text(encoding="utf-8")
    assert "Configuration hydraulique commune" in text
    assert "Parametrage numerique" in text
    assert "first_clim=first" in text
    assert "negative_to_evt=true" in text
    assert "drainage de surface actif sur le toit, conductance 0.2 m2/s" in text


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
