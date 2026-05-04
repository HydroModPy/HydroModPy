"""Shared Project/Pipeline phase contract.

``Project`` and ``Pipeline`` do not have the same job:

- ``Project`` owns the user-facing session state and exposes interactive verbs.
- ``Pipeline`` owns ordered execution, checkpointing, and resume.

Both still need to speak the same phase vocabulary. This module is the small
source of truth for that vocabulary so docs, tests, and orchestration code do
not drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkflowPhase:
    """One named phase in HydroModPy's simulation lifecycle."""

    name: str
    role: str
    description: str


PROJECT_MODEL_PHASES: tuple[WorkflowPhase, ...] = (
    WorkflowPhase(
        "configure",
        "project",
        "Validate configuration and create an empty workflow context.",
    ),
    WorkflowPhase(
        "setup_workspace",
        "project",
        "Bootstrap shared runtime state: workspace, geographic context, domain, and processes.",
    ),
    WorkflowPhase(
        "build_geographic",
        "project",
        "Expose the geographic/domain runtime as ready and invalidate downstream state.",
    ),
    WorkflowPhase(
        "load_data",
        "project",
        "Load external forcings and observations into the current project context.",
    ),
    WorkflowPhase(
        "build_mesh",
        "project",
        "Build or load the mesh used by solver runs.",
    ),
)

STANDARD_PIPELINE_PHASES: tuple[WorkflowPhase, ...] = (
    WorkflowPhase("validate", "pipeline", "Validate or coerce the root config object."),
    WorkflowPhase("resolve", "pipeline", "Resolve paths and create the workflow context."),
    WorkflowPhase(
        "build_geographic",
        "pipeline",
        "Build workspace, geographic runtime, domain, and setup-phase supports.",
    ),
    WorkflowPhase("load_data", "pipeline", "Load data managers and bind them to runtime objects."),
    WorkflowPhase("build_mesh", "pipeline", "Build/import mesh and data-phase supports."),
    WorkflowPhase("setup_process", "pipeline", "Ensure flow and transport processes are bound."),
    WorkflowPhase("prepare_solver", "pipeline", "Plan, register, and persist solver inputs."),
    WorkflowPhase("run_solver", "pipeline", "Execute the planned solver runs."),
    WorkflowPhase(
        "extract", "pipeline", "Ingest complementary observations after solver execution."
    ),
    WorkflowPhase("derive", "pipeline", "Compute derived result fields."),
    WorkflowPhase("export", "pipeline", "Finalize storage and export artifacts."),
    WorkflowPhase("display", "pipeline", "Render configured figures."),
)

PROJECT_MODEL_PHASE_NAMES: tuple[str, ...] = tuple(phase.name for phase in PROJECT_MODEL_PHASES)
STANDARD_PIPELINE_STEP_NAMES: tuple[str, ...] = tuple(
    phase.name for phase in STANDARD_PIPELINE_PHASES
)
PIPELINE_MODEL_STEP_NAMES: tuple[str, ...] = (
    "build_geographic",
    "load_data",
    "build_mesh",
)
PIPELINE_RUN_STEP_NAMES: tuple[str, ...] = (
    "setup_process",
    "prepare_solver",
    "run_solver",
    "extract",
    "derive",
    "export",
    "display",
)


__all__ = [
    "PIPELINE_MODEL_STEP_NAMES",
    "PIPELINE_RUN_STEP_NAMES",
    "PROJECT_MODEL_PHASE_NAMES",
    "PROJECT_MODEL_PHASES",
    "STANDARD_PIPELINE_PHASES",
    "STANDARD_PIPELINE_STEP_NAMES",
    "WorkflowPhase",
]
