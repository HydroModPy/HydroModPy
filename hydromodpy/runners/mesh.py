"""CLI adapter for ``hmp run <config.toml>`` (mesh-only workflow)."""

from __future__ import annotations

from pathlib import Path


def run(config_path: str | Path) -> dict:
    """Generate a catchment mesh from a TOML file."""
    from hydromodpy.workflow.pipelines.mesh import MeshCatchmentLauncher

    return MeshCatchmentLauncher(config_path).run()
