"""Launcher scaffold for model-calibration workflows."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from hydromodpy.core.config.toml_loader import load_toml_with_base_config

from hydromodpy.analysis.calibration.engine.config import ModelCalibrationConfig
from hydromodpy.analysis.calibration.engine.objective_mapping import run_objective_mapping
from hydromodpy.analysis.calibration.engine.reporting import persist_calibration_report
from hydromodpy.analysis.calibration.engine.session import (
    CandidateRunOutcome,
    ModelCalibrationObjectiveEvaluator,
    actualize_candidate,
    build_model_distribution_payload,
    execute_best_candidate_rerun,
    execute_model_distribution_reruns,
    finalize_calibration_session,
    initialize_calibration_session,
    persist_iteration_record,
    prepare_calibration_session,
    update_session_manifest,
)
from hydromodpy.analysis.calibration.engine.state import ModelCalibrationState


class ModelCalibrationLauncher:
    """Validate and prepare one model-calibration session."""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).resolve()
        raw_toml = load_toml_with_base_config(self.config_path)
        self.cfg = ModelCalibrationConfig.from_toml(
            raw_toml,
            base_dir=self.config_path.parent,
        )
        self.state = ModelCalibrationState(cfg=self.cfg)

    def prepare(self):
        """Prepare and cache one calibration session."""
        state = self.state
        if state.prepared_session is None:
            state.prepared_session = prepare_calibration_session(
                config_path=self.config_path,
                cfg=self.cfg,
            )
            state.raw_simulation_toml = dict(state.prepared_session.raw_simulation_toml)
            state.simulation_workspace = state.prepared_session.simulation_workspace
            state.calibration_root = state.prepared_session.calibration_root
            state.core_settings = dict(state.prepared_session.core_settings)
        if not state.session_manifest:
            state.session_manifest = initialize_calibration_session(
                state.prepared_session,
                cfg=self.cfg,
            )
        return state.prepared_session

    def _record_iteration(self, *, session, record) -> None:
        """Persist or only count one iteration according to launcher config."""
        if self.cfg.model_calibration.persist_iteration_history:
            self.state.session_manifest = persist_iteration_record(
                session=session,
                record=record,
                detail_level=(
                    self.cfg.model_calibration.persist_iteration_detail_level
                ),
            )
            return
        self.state.session_manifest = update_session_manifest(
            manifest_path=session.session_manifest_path,
            record=record,
        )

    def actualize_candidate(
        self,
        params,
        *,
        iteration_index: int,
    ):
        """Materialize one candidate config override from calibrated parameters."""
        session = self.prepare()
        return actualize_candidate(
            session=session,
            cfg=self.cfg,
            params=params,
            iteration_index=iteration_index,
        )

    def run_candidate(
        self,
        params,
        *,
        iteration_index: int,
    ):
        """Execute one candidate simulation and persist the minimal iteration record."""
        session = self.prepare()

        # Build the candidate request (creates folder + overlay TOML).
        request = self.actualize_candidate(params, iteration_index=iteration_index)

        # Execute via Project.
        import hydromodpy.project as _project_mod

        project = _project_mod.Project(request.candidate_config_path, headless=True)
        try:
            project.run()
            outcome = CandidateRunOutcome(
                request=request,
                status="solver_run_succeeded",
                run_state=project._ctx,
            )
        except Exception as exc:
            outcome = CandidateRunOutcome(
                request=request,
                status="solver_run_failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        finally:
            project.close()

        record = outcome.to_iteration_record()
        self._record_iteration(session=session, record=record)
        return outcome

    def calibrate(
        self,
        *,
        project: Any = None,
        calibration_method: Any = None,
    ) -> dict[str, Any]:
        """Run the configured optimization loop through CalibrationEngine.

        Parameters
        ----------
        project:
            Pre-built :class:`~hydromodpy.project.Project` instance.
            When *None* (default), one is created automatically from
            ``simulation_config_path`` in headless mode.
        calibration_method:
            Override for the optimization method.
        """
        session = self.prepare()

        if project is None:
            import hydromodpy.project as _project_mod

            project = _project_mod.Project(
                self.cfg.simulation_config_path,
                headless=True,
            )

        def _record_iteration(record) -> None:
            self._record_iteration(
                session=session,
                record=record,
            )

        evaluator = ModelCalibrationObjectiveEvaluator(
            session=session,
            cfg=self.cfg,
            project=project,
            iteration_start=(
                int(self.state.session_manifest.get("iteration_count", 0)) + 1
            ),
            record_callback=_record_iteration,
        )
        from hydromodpy.analysis.calibration.core.engine import CalibrationEngine

        core_settings = session.core_settings
        engine = CalibrationEngine(
            observed=None,
            simulator=None,
            bounds=None,
            objective_metric=core_settings["objective_metric"],
            objective_config=core_settings["objective"],
            parameter_set=core_settings["parameter_set"],
            objective_evaluator=evaluator,
            calibration_method=calibration_method,
        )
        result = engine.calibrate(
            method=core_settings["method"],
            **core_settings["method_kwargs"],
        )
        needs_distribution_payload = (
            self.cfg.model_calibration.persist_model_distribution
            or self.cfg.model_calibration.rerun_model_distribution_with_outputs
        )
        model_distribution_payload = None
        if needs_distribution_payload:
            model_distribution_payload = build_model_distribution_payload(
                session=session,
                result=result,
                evaluator=evaluator,
            )
        best_rerun_outcome = None
        if (
            self.cfg.model_calibration.rerun_best_with_outputs
            and math.isfinite(float(result.cost_best))
        ):
            best_rerun_outcome = execute_best_candidate_rerun(
                session=session,
                cfg=self.cfg,
                result=result,
                project=project,
            )
        model_distribution_rerun_summary = None
        if self.cfg.model_calibration.rerun_model_distribution_with_outputs:
            model_distribution_rerun_summary = execute_model_distribution_reruns(
                session=session,
                cfg=self.cfg,
                distribution_payload=model_distribution_payload,
                project=project,
                max_reruns=self.cfg.model_calibration.model_distribution_max_reruns,
                selection=(
                    self.cfg.model_calibration.model_distribution_rerun_selection
                ),
            )
        objective_mapping_summary = run_objective_mapping(
            cfg=self.cfg,
            session=session,
            evaluator=evaluator,
            result=result,
        )
        result_store = self._open_calibration_result_store(session)
        self.state.session_manifest = finalize_calibration_session(
            session=session,
            result=result,
            evaluator=evaluator,
            best_rerun_outcome=best_rerun_outcome,
            model_distribution_payload=model_distribution_payload,
            model_distribution_rerun_summary=model_distribution_rerun_summary,
            objective_mapping_summary=objective_mapping_summary,
            persist_distribution=self.cfg.model_calibration.persist_model_distribution,
            result_store=result_store,
        )
        if result_store is not None:
            try:
                result_store.close()
            except Exception:
                pass
        if self.cfg.model_calibration.persist_calibration_report:
            report_summary = persist_calibration_report(
                session=session,
                cfg=self.cfg,
                manifest=self.state.session_manifest,
            )
            refreshed_manifest = dict(self.state.session_manifest)
            refreshed_manifest["calibration_report"] = report_summary
            session.session_manifest_path.write_text(
                json.dumps(refreshed_manifest, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            self.state.session_manifest = refreshed_manifest
        if project is not None:
            project.close()
        return dict(self.state.session_manifest)

    def _open_calibration_result_store(self, session) -> "Any | None":
        """Best-effort open of a SimulationCatalog for persisting calibration results.

        Returns None when the catalog cannot be opened (missing workspace,
        import error, etc.) so that calibration never fails because of
        catalog integration.
        """
        try:
            from hydromodpy.results.catalog import SimulationCatalog

            workspace = session.simulation_workspace
            if workspace is None or workspace.workspace_root is None:
                return None
            return SimulationCatalog(workspace.workspace_root)
        except Exception:
            import logging as _logging

            _logging.getLogger(__name__).debug(
                "Could not open SimulationCatalog for calibration persistence",
                exc_info=True,
            )
            return None

    def run(self) -> dict[str, Any]:
        """Validate launcher and simulation-side contracts, then prepare one session."""
        _ = self.prepare()
        return dict(self.state.session_manifest)


__all__ = ("ModelCalibrationLauncher",)
