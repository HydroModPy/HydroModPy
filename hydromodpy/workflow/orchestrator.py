"""Canonical simulation pipeline.

Five run-phase verbs (prepare_run, execute_run, ingest_run, render_run,
cleanup_run) compose a full simulation by chaining atomic steps. A single
composite ``prepare_runtime`` keeps the model-phase (setup/data/mesh) wiring
in one place for the eager Project constructor.

This is the only path from orchestration to solver. CLI, programmatic API
and frontend backends all funnel through these functions.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.simulation.execution.runner import (
    ProcessCallbacks,
    SimulationRunner,
)
from hydromodpy.workflow.steps.display import step_render_figures
from hydromodpy.workflow.steps.export import (
    step_cleanup_scratch,
    step_finalize_store,
    step_save_run_artifacts,
)
from hydromodpy.workflow.steps.extract import step_ingest_observations
from hydromodpy.workflow.steps.planning import (
    step_build_plan,
    step_configure_results,
)
from hydromodpy.workflow.steps.prepare_solver import (
    step_persist_forcings,
    step_persist_geographic,
    step_persist_mesh,
    step_persist_params,
    step_register_simulation,
    step_write_provenance,
)

if TYPE_CHECKING:
    from hydromodpy.results.run import Run
    from hydromodpy.spatial.mesh.config import MeshCatchmentConfig
    from hydromodpy.workflow.context import WorkflowContext


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


def prepare_run(
    ctx: WorkflowContext,
    *,
    sim_id: str,
    name: str,
    project_name: str,
    overrides: dict[str, Any] | None = None,
    thickness: float | None = None,
    first_clim: str | None = None,
    solver: str | None = None,
    properties: dict[str, Any] | None = None,
) -> str:
    """Reserve sim_id, register the simulation, persist inputs.

    Returns the catalog-assigned run name. Must be called on a context that
    has an open store (``ctx.store`` not None). No solver is launched here.
    """
    plan = step_build_plan(
        ctx,
        name=name,
        overrides=overrides or {},
        thickness=thickness,
        first_clim=first_clim,
        solver=solver,
    )

    ctx.effective_results_config = step_configure_results(ctx.cfg.simulation.results, plan)
    if properties is not None:
        ctx.setup.flow_runtime_overrides = {
            "source": "project_run",
            "properties": dict(properties),
        }
    else:
        ctx.setup.flow_runtime_overrides = None

    ctx.sim_id = sim_id
    final_name = step_register_simulation(
        ctx,
        sim_id,
        plan=plan,
        project_name=project_name,
        name=name,
    )
    ctx.setup.run_id = final_name

    if ctx.setup.flow is not None:
        step_persist_params(
            ctx.store,
            sim_id,
            ctx.setup.flow,
            domain=ctx.cfg.domain,
        )
    step_persist_mesh(ctx, sim_id)
    step_persist_geographic(ctx, sim_id)
    step_write_provenance(ctx)
    step_persist_forcings(ctx)
    return final_name


def execute_run(
    ctx: WorkflowContext,
    sim_id: str,
    *,
    final_name: str,
    after_process: Any | None = None,
) -> float:
    """Execute the planned simulation via SimulationRunner.

    The seepage derivatives are patched once here so ingest steps see a
    results config that matches the plan. Returns wall-clock seconds.
    """
    from hydromodpy.simulation.extraction.post_run import post_run_results
    from hydromodpy.simulation.planning.plan import RunContext

    plan = ctx.execution.simulation_plan
    results_cfg = ctx.effective_results_config or step_configure_results(
        ctx.cfg.simulation.results,
        plan,
    )
    ctx.effective_results_config = results_cfg

    def _after_run(run, result, state):
        post_run_results(
            ctx=RunContext(plan=plan, run=run, state=state),
            sim_id=sim_id,
            results_config=results_cfg,
            store=ctx.store,
            run_id=final_name,
        )

    wall_start = time.monotonic()
    original_domain = ctx.setup.domain
    try:
        SimulationRunner(
            callbacks=ProcessCallbacks(
                after_process=after_process,
                after_run=_after_run,
            ),
        ).execute(plan, ctx)
    finally:
        ctx.setup.domain = original_domain
        ctx.setup.flow_runtime_overrides = None
    return time.monotonic() - wall_start


def ingest_run(
    ctx: WorkflowContext,
    sim_id: str,
    *,
    extractors: list[str] | None = None,
) -> None:
    """Ingest observations attached to this simulation.

    Result extraction itself happens in ``execute_run`` via the after-run
    callback. This step covers the complementary ingestion that does not
    require the solver output directory to stay open.
    """
    step_ingest_observations(ctx, sim_id)


def render_run(
    ctx: WorkflowContext,
    sim_id: str,
    *,
    run: Run | None = None,
    figures: list[str] | None = None,
    headless: bool = False,
    no_display: bool = False,
    run_name: str | None = None,
) -> list[Path]:
    """Render the figures declared in [display] for this simulation.

    ``run`` may be pre-fetched to avoid a catalog round-trip; if None the
    run is looked up from the active store.
    """
    if run is None:
        run = ctx.store[sim_id]
    return step_render_figures(
        ctx,
        run,
        sim_id=sim_id,
        run_name=run_name or ctx.setup.run_id,
        headless=headless,
        no_display=no_display,
        figures=figures,
    )


def cleanup_run(
    ctx: WorkflowContext,
    sim_id: str,
    *,
    keep_solver_files: bool = False,
    wall_seconds: float = 0.0,
    save_artifacts: bool = True,
    close_store: bool = True,
    status: str = "completed",
) -> None:
    """Finalize the simulation row and remove the scratch directory.

    ``close_store=False`` leaves the catalog open so the caller can keep using
    it (Project lifetime). ``status`` selects the final DuckDB status and is
    usually "completed"; pass "failed" when the run raised.
    """
    if save_artifacts:
        step_save_run_artifacts(ctx, wall_seconds)

    effective = getattr(ctx, "effective_results_config", None)
    keep = keep_solver_files
    if effective is not None:
        keep = effective.keep_solver_files
    step_cleanup_scratch(ctx, keep_solver_files=keep)

    geo = ctx.setup.geographic
    if geo is not None:
        from hydromodpy.spatial.geographic.store_ingestion import (
            cleanup_stable_folder,
            dump_cached_rasters_to_disk,
        )

        geo_cfg = getattr(ctx.cfg, "geographic", None)
        if geo_cfg is not None and getattr(geo_cfg, "write_intermediates", False):
            dump_cached_rasters_to_disk(geo)
        cleanup_stable_folder(geo)

    if close_store:
        step_finalize_store(ctx, wall_seconds=wall_seconds, status=status)
    elif ctx.store is not None:
        ctx.store.finalize(sim_id, status=status, duration_s=wall_seconds)


def standard_steps() -> tuple:
    """Return the canonical ordered tuple of simulation pipeline steps.

    Order matches the ``Project`` model phase: build the geographic
    runtime (which populates ``setup.domain``), load the external
    forcings (which need ``setup.domain``), then build the mesh and the
    process objects, then prepare and run the solver.
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
        ExportStep(),
        DisplayStep(),
    )


__all__ = (
    "prepare_runtime",
    "prepare_run",
    "execute_run",
    "ingest_run",
    "render_run",
    "cleanup_run",
    "standard_steps",
)
