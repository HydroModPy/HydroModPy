from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
from types import ModuleType


def test_testbed_web_report_includes_numerical_closure_metrics(tmp_path: Path) -> None:
    module = _load_report_module()
    output_root = tmp_path / "testbed"
    comparison_root = output_root / "comparisons" / "site_01_compare"
    (comparison_root / "web").mkdir(parents=True)
    (comparison_root / "web" / "index.html").write_text("comparison", encoding="utf-8")
    _write_json(
        output_root / "testbed_manifest.json",
        {
            "testbed_id": "closure_demo",
            "variant_count": 1,
            "successful_count": 1,
            "failed_count": 0,
            "cases": [
                {
                    "variant_id": "site_01",
                    "variant_label": "Site 01",
                    "axis": "natural",
                    "status": "ok",
                    "runner": "comparison",
                }
            ],
        },
    )
    _write_json(output_root / "testbed_plan.json", {"cases": []})
    _write_csv(
        output_root / "testbed_cases.csv",
        [
            {
                "variant_id": "site_01",
                "variant_label": "Site 01",
                "axis": "natural",
                "status": "ok",
                "runner": "comparison",
            }
        ],
    )
    _write_csv(output_root / "testbed_metrics.csv", [])
    _write_json(
        comparison_root / "comparison_manifest.json",
        {
            "comparison_id": "site_01_compare",
            "reference_simulation": "mf6_ref",
            "audit_status": "pass",
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
    _write_csv(
        comparison_root / "numerical_closure_summary.csv",
        [
            {
                "simulation_id": "mf6_ref",
                "solver": "modflow6",
                "n_periods": "2",
                "max_abs_closure_m3_s": "0.001",
                "max_abs_closure_mm_d": "0.0002",
                "relative_closure_error_p95": "0.0005",
                "diagnostic": "OK",
            },
            {
                "simulation_id": "bouss_candidate",
                "solver": "boussinesq",
                "n_periods": "2",
                "max_abs_closure_m3_s": "0.02",
                "max_abs_closure_mm_d": "0.004",
                "relative_closure_error_p95": "0.006",
                "diagnostic": "WARN",
            },
        ],
    )

    web_root = output_root / "web_synthesis"
    module.render_testbed_report(
        output_root=output_root,
        web_root=web_root,
        context={},
    )

    index_text = (web_root / "index.html").read_text(encoding="utf-8")
    case_text = (web_root / "cases" / "site_01.html").read_text(encoding="utf-8")
    assert "Precision de resolution" in index_text
    assert "MODFLOW max mm/j" in index_text
    assert "Boussinesq max mm/j" in index_text
    assert "WARN" in index_text
    assert "bouss_candidate" in case_text
    assert "Max residu mm/j" in case_text


def _load_report_module() -> ModuleType:
    repo_root = Path(__file__).resolve().parents[3]
    path = repo_root / "examples/projects/10_testbed_workflow/reporting/generate_testbed_web_report.py"
    spec = importlib.util.spec_from_file_location("generate_testbed_web_report", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
