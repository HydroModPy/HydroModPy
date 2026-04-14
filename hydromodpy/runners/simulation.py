"""CLI adapter for ``hmp run <config.toml>`` (simulation workflow).

Domain logic lives in :class:`hydromodpy.simulation.Simulation` and
``hydromodpy.workflow.pipelines.simulation``.
"""

from __future__ import annotations

from pathlib import Path


def run(config_path: str | Path) -> dict:
    """Execute a single simulation from a TOML file.

    This is the CLI entry point for ``hmp run config.toml`` when the TOML
    describes a simulation workflow.  It creates a Simulation, runs once
    (no overrides), and closes.
    """
    from hydromodpy.simulation import Simulation

    with Simulation(config_path) as project:
        result = project.run()
        return {
            "name": result.name,
            "sim_id": result.sim_id,
        }
