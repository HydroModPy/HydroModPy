"""Launcher scaffold for model-calibration workflows."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from hydromodpy.core.config.toml_loader import load_toml_with_base_config

from launchers.model_calibration.config import ModelCalibrationConfig
from launchers.model_calibration.objective_mapping import run_objective_mapping
from launchers.model_calibration.reporting import persist_calibration_report
from launchers.model_calibration.runtime import (
    ModelCalibrationObjectiveEvaluator,
    actualize_candidate,
    build_model_distribution_payload,
    execute_best_candidate_rerun,
    execute_candidate_run,
    execute_model_distribution_reruns,
    finalize_calibration_session,
    initialize_calibration_session,
    persist_iteration_record,
    prepare_calibration_session,
    update_session_manifest,
)
from launchers.model_calibration.state import ModelCalibrationState


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
        launcher_factory=None,
    ):
        """Execute one candidate simulation and persist the minimal iteration record."""
        request = self.actualize_candidate(
            params,
            iteration_index=iteration_index,
        )
        if launcher_factory is None:
            from launchers import HydroModPyLauncher

            launcher_factory = HydroModPyLauncher
        outcome = execute_candidate_run(
            request=request,
            launcher_factory=launcher_factory,
            cfg=self.cfg,
        )
        record = outcome.to_iteration_record()
        self._record_iteration(
            session=request.session,
            record=record,
        )
        return outcome

    def calibrate(
        self,
        *,
        launcher_factory=None,
        calibration_method=None,
    ) -> dict[str, Any]:
        """Run the configured optimization loop through CalibrationEngine."""
        session = self.prepare()
        if launcher_factory is None:
            from launchers import HydroModPyLauncher

            launcher_factory = HydroModPyLauncher

        def _record_iteration(record) -> None:
            self._record_iteration(
                session=session,
                record=record,
            )

        evaluator = ModelCalibrationObjectiveEvaluator(
            session=session,
            cfg=self.cfg,
            launcher_factory=launcher_factory,
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
                launcher_factory=launcher_factory,
            )
        model_distribution_rerun_summary = None
        if self.cfg.model_calibration.rerun_model_distribution_with_outputs:
            model_distribution_rerun_summary = execute_model_distribution_reruns(
                session=session,
                cfg=self.cfg,
                distribution_payload=model_distribution_payload,
                launcher_factory=launcher_factory,
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
        self.state.session_manifest = finalize_calibration_session(
            session=session,
            result=result,
            evaluator=evaluator,
            best_rerun_outcome=best_rerun_outcome,
            model_distribution_payload=model_distribution_payload,
            model_distribution_rerun_summary=model_distribution_rerun_summary,
            objective_mapping_summary=objective_mapping_summary,
            persist_distribution=self.cfg.model_calibration.persist_model_distribution,
        )
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
        return dict(self.state.session_manifest)

    def run(self) -> dict[str, Any]:
        """Validate launcher and simulation-side contracts, then prepare one session."""
        _ = self.prepare()
        return dict(self.state.session_manifest)


__all__ = ("ModelCalibrationLauncher",)
