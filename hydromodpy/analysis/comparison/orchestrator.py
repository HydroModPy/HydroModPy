"""Orchestrator for solver/mesh method comparisons.

Runs or reuses variant simulations via :class:`~hydromodpy.simulation.Simulation`,
then extracts configured observables, computes metrics, and generates
comparative figures and reports.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from hydromodpy.analysis.comparison.config import MethodComparisonConfig
from hydromodpy.analysis.comparison.exports import (
    write_budget_exports,
    write_execution_summary_csv,
    write_hydrographic_network_metrics_export,
    write_native_timeseries_exports,
    write_observable_chronicle_exports,
    write_simulated_active_network_metrics_export,
    write_simulated_active_network_overlap_metrics_export,
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
from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config.toml_loader import load_toml_with_base_config


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
                resolved_config_path = None if config_path in (None, "") else Path(str(config_path))
                preferred_sim_id = summary.get("sim_id")
                preferred_run_name = summary.get("run_name")
                store, sim_id = discover_result_store(
                    resolved_config_path,
                    preferred_sim_id=(
                        None
                        if preferred_sim_id in (None, "")
                        else str(preferred_sim_id)
                    ),
                    preferred_name=(
                        None
                        if preferred_run_name in (None, "")
                        else str(preferred_run_name)
                    ),
                )
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
                    observable.model_dump(mode="json") for observable in section.observable
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
        hydrographic_artifacts, _hydrographic_rows = write_hydrographic_network_metrics_export(
            comparison_id=str(section.comparison_id),
            comparison_root=comparison_root,
            variant_summaries=variant_summaries,
        )
        data_artifacts.extend(hydrographic_artifacts)
        simulated_active_artifacts, _simulated_active_rows = (
            write_simulated_active_network_metrics_export(
                comparison_id=str(section.comparison_id),
                comparison_root=comparison_root,
                variant_summaries=variant_summaries,
            )
        )
        data_artifacts.extend(simulated_active_artifacts)
        simulated_active_overlap_artifacts, _simulated_active_overlap_rows = (
            write_simulated_active_network_overlap_metrics_export(
                comparison_id=str(section.comparison_id),
                comparison_root=comparison_root,
                variant_summaries=variant_summaries,
            )
        )
        data_artifacts.extend(simulated_active_overlap_artifacts)
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
                    observable.model_dump(mode="json") for observable in section.observable
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
                observable.model_dump(mode="json") for observable in section.observable
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
        sim_id: str | None = None
        run_name: str | None = variant.id

        try:
            config_path = materialize_variant_config(cfg=self.cfg, variant=variant)
            if section.run_variants and config_path is not None:
                from hydromodpy.project import Project

                project = Project(config_path)
                try:
                    supports_granular_run = all(
                        callable(getattr(project, method_name, None))
                        for method_name in ("prepare", "execute", "ingest", "render", "cleanup")
                    )
                    start = time.monotonic()
                    if supports_granular_run:
                        sim_id = project.prepare(name=variant.id)
                        run_name = str(project._active_runs.get(sim_id, variant.id))
                        try:
                            project.execute(sim_id)
                            project.ingest(sim_id)
                            project.render(sim_id)
                            wall_seconds = round(time.monotonic() - start, 2)
                            run_folder = self._resolve_completed_run_folder(
                                run_state=project._ctx,
                                solver_name=str(variant.solver),
                            )
                            project.cleanup(sim_id, keep_solver_files=True)
                        except Exception:
                            try:
                                project.cleanup(
                                    sim_id,
                                    keep_solver_files=True,
                                    status="failed",
                                )
                            except Exception:
                                pass
                            raise
                    else:
                        project.run(name=variant.id)
                        wall_seconds = round(time.monotonic() - start, 2)
                        run_folder = self._resolve_completed_run_folder(
                            run_state=project._ctx,
                            solver_name=str(variant.solver),
                        )
                finally:
                    project.close()
                status = "completed"
            elif run_folder is None and config_path is not None:
                run_folder = self._infer_run_folder_from_config(
                    config_path,
                    solver_name=str(variant.solver or ""),
                )
                status = "reused"
            elif run_folder is None:
                raise ValueError(f"Variant '{variant.id}' has no config_path or run_folder")

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
                "sim_id": sim_id,
                "run_name": run_name,
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
                "sim_id": sim_id,
                "run_name": run_name,
                "wall_time_seconds": wall_seconds,
                "error_type": error_type,
                "error_message": error_message,
            }

    @staticmethod
    def _looks_like_run_folder(candidate: Path) -> bool:
        """Return whether a folder contains comparison-readable run outputs."""
        return (candidate / "_postprocess").exists() or (
            candidate / "_boussinesq_state_history.npz"
        ).exists()

    @classmethod
    def _resolve_existing_run_folder(
        cls,
        base_folder: Path,
        *,
        solver_name: str | None = None,
    ) -> Path:
        """Resolve one concrete run folder from a root, child, or sibling path."""
        base_folder = Path(base_folder).expanduser()
        solver_key = str(solver_name or "").strip().lower()

        def _append_dir(targets: list[Path], candidate: Path) -> None:
            if not candidate.exists() or not candidate.is_dir():
                return
            if any(existing == candidate for existing in targets):
                return
            targets.append(candidate)

        candidates: list[Path] = []
        _append_dir(candidates, base_folder)
        if solver_key:
            _append_dir(candidates, base_folder / solver_key)

        first_ring: list[Path] = []
        if base_folder.exists():
            for child in sorted(base_folder.iterdir()):
                _append_dir(first_ring, child)

        parent = base_folder.parent
        if parent.exists():
            for sibling in sorted(parent.iterdir()):
                _append_dir(first_ring, sibling)

        ordered_children = sorted(
            first_ring,
            key=lambda path: (
                0
                if solver_key
                and (solver_key in path.name.strip().lower())
                else 1,
                len(path.parts),
                str(path),
            ),
        )
        for child in ordered_children:
            _append_dir(candidates, child)

        second_ring: list[Path] = []
        for container in ordered_children:
            try:
                for grandchild in sorted(container.iterdir()):
                    _append_dir(second_ring, grandchild)
            except Exception:
                continue
        ordered_grandchildren = sorted(
            second_ring,
            key=lambda path: (
                0
                if solver_key
                and (
                    solver_key in path.name.strip().lower()
                    or solver_key in path.parent.name.strip().lower()
                )
                else 1,
                len(path.parts),
                str(path),
            ),
        )
        for grandchild in ordered_grandchildren:
            _append_dir(candidates, grandchild)

        for candidate in candidates:
            if cls._looks_like_run_folder(candidate):
                return candidate.resolve()
        return base_folder.resolve()

    @staticmethod
    def _infer_run_folder_from_config(
        config_path: Path,
        *,
        solver_name: str | None = None,
    ) -> Path:
        """Infer one existing run folder from a simulation config path."""
        cfg = HydroModPyConfig.from_toml(config_path)
        base_folder = Path(cfg.workspace.solver_scratch_folder) / str(cfg.simulation.run_id)
        return MethodComparisonLauncher._resolve_existing_run_folder(
            base_folder,
            solver_name=solver_name,
        )

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
            return MethodComparisonLauncher._resolve_existing_run_folder(
                full_path,
                solver_name=solver_name,
            )

        workspace = run_state.setup.workspace
        run_id = run_state.setup.run_id
        return MethodComparisonLauncher._resolve_existing_run_folder(
            Path(workspace.solver_scratch_folder) / str(run_id),
            solver_name=solver_name,
        )

    @staticmethod
    def _first_completed_variant_id(
        variant_summaries: list[dict[str, Any]],
    ) -> str | None:
        """Return the first variant that produced or reused results."""
        for summary in variant_summaries:
            if summary.get("status") in {"completed", "reused"}:
                return str(summary.get("id"))
        return None

    @staticmethod
    def pairwise(sim_a: Any, sim_b: Any, **kwargs) -> dict[str, Any]:
        """Reserved ad-hoc two-run comparison entry point.

        The public ``hydromodpy.compare(...)`` facade points here. The
        pairwise helper is not implemented in this checkout yet; callers should
        use a TOML-driven comparison through :meth:`Project.compare` or invoke
        :class:`MethodComparisonLauncher` directly with a config path.
        """
        raise NotImplementedError(
            "hydromodpy.compare(sim_a, sim_b) is not implemented in this checkout. "
            "Use Project.compare(config_path=...) or "
            "MethodComparisonLauncher(config_path).run() instead."
        )


__all__ = ("MethodComparisonLauncher",)
