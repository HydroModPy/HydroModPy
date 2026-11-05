"""The canonical order of the thirteen steps of a run.

``standard_steps`` names the thirteen steps of a full simulation in the order
the phase contract fixes, under the names of :data:`hydromodpy.core.pipeline_steps.STEP_NAMES`.

The run phase itself belongs to the steps: :class:`PrepareSolverStep` opens
what a run writes to and :class:`SealStep` seals it. Nothing here drives a
solver.
"""

from __future__ import annotations


def standard_steps() -> tuple:
    """Return the canonical ordered tuple of simulation pipeline steps.

    Order matches the shared phase contract in
    :data:`hydromodpy.core.pipeline_steps.STEP_NAMES`: build the geographic/domain runtime,
    load data into that runtime, build/import the mesh, bind processes, then
    prepare and run the solver. The tail is extract, derive, display, export,
    seal: figures and deliverables land before the seal, which is the last
    write of the run.
    """
    from hydromodpy.workflow.steps import (
        BuildGeographicStep,
        BuildMeshStep,
        DeriveStep,
        DisplayStep,
        ExportStep,
        ExtractStep,
        LoadDataStep,
        PrepareSolverStep,
        ResolveStep,
        RunSolverStep,
        SealStep,
        SetupProcessStep,
        ValidateStep,
    )

    return (
        ValidateStep(),
        ResolveStep(),
        BuildGeographicStep(),
        LoadDataStep(),
        BuildMeshStep(),
        SetupProcessStep(),
        PrepareSolverStep(),
        RunSolverStep(),
        ExtractStep(),
        DeriveStep(),
        DisplayStep(),
        ExportStep(),
        SealStep(),
    )


__all__ = ("standard_steps",)
