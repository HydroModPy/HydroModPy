"""Run the Nançon transient example through the Python API.

This script keeps the reproducible TOML as the source of truth, then hands the
resolved Pydantic config to :class:`hydromodpy.Project`.
"""

from __future__ import annotations

from pathlib import Path

import hydromodpy as hmp
from hydromodpy.config.hydromodpy_config import HydroModPyConfig

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "run_transient_nwt.toml"


def build_config() -> HydroModPyConfig:
    """Return the validated config used by the Python API example."""
    return HydroModPyConfig.from_toml(CONFIG_PATH)


def main() -> None:
    """Build the project, run one simulation, and print its catalog id."""
    cfg = build_config()
    with hmp.Project(cfg) as project:
        run = project.run()
        if run is not None:
            print(f"sim_id={run.sim_id} name={run.name}")


if __name__ == "__main__":
    main()
