"""Runtime state for the model-calibration launcher scaffold."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hydromodpy.core.workspace.config import WorkspaceConfig

from launchers.model_calibration.config import ModelCalibrationConfig


@dataclass
class ModelCalibrationState:
    """Carries validated config plus resolved simulation-side context."""

    cfg: ModelCalibrationConfig
    raw_simulation_toml: dict[str, Any] = field(default_factory=dict)
    simulation_workspace: WorkspaceConfig | None = None
    calibration_root: Path | None = None
    core_settings: dict[str, Any] = field(default_factory=dict)
