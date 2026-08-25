"""Regional-lab profile runtime for the testbed campaign model."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from hydromodpy.analysis.testbed.child_artifacts import extract_child_artifacts
from hydromodpy.analysis.testbed.regional_lab_adapter import run_case_with_testbed_provider
from hydromodpy.analysis.testbed.regional_lab_catalog import load_site_catalog
from hydromodpy.analysis.testbed.regional_lab_config import RegionalLabConfig
from hydromodpy.analysis.testbed.regional_lab_planning import build_regional_lab_plan
from hydromodpy.analysis.testbed.regional_lab_reporting import (
    build_plan_payload,
    build_report_payload,
    load_previous_ok_case_ids,
    write_json_payload,
    write_summary_artifacts,
)
from hydromodpy.analysis.testbed.regional_lab_types import (
    RegionalLabExecution,
    RegionalLabPlannedCase,
)
from hydromodpy.core import progress


class RegionalLabProfileLauncher:
    """Expand one regional site catalog into a testbed-profile campaign."""

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
        write_json_payload(
            plan_path,
            build_plan_payload(
                cfg=cfg,
                selected_sites=selected_sites,
                planned_cases=planned_cases,
                skipped_cases=skipped_cases,
            ),
        )

        previous_ok_case_ids: set[str] = set()
        if cfg.resume_from_report and cfg.skip_completed_cases:
            previous_ok_case_ids = load_previous_ok_case_ids(report_path)

        executions: list[RegionalLabExecution] = []
        synthesis_paths = write_summary_artifacts(
            cfg=cfg,
            selected_sites=selected_sites,
            planned_cases=planned_cases,
            skipped_cases=skipped_cases,
            executions=executions,
        )
        write_json_payload(
            report_path,
            build_report_payload(
                cfg=cfg,
                selected_sites=selected_sites,
                planned_cases=planned_cases,
                skipped_cases=skipped_cases,
                executions=executions,
                synthesis_paths=synthesis_paths,
            ),
        )

        if cfg.execute:
            with progress.task("Running regional lab cases", total=len(planned_cases)) as bar:
                for case in planned_cases:
                    if case.case_id in previous_ok_case_ids:
                        executions.append(
                            RegionalLabExecution(
                                case=case,
                                status="skipped_existing_ok",
                                duration_seconds=0.0,
                                reused_from_report=True,
                                child_artifacts=_regional_case_child_artifacts(case),
                            )
                        )
                    else:
                        started_at = time.perf_counter()
                        with progress.suppressed():
                            status = _run_child_case(case=case)
                        executions.append(
                            RegionalLabExecution(
                                case=case,
                                status=status,
                                duration_seconds=round(float(time.perf_counter() - started_at), 6),
                                reused_from_report=False,
                                child_artifacts=_regional_case_child_artifacts(case),
                            )
                        )
                    synthesis_paths = write_summary_artifacts(
                        cfg=cfg,
                        selected_sites=selected_sites,
                        planned_cases=planned_cases,
                        skipped_cases=skipped_cases,
                        executions=executions,
                    )
                    write_json_payload(
                        report_path,
                        build_report_payload(
                            cfg=cfg,
                            selected_sites=selected_sites,
                            planned_cases=planned_cases,
                            skipped_cases=skipped_cases,
                            executions=executions,
                            synthesis_paths=synthesis_paths,
                        ),
                    )
                    bar.advance()
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


def _run_child_case(
    *,
    case: RegionalLabPlannedCase,
) -> str:
    """Run one regional-lab child through the shared testbed provider."""
    return run_case_with_testbed_provider(case)


def _regional_case_child_artifacts(case: RegionalLabPlannedCase) -> dict[str, Any]:
    """Extract shared child artifacts for one regional-lab planned case."""
    return extract_child_artifacts(runner=case.launcher, config_path=case.config_path)


__all__ = [
    "RegionalLabProfileLauncher",
]
