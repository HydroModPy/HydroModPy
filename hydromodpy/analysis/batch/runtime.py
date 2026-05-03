"""Top-level launcher orchestrating the regional-lab campaign."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from hydromodpy.analysis.batch.batch_catalog import load_site_catalog
from hydromodpy.analysis.batch.batch_execution import _extract_child_case_artifacts
from hydromodpy.analysis.batch.batch_planning import (
    build_regional_lab_plan,
    build_run_command,
)
from hydromodpy.analysis.batch.batch_reporting import (
    _build_plan_payload,
    _build_report_payload,
    _load_previous_ok_case_ids,
    _write_json,
    _write_summary_artifacts,
)
from hydromodpy.analysis.batch.batch_types import RegionalLabExecution
from hydromodpy.analysis.batch.config import RegionalLabConfig

REPO_ROOT = Path(__file__).resolve().parents[3]


class RegionalLabLauncher:
    """Expand one site catalog into a concrete regional-lab campaign."""

    def __init__(self, config_path: str | Path) -> None:
        self.cfg = RegionalLabConfig.from_file(config_path)

    def run(self) -> dict[str, Any]:
        """Build the plan, optionally execute it, and persist summary artifacts."""
        cfg = self.cfg
        cfg.output_root.mkdir(parents=True, exist_ok=True)
        sites = load_site_catalog(cfg.catalog)
        selected_sites, planned_cases, skipped_cases = build_regional_lab_plan(cfg, sites)

        plan_path = (cfg.output_root / "regional_lab_plan.json").resolve()
        report_path = (cfg.output_root / "regional_lab_report.json").resolve()
        _write_json(
            plan_path,
            _build_plan_payload(
                cfg=cfg,
                selected_sites=selected_sites,
                planned_cases=planned_cases,
                skipped_cases=skipped_cases,
            ),
        )

        previous_ok_case_ids: set[str] = set()
        if cfg.resume_from_report and cfg.skip_completed_cases:
            previous_ok_case_ids = _load_previous_ok_case_ids(report_path)

        executions: list[RegionalLabExecution] = []
        synthesis_paths = _write_summary_artifacts(
            cfg=cfg,
            selected_sites=selected_sites,
            planned_cases=planned_cases,
            skipped_cases=skipped_cases,
            executions=executions,
        )
        _write_json(
            report_path,
            _build_report_payload(
                cfg=cfg,
                selected_sites=selected_sites,
                planned_cases=planned_cases,
                skipped_cases=skipped_cases,
                executions=executions,
                synthesis_paths=synthesis_paths,
            ),
        )

        if cfg.execute:
            python_executable = cfg.python_executable or Path(sys.executable)
            for case in planned_cases:
                command = build_run_command(case, python_executable=python_executable)
                if case.case_id in previous_ok_case_ids:
                    executions.append(
                        RegionalLabExecution(
                            case=case,
                            command=tuple(command),
                            status="skipped_existing_ok",
                            returncode=0,
                            duration_seconds=0.0,
                            reused_from_report=True,
                            child_artifacts=_extract_child_case_artifacts(case),
                        )
                    )
                else:
                    started_at = time.perf_counter()
                    status, returncode = _run_child_subprocess(command, timeout=cfg.child_timeout_s)
                    executions.append(
                        RegionalLabExecution(
                            case=case,
                            command=tuple(command),
                            status=status,
                            returncode=returncode,
                            duration_seconds=round(float(time.perf_counter() - started_at), 6),
                            reused_from_report=False,
                            child_artifacts=_extract_child_case_artifacts(case),
                        )
                    )
                synthesis_paths = _write_summary_artifacts(
                    cfg=cfg,
                    selected_sites=selected_sites,
                    planned_cases=planned_cases,
                    skipped_cases=skipped_cases,
                    executions=executions,
                )
                _write_json(
                    report_path,
                    _build_report_payload(
                        cfg=cfg,
                        selected_sites=selected_sites,
                        planned_cases=planned_cases,
                        skipped_cases=skipped_cases,
                        executions=executions,
                        synthesis_paths=synthesis_paths,
                    ),
                )
                if executions[-1].status == "failed" and not cfg.continue_on_error:
                    break

        return {
            "lab_id": cfg.lab_id,
            "output_root": str(cfg.output_root),
            "selected_site_count": len(selected_sites),
            "planned_case_count": len(planned_cases),
            "skipped_case_count": len(skipped_cases),
            "executed_case_count": len(
                [item for item in executions if not item.reused_from_report]
            ),
            "reused_case_count": len([item for item in executions if item.reused_from_report]),
            "failed_case_count": len([item for item in executions if item.status == "failed"]),
            "plan_path": str(plan_path),
            "report_path": str(report_path),
            **synthesis_paths,
        }


def _run_child_subprocess(command: list[str], *, timeout: int | None) -> tuple[str, int | None]:
    """Run one child launcher and classify its outcome."""
    try:
        completed = subprocess.run(command, cwd=REPO_ROOT, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "failed", None
    return ("ok" if completed.returncode == 0 else "failed", int(completed.returncode))
