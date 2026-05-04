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
    assert "demo_compare" in text
    assert "comparable_outflow_total_m3_s" in text
    assert "comparable_outflow_dashboard.png" in text
    assert "Persistance des sorties" in text
    assert "comparison_report.md" in text


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
