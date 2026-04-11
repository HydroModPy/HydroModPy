"""Launcher scaffold for model-calibration workflows."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.core.config.toml_loader import load_toml_with_base_config

from launchers.model_calibration.config import ModelCalibrationConfig
from launchers.model_calibration.runtime import (
    initialize_calibration_session,
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

    def run(self) -> dict[str, Any]:
        """Validate launcher and simulation-side contracts, then prepare one session."""
        state = ModelCalibrationState(cfg=self.cfg)
        state.prepared_session = prepare_calibration_session(
            config_path=self.config_path,
            cfg=self.cfg,
        )
        state.raw_simulation_toml = dict(state.prepared_session.raw_simulation_toml)
        state.simulation_workspace = state.prepared_session.simulation_workspace
        state.calibration_root = state.prepared_session.calibration_root
        state.core_settings = dict(state.prepared_session.core_settings)
        state.session_manifest = initialize_calibration_session(
            state.prepared_session,
            cfg=self.cfg,
        )

        return dict(state.session_manifest)


__all__ = ("ModelCalibrationLauncher",)
