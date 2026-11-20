"""The canonical order of the thirteen steps of a run.

``standard_steps`` names the thirteen steps of a full simulation in the order
the phase contract fixes, under the names of :data:`hydromodpy.core.pipeline_steps.STEP_NAMES`.

The run phase itself belongs to the steps: :class:`PrepareSolverStep` opens
what a run writes to and :class:`SealStep` seals it. What renders the run, the
exports and the figures, follows the seal and carries its label. Nothing here
drives a solver.
"""

from __future__ import annotations


def standard_steps() -> tuple:
    """Return the canonical ordered tuple of simulation pipeline steps.

    Order matches the shared phase contract in
    :data:`hydromodpy.core.pipeline_steps.STEP_NAMES`: build the geographic/domain runtime,
    load data into that runtime, build/import the mesh, bind processes, then
    prepare and run the solver. The tail is extract, derive, export, seal,
    display: the export step cleans the solver files and the scratch, the seal
    certifies the run, then the data exports and the views
    (``step_after_seal``) and the figures render the sealed run with its label
    of the day. A render that fails after the seal leaves the run sealed.
    """
    from hydromodpy.workflow.steps.data import LoadDataStep
    from hydromodpy.workflow.steps.derive import DeriveStep
    from hydromodpy.workflow.steps.display import DisplayStep
    from hydromodpy.workflow.steps.export import ExportStep, SealStep
    from hydromodpy.workflow.steps.extract import ExtractStep
    from hydromodpy.workflow.steps.mesh import BuildMeshStep
    from hydromodpy.workflow.steps.prepare_solver.step import PrepareSolverStep
    from hydromodpy.workflow.steps.resolve import ResolveStep
    from hydromodpy.workflow.steps.run_solver import RunSolverStep
    from hydromodpy.workflow.steps.setup import BuildGeographicStep, SetupProcessStep
    from hydromodpy.workflow.steps.validate import ValidateStep

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
        ExportStep(),
        SealStep(),
        DisplayStep(),
    )


__all__ = ("standard_steps",)
