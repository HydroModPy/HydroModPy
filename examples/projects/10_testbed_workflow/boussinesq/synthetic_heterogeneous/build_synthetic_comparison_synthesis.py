"""Build the synthetic MF6/Boussinesq campaign synthesis pages.

This script is a reporting helper only. It reads comparison outputs that were
already produced by ``hydromodpy run``, writes a small generic testbed-style
index contract, then delegates HTML rendering to the reusable testbed report
generator.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any


CASE_DEFINITIONS = [
    {
        "variant_id": "synthetic_homogeneous_control_mf6_vs_bouss",
        "variant_label": "Homogeneous control",
        "axis": "hydraulic_properties",
        "config": "base_synthetic_homogeneous_control.toml",
        "comparison_root": "synthetic_homogeneous_control_mf6_vs_bouss",
    },
    {
        "variant_id": "synthetic_patchy_long_mf6_vs_bouss",
        "variant_label": "Patchy K moderate contrast",
        "axis": "hydraulic_properties",
        "config": "base_synthetic_patchy_mf6_bouss_transient.toml",
        "comparison_root": "synthetic_patchy_long_mf6_vs_bouss",
    },
    {
        "variant_id": "synthetic_patchy_strong_k_mf6_vs_bouss",
        "variant_label": "Patchy K strong contrast",
        "axis": "hydraulic_properties",
        "config": "base_synthetic_patchy_strong_k.toml",
        "comparison_root": "synthetic_patchy_strong_k_mf6_vs_bouss",
    },
    {
        "variant_id": "synthetic_drainage_low_mf6_vs_bouss",
        "variant_label": "Low drainage conductance",
        "axis": "drainage_conductance",
        "config": "base_synthetic_drainage_low.toml",
        "comparison_root": "synthetic_drainage_low_mf6_vs_bouss",
    },
    {
        "variant_id": "synthetic_drainage_high_mf6_vs_bouss",
        "variant_label": "High drainage conductance",
        "axis": "drainage_conductance",
        "config": "base_synthetic_drainage_high.toml",
        "comparison_root": "synthetic_drainage_high_mf6_vs_bouss",
    },
    {
        "variant_id": "synthetic_recharge_pulse_48m_mf6_vs_bouss",
        "variant_label": "48-month recharge pulse",
        "axis": "recharge_chronicle",
        "config": "base_synthetic_recharge_pulse_48m.toml",
        "comparison_root": "synthetic_recharge_pulse_48m_mf6_vs_bouss",
    },
    {
        "variant_id": "synthetic_small_domain_mf6_vs_bouss",
        "variant_label": "Small domain",
        "axis": "domain_size",
        "config": "base_synthetic_small_domain.toml",
        "comparison_root": "synthetic_small_domain_mf6_vs_bouss",
    },
    {
        "variant_id": "synthetic_large_domain_mf6_vs_bouss",
        "variant_label": "Large domain",
        "axis": "domain_size",
        "config": "base_synthetic_large_domain.toml",
        "comparison_root": "synthetic_large_domain_mf6_vs_bouss",
    },
    {
        "variant_id": "synthetic_low_slope_mf6_vs_bouss",
        "variant_label": "Low topographic gradient",
        "axis": "topographic_gradient",
        "config": "base_synthetic_low_slope.toml",
        "comparison_root": "synthetic_low_slope_mf6_vs_bouss",
    },
    {
        "variant_id": "synthetic_high_slope_mf6_vs_bouss",
        "variant_label": "High topographic gradient",
        "axis": "topographic_gradient",
        "config": "base_synthetic_high_slope.toml",
        "comparison_root": "synthetic_high_slope_mf6_vs_bouss",
    },
]


def main() -> int:
    repo_root = Path(__file__).resolve().parents[5]
    source_dir = Path(__file__).resolve().parent
    output_root = (
        repo_root
        / "examples/projects/10_testbed_workflow/outputs/boussinesq_synthetic_heterogeneous"
    )
    campaign_root = output_root / "synthetic_comparison_campaign"
    comparisons_root = output_root / "comparisons"
    reporting_dir = repo_root / "examples/projects/10_testbed_workflow/reporting"

    case_rows, metric_rows = _build_rows(
        source_dir=source_dir,
        comparisons_root=comparisons_root,
    )
    _write_campaign_contract(
        campaign_root=campaign_root,
        source_dir=source_dir,
        case_rows=case_rows,
        metric_rows=metric_rows,
    )

    sys.path.insert(0, str(reporting_dir))
    from generate_testbed_web_report import main as render_report

    report_args: list[str] = [
        str(campaign_root),
        "--title",
        "Boussinesq synthetic comparison campaign",
    ]
    for case in CASE_DEFINITIONS:
        report_args.extend(
            [
                "--comparison-root",
                str((comparisons_root / str(case["comparison_root"])).resolve()),
            ]
        )
    return int(render_report(report_args))


def _build_rows(
    *,
    source_dir: Path,
    comparisons_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    case_rows: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    for item in CASE_DEFINITIONS:
        comparison_root = comparisons_root / str(item["comparison_root"])
        manifest_path = comparison_root / "comparison_manifest.json"
        manifest = _read_json(manifest_path)
        html_path = comparison_root / "web" / "index.html"
        status = "ok" if _comparison_completed(manifest=manifest, html_path=html_path) else "failed"
        case_row = {
            "variant_id": item["variant_id"],
            "variant_label": item["variant_label"],
            "axis": item["axis"],
            "enabled": "true",
            "status": status,
            "config_path": str((source_dir / str(item["config"])).resolve()),
            "runner": "comparison",
            "duration_seconds": manifest.get("wall_time_seconds", ""),
            "error": "" if status == "ok" else "comparison output incomplete",
            "name": item["variant_id"],
            "sim_id": "",
            "comparison_root": str(comparison_root.resolve()),
            "comparison_html": str(html_path.resolve()) if html_path.is_file() else "",
        }
        case_rows.append(case_row)
        metric_rows.append(
            {
                "variant_id": item["variant_id"],
                "variant_label": item["variant_label"],
                "axis": item["axis"],
                "status": status,
                "duration_s": manifest.get("wall_time_seconds", ""),
                "audit_status": manifest.get("audit_status", ""),
                "n_metric_rows": manifest.get("n_metric_rows", ""),
                "n_difference_rows": manifest.get("n_difference_rows", ""),
                "comparison_html": case_row["comparison_html"],
            }
        )
    return case_rows, metric_rows


def _comparison_completed(*, manifest: dict[str, Any], html_path: Path) -> bool:
    if not html_path.is_file():
        return False
    simulations = manifest.get("simulations")
    if not isinstance(simulations, list):
        return True
    completed_statuses = {"completed", "success", "ok"}
    return all(
        str(item.get("status", "")).lower() in completed_statuses
        for item in simulations
        if isinstance(item, dict)
    )


def _write_campaign_contract(
    *,
    campaign_root: Path,
    source_dir: Path,
    case_rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
) -> None:
    campaign_root.mkdir(parents=True, exist_ok=True)
    successful_count = sum(1 for row in case_rows if row["status"] == "ok")
    manifest = {
        "schema_version": "testbed_manifest_v1",
        "testbed_id": "boussinesq_synthetic_comparison_campaign",
        "subject": "flow",
        "purpose": "mf6_boussinesq_synthetic_method_comparison_campaign",
        "runner": "comparison",
        "output_root": str(campaign_root.resolve()),
        "execute": True,
        "variant_count": len(case_rows),
        "executed_count": len(case_rows),
        "successful_count": successful_count,
        "failed_count": len(case_rows) - successful_count,
        "config_path": str((source_dir / "run_synthetic_comparison_campaign.sh").resolve()),
        "base_config": str((source_dir / "base_synthetic_patchy_mf6_bouss_transient.toml").resolve()),
        "cases": case_rows,
    }
    _write_json(campaign_root / "testbed_manifest.json", manifest)
    _write_json(campaign_root / "testbed_plan.json", {"cases": case_rows})
    _write_csv(campaign_root / "testbed_cases.csv", case_rows)
    _write_csv(campaign_root / "testbed_metrics.csv", metric_rows)
    _write_markdown_report(campaign_root / "testbed_report.md", case_rows=case_rows)


def _write_markdown_report(path: Path, *, case_rows: list[dict[str, Any]]) -> None:
    successful_count = sum(1 for row in case_rows if row["status"] == "ok")
    lines = [
        "# Boussinesq synthetic comparison campaign",
        "",
        (
            f"Cases: {len(case_rows)}; successful: {successful_count}; "
            f"failed: {len(case_rows) - successful_count}."
        ),
        "",
        "| Case | Axis | Status | HTML |",
        "| --- | --- | --- | --- |",
    ]
    for row in case_rows:
        lines.append(
            "| {label} | {axis} | {status} | {html_path} |".format(
                label=row["variant_label"],
                axis=row["axis"],
                status=row["status"],
                html_path=row["comparison_html"] or "missing",
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
