"""External simulation-comparison workflow launcher."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from hydromodpy.analysis.comparison.audit import (
    build_equivalence_audit,
    write_audit_files,
)
from hydromodpy.analysis.comparison.child_materialization import (
    GeneratedChildConfig,
    materialize_child_configs,
)
from hydromodpy.analysis.comparison.config import (
    MethodComparisonConfig,
    MethodComparisonSection,
    MethodComparisonVariant,
)
from hydromodpy.analysis.comparison.experiment_config import SimulationComparisonConfig
from hydromodpy.analysis.comparison.exports import (
    write_boussinesq_obstacle_diagnostics_export,
    write_budget_exports,
    write_execution_summary_csv,
    write_hydrographic_network_metrics_export,
    write_native_timeseries_exports,
    write_observable_chronicle_exports,
    write_simulated_active_network_distance_metrics_export,
    write_simulated_active_network_metrics_export,
    write_simulated_active_network_overlap_metrics_export,
    write_simulated_active_network_reference_figure_export,
)
from hydromodpy.analysis.comparison.metric_diff import (
    DETAIL_METRIC_FIELDS,
    SUMMARY_METRIC_FIELDS,
    build_comparison_metrics,
    write_metrics_csv,
    write_metrics_json,
)
from hydromodpy.analysis.comparison.reporting import build_comparison_report
from hydromodpy.analysis.comparison.run_backend import ChildRunResult, run_child_with_hmp
from hydromodpy.analysis.comparison.runtime_metadata import discover_result_store
from hydromodpy.analysis.comparison.runtime_observables import (
    extract_observable_rows,
    write_observables_csv,
)
from hydromodpy.analysis.comparison.visuals import generate_comparison_figures
from hydromodpy.core.toml_io.loader import load_toml_with_base_config


class SimulationComparisonLauncher:
    """Run generated child simulations and compare their stored results."""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).expanduser().resolve()
        raw_toml = load_toml_with_base_config(self.config_path)
        self.cfg = SimulationComparisonConfig.from_toml(
            raw_toml,
            config_path=self.config_path,
        )

    def run(self) -> dict[str, Any]:
        """Execute the external comparison experiment."""
        comparison = self.cfg.comparison
        comparison_root = self.cfg.comparison_root
        comparison_root.mkdir(parents=True, exist_ok=True)
        started_at = time.monotonic()

        children = materialize_child_configs(self.cfg)
        variant_summaries = self._run_children(children)

        method_cfg = self._build_method_comparison_cfg(children)
        all_rows = self._extract_observables(method_cfg, variant_summaries)
        observables_csv = comparison_root / "observables.csv"
        write_observables_csv(observables_csv, all_rows)

        reference_variant = comparison.reference_simulation or self._first_completed_id(
            variant_summaries
        )
        detail_metrics, summary_metrics = build_comparison_metrics(
            all_rows,
            reference_variant=reference_variant,
        )
        metrics_csv = comparison_root / "comparison_metrics.csv"
        differences_csv = comparison_root / "comparison_differences.csv"
        metrics_json = comparison_root / "comparison_metrics.json"
        write_metrics_csv(metrics_csv, summary_metrics, fieldnames=SUMMARY_METRIC_FIELDS)
        write_metrics_csv(differences_csv, detail_metrics, fieldnames=DETAIL_METRIC_FIELDS)
        write_metrics_json(
            metrics_json,
            {
                "schema_version": "simulation_comparison_metrics_v1",
                "comparison_id": comparison.comparison_id,
                "reference_variant": reference_variant,
                "summary": summary_metrics,
                "differences": detail_metrics,
            },
        )

        audit = build_equivalence_audit(
            variant_summaries=variant_summaries,
            reference_variant=reference_variant,
            mode=comparison.audit.mode,
            on_mismatch=comparison.audit.on_mismatch,
            observable_rows=all_rows,
        )
        audit_json, audit_md = write_audit_files(
            comparison_root=comparison_root,
            audit=audit,
        )

        data_artifacts: list[dict[str, Any]] = [
            {"kind": "comparison_audit_json", "path": str(audit_json)},
            {"kind": "comparison_audit_md", "path": str(audit_md)},
        ]
        observable_artifacts, observable_long_rows, _observable_wide_rows, observable_delta_rows = (
            write_observable_chronicle_exports(
                comparison_root=comparison_root,
                rows=all_rows,
                detail_metrics=detail_metrics,
                observables=[
                    observable.model_dump(mode="json") for observable in comparison.observable
                ],
            )
        )
        data_artifacts.extend(observable_artifacts)
        native_artifacts, native_long_rows, _native_wide_rows, native_delta_rows = (
            write_native_timeseries_exports(
                comparison_id=str(comparison.comparison_id),
                comparison_root=comparison_root,
                variant_summaries=variant_summaries,
                reference_variant=reference_variant,
            )
        )
        data_artifacts.extend(native_artifacts)
        hydrographic_artifacts, _hydrographic_rows = write_hydrographic_network_metrics_export(
            comparison_id=str(comparison.comparison_id),
            comparison_root=comparison_root,
            variant_summaries=variant_summaries,
        )
        data_artifacts.extend(hydrographic_artifacts)
        simulated_active_artifacts, _simulated_active_rows = (
            write_simulated_active_network_metrics_export(
                comparison_id=str(comparison.comparison_id),
                comparison_root=comparison_root,
                variant_summaries=variant_summaries,
            )
        )
        data_artifacts.extend(simulated_active_artifacts)
        simulated_active_overlap_artifacts, _simulated_active_overlap_rows = (
            write_simulated_active_network_overlap_metrics_export(
                comparison_id=str(comparison.comparison_id),
                comparison_root=comparison_root,
                variant_summaries=variant_summaries,
            )
        )
        data_artifacts.extend(simulated_active_overlap_artifacts)
        simulated_active_distance_artifacts, _simulated_active_distance_rows = (
            write_simulated_active_network_distance_metrics_export(
                comparison_id=str(comparison.comparison_id),
                comparison_root=comparison_root,
                variant_summaries=variant_summaries,
            )
        )
        data_artifacts.extend(simulated_active_distance_artifacts)
        budget_artifacts, budget_rows = write_budget_exports(
            comparison_root=comparison_root,
            variant_summaries=variant_summaries,
        )
        data_artifacts.extend(budget_artifacts)
        obstacle_artifacts, _obstacle_rows = write_boussinesq_obstacle_diagnostics_export(
            comparison_root=comparison_root,
            variant_summaries=variant_summaries,
        )
        data_artifacts.extend(obstacle_artifacts)
        execution_artifacts, execution_rows = write_execution_summary_csv(
            comparison_root=comparison_root,
            variant_summaries=variant_summaries,
            reference_variant=reference_variant,
        )
        data_artifacts.extend(execution_artifacts)

        figure_artifacts = generate_comparison_figures(
            cfg=method_cfg,
            variant_summaries=variant_summaries,
            rows=all_rows,
            detail_metrics=detail_metrics,
            reference_variant=reference_variant,
            comparison_root=comparison_root,
            native_timeseries_rows=native_long_rows,
            native_timeseries_delta_rows=native_delta_rows,
            budget_rows=budget_rows,
            execution_rows=execution_rows,
        )
        simulated_active_figure_artifacts, _simulated_active_figure_rows = (
            write_simulated_active_network_reference_figure_export(
                comparison_root=comparison_root,
                variant_summaries=variant_summaries,
            )
        )
        figure_artifacts.extend(simulated_active_figure_artifacts)

        report_path = comparison_root / "comparison_report.md"
        report_text = build_comparison_report(
            comparison_id=str(comparison.comparison_id),
            reference_variant=reference_variant,
            variant_summaries=variant_summaries,
            observables=[
                observable.model_dump(mode="json") for observable in comparison.observable
            ],
            rows=all_rows,
            summary_metrics=summary_metrics,
            figure_artifacts=figure_artifacts,
            data_artifacts=data_artifacts,
        )
        report_path.write_text(self._prepend_audit_summary(report_text, audit), encoding="utf-8")

        generated_config_paths = [str(child.config_path) for child in children]
        generated_configs_kept = bool(comparison.execution.keep_generated_configs)
        cleanup_errors: list[str] = []
        if not generated_configs_kept:
            cleanup_errors = self._cleanup_generated_configs(children)

        manifest = {
            "schema_version": "simulation_comparison_manifest_v1",
            "comparison_id": comparison.comparison_id,
            "config_path": str(self.config_path),
            "base_simulation_config": str(self.cfg.base_simulation_config_path),
            "comparison_root": str(comparison_root),
            "reference_variant": reference_variant,
            "audit_status": audit.get("status"),
            "observables_csv": str(observables_csv),
            "comparison_metrics_csv": str(metrics_csv),
            "comparison_differences_csv": str(differences_csv),
            "comparison_metrics_json": str(metrics_json),
            "comparison_audit_json": str(audit_json),
            "comparison_audit_md": str(audit_md),
            "comparison_report_md": str(report_path),
            "comparison_figures_dir": str(comparison_root / "comparison_figures"),
            "comparison_figures": figure_artifacts,
            "comparison_data_artifacts": data_artifacts,
            "n_observable_rows": len(all_rows),
            "n_metric_rows": len(summary_metrics),
            "n_difference_rows": len(detail_metrics),
            "wall_time_seconds": round(time.monotonic() - started_at, 2),
            "generated_configs_kept": generated_configs_kept,
            "generated_config_paths": generated_config_paths,
            "generated_config_cleanup_errors": cleanup_errors,
            "variants": variant_summaries,
            "observables": [
                observable.model_dump(mode="json") for observable in comparison.observable
            ],
        }
        manifest_path = comparison_root / "comparison_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        manifest["manifest_path"] = str(manifest_path)

        if audit.get("status") == "fail" and comparison.audit.on_mismatch == "fail":
            raise RuntimeError(
                f"Comparison audit failed. See {audit_json} for equivalence diagnostics."
            )
        return manifest

    def _run_children(
        self,
        children: list[GeneratedChildConfig],
    ) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        execution = self.cfg.comparison.execution
        for child in children:
            if not execution.run_simulations:
                summaries.append(self._reuse_child_summary(child))
                continue
            try:
                result = run_child_with_hmp(
                    child.config_path,
                    python_executable=execution.python_executable,
                    timeout_seconds=execution.timeout_seconds,
                )
                summary = self._summary_from_run_result(child, result)
            except Exception as exc:
                summary = self._failed_child_summary(child, exc)
            summaries.append(summary)
            if summary["status"] == "failed" and not self.cfg.comparison.continue_on_error:
                raise RuntimeError(
                    f"Comparison child '{child.simulation_id}' failed: "
                    f"{summary.get('error_message', '')}"
                )
        return summaries

    def _summary_from_run_result(
        self,
        child: GeneratedChildConfig,
        result: ChildRunResult,
    ) -> dict[str, Any]:
        sim_id = result.sim_id
        if result.succeeded and sim_id is None:
            store, discovered = discover_result_store(child.config_path)
            try:
                sim_id = discovered
            finally:
                if store is not None:
                    try:
                        store.close()
                    except Exception:
                        pass
        status = "completed" if result.succeeded else "failed"
        summary = self._base_child_summary(child, status=status)
        summary.update(
            {
                "sim_id": sim_id,
                "wall_time_seconds": round(result.wall_time_seconds, 2),
                "returncode": result.returncode,
                "stdout_tail": result.stdout[-4000:],
                "stderr_tail": result.stderr[-4000:],
            }
        )
        if not result.succeeded:
            summary["error_type"] = "ChildProcessError"
            summary["error_message"] = f"hmp run exited with code {result.returncode}"
        return summary

    def _reuse_child_summary(self, child: GeneratedChildConfig) -> dict[str, Any]:
        store, sim_id = discover_result_store(child.config_path)
        try:
            summary = self._base_child_summary(child, status="reused")
            summary["sim_id"] = sim_id
            return summary
        finally:
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass

    def _failed_child_summary(
        self,
        child: GeneratedChildConfig,
        exc: Exception,
    ) -> dict[str, Any]:
        summary = self._base_child_summary(child, status="failed")
        summary["error_type"] = type(exc).__name__
        summary["error_message"] = str(exc)
        return summary

    def _base_child_summary(
        self,
        child: GeneratedChildConfig,
        *,
        status: str,
    ) -> dict[str, Any]:
        return {
            "id": child.simulation_id,
            "label": child.label,
            "status": status,
            "enabled": True,
            "solver": child.solver,
            "mesh_label": child.mesh_label,
            "mesh_mode": child.mesh_mode,
            "config_path": str(child.config_path),
            "run_folder": str(child.config_path.parent),
            "run_name": child.run_name,
        }

    def _build_method_comparison_cfg(
        self,
        children: list[GeneratedChildConfig],
    ) -> MethodComparisonConfig:
        variants = [
            MethodComparisonVariant(
                id=child.simulation_id,
                label=child.label,
                solver=child.solver,
                mesh_label=child.mesh_label,
                mesh_mode=child.mesh_mode,  # type: ignore[arg-type]
                simulation_config=str(child.config_path),
                run_folder=str(child.config_path.parent),
            )
            for child in children
        ]
        section = MethodComparisonSection(
            comparison_id=self.cfg.comparison.comparison_id,
            base_simulation_config=str(self.cfg.base_simulation_config_path),
            output_root=str(self.cfg.comparison_root),
            run_variants=False,
            continue_on_error=self.cfg.comparison.continue_on_error,
            reference_variant=self.cfg.comparison.reference_simulation,
            fine_raster=self.cfg.comparison.fine_raster,
            variant=variants,
            observable=self.cfg.comparison.observable,
        )
        return MethodComparisonConfig(
            config_path=self.cfg.config_path,
            base_dir=self.cfg.base_dir,
            comparison_root=self.cfg.comparison_root,
            base_simulation_config_path=self.cfg.base_simulation_config_path,
            anchors_path=None,
            anchors={},
            method_comparison=section,
        )

    def _extract_observables(
        self,
        method_cfg: MethodComparisonConfig,
        variant_summaries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        variants = {variant.id: variant for variant in method_cfg.method_comparison.variant}
        for summary in variant_summaries:
            if summary.get("status") not in {"completed", "reused"}:
                continue
            variant = variants.get(str(summary.get("id", "")))
            if variant is None:
                continue
            store = None
            sim_id = None
            try:
                config_path = Path(str(summary["config_path"]))
                preferred_sim_id = summary.get("sim_id")
                store, sim_id = discover_result_store(
                    config_path,
                    preferred_sim_id=(
                        None if preferred_sim_id in (None, "") else str(preferred_sim_id)
                    ),
                )
                variant_rows = extract_observable_rows(
                    comparison_id=str(self.cfg.comparison.comparison_id),
                    variant=variant,
                    run_folder=Path(str(summary["run_folder"])),
                    observables=tuple(method_cfg.method_comparison.observable),
                    config_path=config_path,
                    store=store,
                    sim_id=sim_id,
                )
                rows.extend(variant_rows)
                summary["n_observable_rows"] = len(variant_rows)
            finally:
                if store is not None:
                    try:
                        store.close()
                    except Exception:
                        pass
        return rows

    @staticmethod
    def _first_completed_id(variant_summaries: list[dict[str, Any]]) -> str | None:
        for summary in variant_summaries:
            if summary.get("status") in {"completed", "reused"}:
                return str(summary.get("id", ""))
        return None

    @staticmethod
    def _prepend_audit_summary(report_text: str, audit: dict[str, Any]) -> str:
        lines = [
            f"# Simulation Comparison Report: {audit.get('reference_variant', '')}",
            "",
            f"- Audit status: `{audit.get('status', '')}`",
            f"- Audit issues: {len(audit.get('issues', []))}",
            "",
        ]
        return "\n".join(lines) + report_text

    @staticmethod
    def _cleanup_generated_configs(children: list[GeneratedChildConfig]) -> list[str]:
        """Remove generated child TOMLs when the comparison config requests it."""
        errors: list[str] = []
        generated_dirs = {child.config_path.parent for child in children}
        for child in children:
            path = child.config_path
            try:
                path.unlink(missing_ok=True)
            except Exception as exc:
                errors.append(f"could not remove {path}: {exc}")
        for generated_dir in sorted(generated_dirs):
            try:
                generated_dir.rmdir()
            except OSError:
                # Keep non-empty directories: users may have added files there.
                pass
            except Exception as exc:
                errors.append(f"could not remove {generated_dir}: {exc}")
        return errors


__all__ = ("SimulationComparisonLauncher",)
