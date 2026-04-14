"""Launcher orchestrating solver/mesh method comparisons."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config.toml_loader import load_toml_with_base_config

from hydromodpy.analysis.comparison.config import MethodComparisonConfig
from hydromodpy.analysis.comparison.exports import (
    write_budget_exports,
    write_execution_summary_csv,
    write_native_timeseries_exports,
    write_observable_chronicle_exports,
)
from hydromodpy.analysis.comparison.metrics import (
    DETAIL_METRIC_FIELDS,
    SUMMARY_METRIC_FIELDS,
    build_comparison_metrics,
    write_metrics_csv,
    write_metrics_json,
)
from hydromodpy.analysis.comparison.reporting import build_comparison_report
from hydromodpy.analysis.comparison.runtime import (
    compact_run_metrics,
    discover_result_store,
    extract_observable_rows,
    materialize_variant_config,
    read_json_file,
    read_variant_run_metadata,
    write_observables_csv,
)
from hydromodpy.analysis.comparison.visuals import generate_comparison_figures


class MethodComparisonLauncher:
    """Run or reuse method variants and compare configured observables."""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).expanduser().resolve()
        raw_toml = load_toml_with_base_config(self.config_path)
        self.cfg = MethodComparisonConfig.from_toml(
            raw_toml,
            config_path=self.config_path,
        )

    def run(self) -> dict[str, Any]:
        """Execute the comparison session and persist summary artefacts."""
        section = self.cfg.method_comparison
        comparison_root = self.cfg.comparison_root
        comparison_root.mkdir(parents=True, exist_ok=True)

        started_at = time.monotonic()
        all_rows: list[dict[str, Any]] = []
        variant_summaries: list[dict[str, Any]] = []

        for variant in section.variant:
            if not variant.enabled:
                variant_summaries.append(
                    {
                        "id": variant.id,
                        "status": "skipped",
                        "enabled": False,
                    }
                )
                continue

            summary = self._run_or_reuse_variant(variant)
            variant_summaries.append(summary)

            status = str(summary.get("status", ""))
            if status not in {"completed", "reused"}:
                if section.continue_on_error:
                    continue
                raise RuntimeError(
                    f"Method comparison variant '{variant.id}' failed: "
                    f"{summary.get('error_message', status)}"
                )

            run_folder = Path(str(summary["run_folder"]))
            store = None
            sim_id = None
            try:
                config_path = summary.get("config_path")
                resolved_config_path = (
                    None if config_path in (None, "") else Path(str(config_path))
                )
                store, sim_id = discover_result_store(resolved_config_path)
                rows = extract_observable_rows(
                    comparison_id=str(section.comparison_id),
                    variant=variant,
                    run_folder=run_folder,
                    observables=tuple(section.observable),
                    config_path=resolved_config_path,
                    store=store,
                    sim_id=sim_id,
                )
            except Exception as exc:
                summary["status"] = "observable_extraction_failed"
                summary["error_type"] = type(exc).__name__
                summary["error_message"] = str(exc)
                if section.continue_on_error:
                    continue
                raise
            finally:
                if store is not None:
                    try:
                        store.close()
                    except Exception:
                        pass
            all_rows.extend(rows)
            summary["n_observable_rows"] = len(rows)

        observables_csv = comparison_root / "observables.csv"
        write_observables_csv(observables_csv, all_rows)

        reference_variant = section.reference_variant or self._first_completed_variant_id(
            variant_summaries
        )
        detail_metrics, summary_metrics = build_comparison_metrics(
            all_rows,
            reference_variant=reference_variant,
        )
        metrics_csv = comparison_root / "comparison_metrics.csv"
        differences_csv = comparison_root / "comparison_differences.csv"
        metrics_json = comparison_root / "comparison_metrics.json"
        write_metrics_csv(
            metrics_csv,
            summary_metrics,
            fieldnames=SUMMARY_METRIC_FIELDS,
        )
        write_metrics_csv(
            differences_csv,
            detail_metrics,
            fieldnames=DETAIL_METRIC_FIELDS,
        )
        write_metrics_json(
            metrics_json,
            {
                "schema_version": "method_comparison_metrics_v1",
                "comparison_id": section.comparison_id,
                "reference_variant": reference_variant,
                "summary": summary_metrics,
                "differences": detail_metrics,
            },
        )
        data_artifacts: list[dict[str, Any]] = []
        observable_artifacts, observable_long_rows, _observable_wide_rows, observable_delta_rows = (
            write_observable_chronicle_exports(
                comparison_root=comparison_root,
                rows=all_rows,
                detail_metrics=detail_metrics,
                observables=[
                    observable.model_dump(mode="json")
                    for observable in section.observable
                ],
            )
        )
        data_artifacts.extend(observable_artifacts)
        native_artifacts, native_long_rows, _native_wide_rows, native_delta_rows = (
            write_native_timeseries_exports(
                comparison_id=str(section.comparison_id),
                comparison_root=comparison_root,
                variant_summaries=variant_summaries,
                reference_variant=reference_variant,
            )
        )
        data_artifacts.extend(native_artifacts)
        budget_artifacts, budget_rows = write_budget_exports(
            comparison_root=comparison_root,
            variant_summaries=variant_summaries,
        )
        data_artifacts.extend(budget_artifacts)
        execution_artifacts, execution_rows = write_execution_summary_csv(
            comparison_root=comparison_root,
            variant_summaries=variant_summaries,
            reference_variant=reference_variant,
        )
        data_artifacts.extend(execution_artifacts)
        figure_artifacts = generate_comparison_figures(
            cfg=self.cfg,
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
        report_path = comparison_root / "comparison_report.md"
        report_path.write_text(
            build_comparison_report(
                comparison_id=str(section.comparison_id),
                reference_variant=reference_variant,
                variant_summaries=variant_summaries,
                observables=[
                    observable.model_dump(mode="json")
                    for observable in section.observable
                ],
                rows=all_rows,
                summary_metrics=summary_metrics,
                figure_artifacts=figure_artifacts,
                data_artifacts=data_artifacts,
            ),
            encoding="utf-8",
        )

        manifest = {
            "schema_version": "method_comparison_manifest_v2",
            "comparison_id": section.comparison_id,
            "config_path": str(self.config_path),
            "comparison_root": str(comparison_root),
            "base_simulation_config": (
                None
                if self.cfg.base_simulation_config_path is None
                else str(self.cfg.base_simulation_config_path)
            ),
            "run_variants": section.run_variants,
            "continue_on_error": section.continue_on_error,
            "reference_variant": reference_variant,
            "observables_csv": str(observables_csv),
            "comparison_metrics_csv": str(metrics_csv),
            "comparison_differences_csv": str(differences_csv),
            "comparison_metrics_json": str(metrics_json),
            "comparison_report_md": str(report_path),
            "comparison_figures_dir": str(comparison_root / "comparison_figures"),
            "comparison_figures": figure_artifacts,
            "comparison_data_artifacts": data_artifacts,
            "n_observable_rows": len(all_rows),
            "n_metric_rows": len(summary_metrics),
            "n_difference_rows": len(detail_metrics),
            "wall_time_seconds": round(time.monotonic() - started_at, 2),
            "variants": variant_summaries,
            "observables": [
                observable.model_dump(mode="json")
                for observable in section.observable
            ],
        }
        manifest_path = comparison_root / "comparison_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        manifest["manifest_path"] = str(manifest_path)
        return manifest

    def _run_or_reuse_variant(self, variant) -> dict[str, Any]:
        """Run a variant simulation or resolve an existing run folder."""
        section = self.cfg.method_comparison
        config_path: Path | None = None
        run_folder = self.cfg.resolve_variant_run_folder(variant)
        status = "reused"
        error_type: str | None = None
        error_message: str | None = None
        wall_seconds: float | None = None

        try:
            config_path = materialize_variant_config(cfg=self.cfg, variant=variant)
            if section.run_variants and config_path is not None:
                from hydromodpy.workflow.pipelines.process_simulation import HydroModPyLauncher

                start = time.monotonic()
                run_state = HydroModPyLauncher(config_path).run()
                wall_seconds = round(time.monotonic() - start, 2)
                run_folder = self._resolve_completed_run_folder(
                    run_state=run_state,
                    solver_name=str(variant.solver),
                )
                status = "completed"
            elif run_folder is None and config_path is not None:
                run_folder = self._infer_run_folder_from_config(
                    config_path,
                    solver_name=str(variant.solver or ""),
                )
                status = "reused"
            elif run_folder is None:
                raise ValueError(
                    f"Variant '{variant.id}' has no config_path or run_folder"
                )

            metrics = compact_run_metrics(read_json_file(run_folder / "_metrics.json"))
            metadata = read_variant_run_metadata(run_folder)
            return {
                "id": variant.id,
                "label": variant.label or variant.id,
                "status": status,
                "enabled": True,
                "solver": variant.solver,
                "mesh_label": variant.mesh_label,
                "mesh_mode": variant.mesh_mode,
                "config_path": None if config_path is None else str(config_path),
                "run_folder": str(run_folder),
                "wall_time_seconds": wall_seconds,
                "metrics": metrics,
                "run_metadata": metadata,
            }
        except Exception as exc:
            error_type = type(exc).__name__
            error_message = str(exc)
            if not section.continue_on_error:
                raise
            return {
                "id": variant.id,
                "label": variant.label or variant.id,
                "status": "failed",
                "enabled": True,
                "solver": variant.solver,
                "mesh_label": variant.mesh_label,
                "mesh_mode": variant.mesh_mode,
                "config_path": None if config_path is None else str(config_path),
                "run_folder": None if run_folder is None else str(run_folder),
                "wall_time_seconds": wall_seconds,
                "error_type": error_type,
                "error_message": error_message,
            }

    @staticmethod
    def _infer_run_folder_from_config(
        config_path: Path,
        *,
        solver_name: str | None = None,
    ) -> Path:
        """Infer one existing run folder from a simulation config path."""
        cfg = HydroModPyConfig.from_toml(config_path)
        base_folder = Path(cfg.workspace.solver_scratch_folder) / str(cfg.simulation.run_id)
        if (base_folder / "_postprocess").exists() or (
            base_folder / "_boussinesq_state_history.npz"
        ).exists():
            return base_folder

        solver_key = str(solver_name or "").strip().lower()
        if base_folder.parent.exists():
            for child in sorted(base_folder.parent.iterdir()):
                if not child.is_dir():
                    continue
                child_name = child.name.strip().lower()
                if solver_key and solver_key not in child_name:
                    continue
                if (child / "_postprocess").exists() or (
                    child / "_boussinesq_state_history.npz"
                ).exists():
                    return child
        return base_folder

    @staticmethod
    def _resolve_completed_run_folder(*, run_state: Any, solver_name: str) -> Path:
        """Return the concrete output folder produced for one completed solver run."""
        model = None
        get_model_for_solver = getattr(run_state, "get_model_for_solver", None)
        if callable(get_model_for_solver):
            try:
                model = get_model_for_solver(solver_name)
            except Exception:
                model = None

        full_path = Path(str(getattr(model, "full_path", "") or "")).expanduser()
        if str(full_path).strip() != "":
            return full_path

        workspace = run_state.setup.workspace
        run_id = run_state.setup.run_id
        return Path(workspace.solver_scratch_folder) / str(run_id)

    @staticmethod
    def _first_completed_variant_id(
        variant_summaries: list[dict[str, Any]],
    ) -> str | None:
        """Return the first variant that produced or reused results."""
        for summary in variant_summaries:
            if summary.get("status") in {"completed", "reused"}:
                return str(summary.get("id"))
        return None


__all__ = ("MethodComparisonLauncher",)
