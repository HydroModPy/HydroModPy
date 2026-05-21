"""Runtime facade for method testbeds: orchestrates pipeline + io."""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from hydromodpy.analysis.testbed.catalog_variants import expand_catalog_variants
from hydromodpy.analysis.testbed.config import (
    TestbedConfig,
    TestbedVariantConfig,
)
from hydromodpy.analysis.testbed.contracts import run_testbed_child_workflow
from hydromodpy.analysis.testbed.io import (
    _absolutize_relative_path_values,
    _write_csv_rows,
    _write_json,
    _write_toml_payload,
)
from hydromodpy.analysis.testbed.pipeline import (
    DEFAULT_RUNNER_METRICS,
    RUNNER_WORKFLOWS,
    TestbedExecution,
    TestbedPlannedCase,
    _build_report,
    _catalog_manifest_payload,
    _catalog_variant_manifest_payload,
    _configured_metric_row,
    _ensure_mesh_process_payload,
    _extract_simulation_catalog_summary,
    _metric_row_for_execution,
    _slugify,
)
from hydromodpy.core.toml_io import load_toml_with_base_config, merge_toml_payloads

__all__ = (
    "DEFAULT_RUNNER_METRICS",
    "RUNNER_WORKFLOWS",
    "TestbedExecution",
    "TestbedLauncher",
    "TestbedPlannedCase",
)


class TestbedLauncher:
    """Expand variants, run child workflows, and collect testbed evidence."""

    def __init__(self, config_path: str | Path) -> None:
        self.cfg = TestbedConfig.from_file(config_path)

    @property
    def generated_configs_dir(self) -> Path:
        return self.cfg.output_root / "_generated_configs"

    def _base_config_path(self) -> Path:
        return self.cfg.base_config_path or self.cfg.config_path

    def _child_workflow(self) -> str:
        return RUNNER_WORKFLOWS[self.cfg.runner.type]

    def _base_child_payload(self) -> dict[str, Any]:
        base_config_path = self._base_config_path()
        payload = load_toml_with_base_config(base_config_path)
        payload = _absolutize_relative_path_values(
            payload,
            source_dir=base_config_path.parent,
        )
        if not isinstance(payload, dict):
            raise ValueError("testbed base config must load to a TOML mapping")
        payload.pop("testbed", None)
        payload["workflow"] = self._child_workflow()
        if self.cfg.runner.type == "simulation" and self.cfg.subject == "mesh":
            _ensure_mesh_process_payload(payload)
        return payload

    def _materialize_child_config(self, variant: TestbedVariantConfig) -> Path:
        overlay = _absolutize_relative_path_values(
            variant.overlay,
            source_dir=self.cfg.base_dir,
        )
        payload = merge_toml_payloads(self._base_child_payload(), overlay)
        payload["workflow"] = self._child_workflow()
        if self.cfg.runner.type == "simulation" and self.cfg.subject == "mesh":
            _ensure_mesh_process_payload(payload)
        path = self.generated_configs_dir / f"{_slugify(variant.id)}.toml"
        _write_toml_payload(path, payload)
        return path

    def _expanded_variants(self) -> tuple[TestbedVariantConfig, ...]:
        variants = (
            *self.cfg.variants,
            *expand_catalog_variants(
                catalog=self.cfg.catalog,
                rules=self.cfg.catalog_variants,
            ),
        )
        if not variants:
            raise ValueError("testbed did not expand any variant")
        seen: set[str] = set()
        for variant in variants:
            normalized = variant.id.lower()
            if normalized in seen:
                raise ValueError(f"Duplicate testbed.variant id '{variant.id}'")
            seen.add(normalized)
        return variants

    def build_plan(self) -> list[TestbedPlannedCase]:
        """Materialize child configs and return planned cases."""
        cases: list[TestbedPlannedCase] = []
        for variant in self._expanded_variants():
            if not variant.enabled:
                cases.append(
                    TestbedPlannedCase(variant=variant, config_path=None, status="disabled")
                )
                continue
            cases.append(
                TestbedPlannedCase(
                    variant=variant,
                    config_path=self._materialize_child_config(variant),
                    status="planned",
                )
            )
        return cases

    def _run_case(self, case: TestbedPlannedCase) -> dict[str, Any]:
        if case.config_path is None:
            return {}
        return dict(
            run_testbed_child_workflow(
                runner_type=self.cfg.runner.type,
                config_path=case.config_path,
                no_display=self.cfg.runner.no_display,
            )
        )

    def _summary_paths(self) -> dict[str, str]:
        return {
            "plan_json": str((self.cfg.output_root / "testbed_plan.json").resolve()),
            "manifest_json": str((self.cfg.output_root / "testbed_manifest.json").resolve()),
            "cases_csv": str((self.cfg.output_root / "testbed_cases.csv").resolve()),
            "metrics_csv": str((self.cfg.output_root / "testbed_metrics.csv").resolve()),
            "report_markdown": str((self.cfg.output_root / "testbed_report.md").resolve()),
            "generated_configs_dir": str(self.generated_configs_dir.resolve()),
        }

    def _persist_outputs(
        self,
        *,
        cases: Sequence[TestbedPlannedCase],
        executions: Sequence[TestbedExecution],
    ) -> dict[str, str]:
        self.cfg.output_root.mkdir(parents=True, exist_ok=True)
        paths = self._summary_paths()
        _write_json(
            Path(paths["plan_json"]),
            {
                "schema_version": "testbed_plan_v1",
                "testbed_id": self.cfg.id,
                "profile": self.cfg.profile,
                "config_path": str(self.cfg.config_path),
                "subject": self.cfg.subject,
                "purpose": self.cfg.purpose,
                "runner": self.cfg.runner.type,
                "base_config": str(self._base_config_path()),
                "catalog": _catalog_manifest_payload(self.cfg),
                "variant_from_catalog": _catalog_variant_manifest_payload(self.cfg),
                "cases": [case.to_mapping() for case in cases],
            },
        )
        case_rows: list[dict[str, Any]] = []
        execution_by_variant = {item.case.variant.id: item for item in executions}
        for case in cases:
            execution = execution_by_variant.get(case.variant.id)
            if execution is None:
                row = case.to_mapping()
                row["runner"] = self.cfg.runner.type
                case_rows.append(row)
            else:
                case_rows.append(execution.to_case_row(runner_type=self.cfg.runner.type))
        _write_csv_rows(Path(paths["cases_csv"]), case_rows)

        metric_rows = [
            _metric_row_for_execution(
                execution=execution,
                metrics=self.cfg.metrics,
                runner_type=self.cfg.runner.type,
            )
            for execution in executions
        ]
        _write_csv_rows(Path(paths["metrics_csv"]), metric_rows)
        _write_json(
            Path(paths["manifest_json"]),
            {
                "schema_version": "testbed_manifest_v1",
                "testbed_id": self.cfg.id,
                "profile": self.cfg.profile,
                "subject": self.cfg.subject,
                "purpose": self.cfg.purpose,
                "runner": self.cfg.runner.type,
                "config_path": str(self.cfg.config_path),
                "output_root": str(self.cfg.output_root),
                "execute": bool(self.cfg.execute),
                "base_config": str(self._base_config_path()),
                "site_catalog_path": (
                    None if self.cfg.catalog is None else str(self.cfg.catalog.path)
                ),
                "catalog": _catalog_manifest_payload(self.cfg),
                "variant_from_catalog": _catalog_variant_manifest_payload(self.cfg),
                "variant_count": len(cases),
                "executed_count": len(executions),
                "successful_count": len([item for item in executions if item.status == "ok"]),
                "failed_count": len([item for item in executions if item.status == "failed"]),
                "cases": case_rows,
                "metrics": metric_rows,
                "paths": paths,
            },
        )
        Path(paths["report_markdown"]).write_text(
            _build_report(cfg=self.cfg, cases=cases, executions=executions),
            encoding="utf-8",
        )
        return paths

    def run(self) -> dict[str, Any]:
        """Execute the testbed and return a compact summary."""
        cases = self.build_plan()
        executions: list[TestbedExecution] = []
        paths = self._persist_outputs(cases=cases, executions=executions)

        if self.cfg.execute:
            for case in cases:
                if case.status == "disabled":
                    continue
                started_at = time.perf_counter()
                try:
                    child_summary = self._run_case(case)
                    if self.cfg.runner.type == "simulation":
                        child_summary = {
                            **child_summary,
                            **_extract_simulation_catalog_summary(
                                config_path=case.config_path,
                                child_summary=child_summary,
                            ),
                        }
                    duration = round(float(time.perf_counter() - started_at), 6)
                    from hydromodpy.analysis.testbed.io import _jsonable

                    execution = TestbedExecution(
                        case=case,
                        status="ok",
                        duration_seconds=duration,
                        summary=_jsonable(child_summary),
                    )
                    if self.cfg.metrics:
                        _configured_metric_row(metrics=self.cfg.metrics, summary=execution.summary)
                    executions.append(execution)
                except Exception as exc:
                    duration = round(float(time.perf_counter() - started_at), 6)
                    executions.append(
                        TestbedExecution(
                            case=case,
                            status="failed",
                            duration_seconds=duration,
                            summary={},
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )
                    paths = self._persist_outputs(cases=cases, executions=executions)
                    if not self.cfg.continue_on_error:
                        raise
                else:
                    paths = self._persist_outputs(cases=cases, executions=executions)

        successful_count = len([item for item in executions if item.status == "ok"])
        failed_count = len([item for item in executions if item.status == "failed"])
        return {
            "testbed_id": self.cfg.id,
            "profile": self.cfg.profile,
            "subject": self.cfg.subject,
            "purpose": self.cfg.purpose,
            "runner": self.cfg.runner.type,
            "output_root": str(self.cfg.output_root),
            "variant_count": len(cases),
            "executed_count": len(executions),
            "successful_count": successful_count,
            "failed_count": failed_count,
            **paths,
        }
