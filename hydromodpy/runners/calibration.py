"""CLI adapter for ``hmp run <config.toml>`` (calibration workflow)."""

from __future__ import annotations

from pathlib import Path


def run(config_path: str | Path) -> dict:
    """Run a parameter calibration campaign from a TOML file."""
    from hydromodpy.analysis.calibration.engine.launcher import ModelCalibrationLauncher

    return ModelCalibrationLauncher(config_path).run()
