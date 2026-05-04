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
    ComparisonConfig,
    ComparisonSection,
    ComparisonSimulation,
)
from hydromodpy.analysis.comparison.experiment_config import SimulationComparisonConfig
from hydromodpy.analysis.comparison.output_pipeline import (
    write_comparison_output_bundle,
)
from hydromodpy.analysis.comparison.run_backend import (
    ChildRunResult,
    run_child_with_hmp,
)
from hydromodpy.analysis.comparison.runtime import (
    discover_result_store,
    extract_observable_rows,
    read_simulation_run_metadata,
)
from hydromodpy.analysis.comparison.web_report import write_comparison_web_report
from hydromodpy.core.config_kit.root_config_protocol import get_root_config_provider
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
        simulation_summaries = self._run_children(children)

        comparison_cfg = self._build_comparison_cfg(children)
        all_rows = self._extract_observables(comparison_cfg, simulation_summaries)

        reference_simulation = comparison.reference_simulation or self._first_completed_id(
            simulation_summaries
        )

        audit = build_equivalence_audit(
            simulation_summaries=simulation_summaries,
            reference_simulation=reference_simulation,
            mode=comparison.audit.mode,
            on_mismatch=comparison.audit.on_mismatch,
            observable_rows=all_rows,
        )
        audit_json, audit_md = write_audit_files(
            comparison_root=comparison_root,
            audit=audit,
        )

        outputs = write_comparison_output_bundle(
            cfg=comparison_cfg,
            comparison_id=str(comparison.comparison_id),
            comparison_root=comparison_root,
            simulation_summaries=simulation_summaries,
            observables=comparison.observable,
            rows=all_rows,
            reference_simulation=reference_simulation,
            metrics_schema_version="simulation_comparison_metrics_v1",
            initial_data_artifacts=[
                {"kind": "comparison_audit_json", "path": str(audit_json)},
                {"kind": "comparison_audit_md", "path": str(audit_md)},
            ],
            report_text_transform=lambda text: self._prepend_audit_summary(text, audit),
        )

        generated_config_paths = [
            str(child.config_path)
            for child in children
            if child.generated_config and child.config_path is not None
        ]
        generated_configs_kept = bool(comparison.execution.keep_generated_configs)
        cleanup_errors: list[str] = []
        if not generated_configs_kept:
            cleanup_errors = self._cleanup_generated_configs(children)

        manifest = {
            "schema_version": "simulation_comparison_manifest_v1",
            "comparison_id": comparison.comparison_id,
            "config_path": str(self.config_path),
            "base_simulation_config": (
                None
                if self.cfg.base_simulation_config_path is None
                else str(self.cfg.base_simulation_config_path)
            ),
            "comparison_root": str(comparison_root),
            "reference_simulation": reference_simulation,
            "audit_status": audit.get("status"),
            "observables_csv": str(outputs.observables_csv),
            "comparison_metrics_csv": str(outputs.metrics_csv),
            "comparison_differences_csv": str(outputs.differences_csv),
            "comparison_metrics_json": str(outputs.metrics_json),
            "comparison_audit_json": str(audit_json),
            "comparison_audit_md": str(audit_md),
            "comparison_report_md": str(outputs.report_path),
            "comparison_figures_dir": str(comparison_root / "comparison_figures"),
            "comparison_figures": outputs.figure_artifacts,
            "comparison_data_artifacts": outputs.data_artifacts,
            "n_observable_rows": len(all_rows),
            "n_metric_rows": len(outputs.summary_metrics),
            "n_difference_rows": len(outputs.detail_metrics),
            "wall_time_seconds": round(time.monotonic() - started_at, 2),
            "generated_configs_kept": generated_configs_kept,
            "generated_config_paths": generated_config_paths,
            "generated_config_cleanup_errors": cleanup_errors,
            "simulations": simulation_summaries,
            "observables": [
                observable.model_dump(mode="json") for observable in comparison.observable
            ],
        }
        manifest_path = comparison_root / "comparison_manifest.json"
        manifest["manifest_path"] = str(manifest_path)
        try:
            web_report_path = write_comparison_web_report(
                comparison_root=comparison_root,
                manifest=manifest,
            )
            manifest["comparison_web_report"] = str(web_report_path)
            manifest.setdefault("comparison_data_artifacts", []).append(
                {"kind": "comparison_web_report_html", "path": str(web_report_path)}
            )
        except Exception as exc:
            manifest["comparison_web_report_error"] = str(exc)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

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
            if not execution.run_simulations or child.config_path is None:
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
        if child.config_path is None:
            raise ValueError(f"Comparison child '{child.simulation_id}' has no config_path")
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
            summary["error_message"] = _format_child_process_error(result)
        return summary

    def _reuse_child_summary(self, child: GeneratedChildConfig) -> dict[str, Any]:
        store = None
        sim_id = None
        if child.config_path is not None:
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
        run_folder = child.run_folder
        if run_folder is None and child.config_path is not None:
            run_folder = self._infer_run_folder_from_config(
                child.config_path,
                solver_name=child.solver,
            )
        summary = {
            "id": child.simulation_id,
            "label": child.label,
            "status": status,
            "enabled": True,
            "solver": child.solver,
            "mesh_label": child.mesh_label,
            "mesh_mode": child.mesh_mode,
            "config_path": (None if child.config_path is None else str(child.config_path)),
            "run_folder": None if run_folder is None else str(run_folder),
            "run_name": child.run_name,
        }
        if run_folder is not None and status in {"completed", "reused"}:
            summary.update(read_simulation_run_metadata(run_folder))
        return summary

    def _build_comparison_cfg(
        self,
        children: list[GeneratedChildConfig],
    ) -> ComparisonConfig:
        simulations = [
            ComparisonSimulation(
                id=child.simulation_id,
                label=child.label,
                solver=child.solver,
                mesh_label=child.mesh_label,
                mesh_mode=child.mesh_mode,  # type: ignore[arg-type]
                simulation_config=(None if child.config_path is None else str(child.config_path)),
                run_folder=None if child.run_folder is None else str(child.run_folder),
            )
            for child in children
        ]
        section = ComparisonSection(
            comparison_id=self.cfg.comparison.comparison_id,
            base_simulation_config=str(self.cfg.base_simulation_config_path),
            output_root=str(self.cfg.comparison_root),
            run_simulations=False,
            continue_on_error=self.cfg.comparison.continue_on_error,
            reference_simulation=self.cfg.comparison.reference_simulation,
            fine_raster=self.cfg.comparison.fine_raster,
            simulation=simulations,
            observable=self.cfg.comparison.observable,
        )
        return ComparisonConfig(
            config_path=self.cfg.config_path,
            base_dir=self.cfg.base_dir,
            comparison_root=self.cfg.comparison_root,
            base_simulation_config_path=self.cfg.base_simulation_config_path,
            anchors_path=self.cfg.anchors_path,
            anchors=self.cfg.anchors,
            comparison=section,
        )

    def _extract_observables(
        self,
        comparison_cfg: ComparisonConfig,
        simulation_summaries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        simulations = {
            simulation.id: simulation for simulation in comparison_cfg.comparison.simulation
        }
        for summary in simulation_summaries:
            if summary.get("status") not in {"completed", "reused"}:
                continue
            simulation = simulations.get(str(summary.get("id", "")))
            if simulation is None:
                continue
            store = None
            sim_id = None
            try:
                raw_config_path = summary.get("config_path")
                config_path = None if raw_config_path in (None, "") else Path(str(raw_config_path))
                preferred_sim_id = summary.get("sim_id")
                store = None
                sim_id = None
                if config_path is not None:
                    store, sim_id = discover_result_store(
                        config_path,
                        preferred_sim_id=(
                            None if preferred_sim_id in (None, "") else str(preferred_sim_id)
                        ),
                    )
                else:
                    sim_id = None if preferred_sim_id in (None, "") else str(preferred_sim_id)
                simulation_rows = extract_observable_rows(
                    comparison_id=str(self.cfg.comparison.comparison_id),
                    simulation=simulation,
                    run_folder=Path(str(summary["run_folder"])),
                    observables=tuple(comparison_cfg.comparison.observable),
                    config_path=config_path,
                    store=store,
                    sim_id=sim_id,
                )
                rows.extend(simulation_rows)
                summary["n_observable_rows"] = len(simulation_rows)
            finally:
                if store is not None:
                    try:
                        store.close()
                    except Exception:
                        pass
        return rows

    @staticmethod
    def _first_completed_id(simulation_summaries: list[dict[str, Any]]) -> str | None:
        for summary in simulation_summaries:
            if summary.get("status") in {"completed", "reused"}:
                return str(summary.get("id", ""))
        return None

    @staticmethod
    def _prepend_audit_summary(report_text: str, audit: dict[str, Any]) -> str:
        lines = [
            f"# Simulation Comparison Report: {audit.get('reference_simulation', '')}",
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
        generated_children = [
            child for child in children if child.generated_config and child.config_path is not None
        ]
        generated_dirs = {child.config_path.parent for child in generated_children}
        for child in generated_children:
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

    @staticmethod
    def _looks_like_run_folder(candidate: Path) -> bool:
        """Return whether a folder contains comparison-readable run outputs."""
        return (
            (candidate / "_postprocess").exists()
            or (candidate / "_boussinesq_state_history.npz").exists()
            or (candidate / "_metrics.json").exists()
        )

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
                0 if solver_key and (solver_key in path.name.strip().lower()) else 1,
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
                (
                    0
                    if solver_key
                    and (
                        solver_key in path.name.strip().lower()
                        or solver_key in path.parent.name.strip().lower()
                    )
                    else 1
                ),
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
        try:
            cfg = get_root_config_provider().from_toml(config_path)
            scratch_folder = getattr(cfg.workspace, "solver_scratch_folder", None)
            run_id = getattr(cfg.simulation, "run_id", None)
        except Exception:
            return Path(config_path).expanduser().resolve().parent
        if scratch_folder in (None, "") or run_id in (None, ""):
            return Path(config_path).expanduser().resolve().parent
        base_folder = Path(scratch_folder) / str(run_id)
        return SimulationComparisonLauncher._resolve_existing_run_folder(
            base_folder,
            solver_name=solver_name,
        )


def _format_child_process_error(result: ChildRunResult) -> str:
    """Return a concise error message with enough child output to diagnose."""
    message = f"hmp run exited with code {result.returncode}"
    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    if stderr:
        return f"{message}\nstderr tail:\n{stderr[-2000:]}"
    if stdout:
        return f"{message}\nstdout tail:\n{stdout[-2000:]}"
    return message


__all__ = ("SimulationComparisonLauncher",)
