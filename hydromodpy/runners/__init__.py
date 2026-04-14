"""Thin CLI runner shells that dispatch TOML workflows.

Each runner does exactly three things:
1. Load and validate the TOML
2. Instantiate the appropriate object (Project, or a dedicated pipeline)
3. Call .run() and surface the result to the CLI

If a runner file exceeds ~150 lines, domain logic has leaked in and should
be extracted into ``workflow/pipelines/`` or ``analysis/``.
"""

from __future__ import annotations


def detect_workflow(raw_toml: dict) -> str:
    """Determine workflow type from top-level TOML sections.

    Returns one of: ``"calibration"``, ``"batch"``, ``"overview"``,
    ``"mesh"``, ``"simulation"``.
    """
    if "calibration" in raw_toml:
        return "calibration"
    if "batch" in raw_toml:
        return "batch"
    if "overview" in raw_toml and "simulation" not in raw_toml:
        return "overview"
    if "mesh_catchment" in raw_toml and "simulation" not in raw_toml:
        return "mesh"
    return "simulation"
