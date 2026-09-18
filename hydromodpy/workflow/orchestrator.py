"""Model-phase composite and the canonical step order.

Two things live here: ``prepare_runtime``, which chains the model phase
(workspace, geographic, data, mesh) in one call, and ``standard_steps``,
which names the twelve steps of a full simulation in the order the phase
contract fixes.

The run phase itself belongs to the steps: :class:`PrepareSolverStep` opens
what a run writes to and :class:`ExportStep` seals it. Nothing here drives a
solver.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.spatial.mesh.config import MeshCatchmentConfig


def prepare_runtime(
    ctx: WorkflowContext,
    *,
    mesh_section_data: MeshCatchmentConfig | None = None,
    constraints_mode: str | None = None,
    external_mesh_input: dict[str, str] | None = None,
    requested_domain_supports: dict[str, object] | None = None,
    spatial_support_registry: object | None = None,
    requested_spatial_support_ids: tuple[str, ...] = (),
) -> None:
    """Run the full model-phase: workspace, geographic, data, mesh.

    Composite used by the eager Project constructor. Step 5 exposes the four
    sub-phases as individual verbs for notebook iteration.
    """
    from hydromodpy.workflow.steps.data import step_data_loading
    from hydromodpy.workflow.steps.mesh import step_mesh, step_mesh_input
    from hydromodpy.workflow.steps.setup import step_setup, step_spatial_supports

    if requested_domain_supports is None:
        requested_domain_supports = {}

    step_setup(
        ctx,
        requested_spatial_support_ids=requested_spatial_support_ids,
        requested_domain_supports=requested_domain_supports,
    )
    step_spatial_supports(
        ctx,
        phase="setup",
        requested_domain_supports=requested_domain_supports,
        registry=spatial_support_registry,
    )
    step_data_loading(ctx)
    step_spatial_supports(
        ctx,
        phase="data",
        requested_domain_supports=requested_domain_supports,
        registry=spatial_support_registry,
    )
    step_mesh(
        ctx,
        mesh_section_data=mesh_section_data,
        constraints_mode=constraints_mode,
    )
    step_mesh_input(ctx, external_mesh_input=external_mesh_input)


def standard_steps() -> tuple:
    """Return the canonical ordered tuple of simulation pipeline steps.

    Order matches the shared phase contract in
    :mod:`hydromodpy.workflow.phases`: build the geographic/domain runtime,
    load data into that runtime, build/import the mesh, bind processes, then
    prepare and run the solver. The tail is extract, derive, display, export:
    figures are the last reader of the run, so they draw before the export
    step drops the intermediate fields and seals the store.
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
    )


__all__ = (
    "prepare_runtime",
    "standard_steps",
)
