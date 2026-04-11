"""Launcher scaffold for model-calibration workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.config.toml_loader import load_toml_with_base_config

from launchers.model_calibration.config import ModelCalibrationConfig
from launchers.model_calibration.runtime import (
    actualize_candidate,
    execute_candidate_run,
    initialize_calibration_session,
    persist_iteration_record,
    prepare_calibration_session,
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
        self.state.session_manifest = persist_iteration_record(
            session=request.session,
            record=record,
        )
        return outcome

    def run(self) -> dict[str, Any]:
        """Validate launcher and simulation-side contracts, then prepare one session."""
        _ = self.prepare()
        return dict(self.state.session_manifest)


__all__ = ("ModelCalibrationLauncher",)
