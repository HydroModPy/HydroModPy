"""CLI adapter for ``hmp run <config.toml>`` (calibration workflow).

Dispatches to the P09 calibration package (``hydromodpy.calibration.cli``).
The pre-P09 ``ModelCalibrationLauncher`` has been superseded.
"""

from __future__ import annotations

from pathlib import Path


def run(config_path: str | Path) -> dict:
    """Run a parameter calibration campaign from a TOML file."""
    from hydromodpy.calibration.cli import run_calibration_cli

    return run_calibration_cli(config_path)
