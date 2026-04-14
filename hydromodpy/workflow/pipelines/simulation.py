"""Simulation pipeline — Setup → Data → Mesh → Supports → Execute → Ingest.

This module provides two entry points:

- ``prepare_simulation_runtime``: run all preparation steps (setup, data,
  mesh, spatial supports) so the context is ready for execution.
- ``execute_simulation``: open the store, run the plan via
  ``SimulationRunner``, ingest results, finalize.
"""

from __future__ import annotations

import logging
import shutil
import time
from typing import TYPE_CHECKING

from hydromodpy.simulation.execution.runner import (
    ProcessCallbacks,
    SimulationRunner,
)
from hydromodpy.workflow.steps.result_ingestion import (
    step_ingest_run_results,
    step_persist_forcings,
    step_save_run_artifacts,
    step_write_provenance,
)
from hydromodpy.workflow.steps.store_lifecycle import (
    step_finalize_store,
    step_open_store,
)

if TYPE_CHECKING:
    from hydromodpy.workflow.context import WorkflowContext
    from hydromodpy.spatial.mesh.config import MeshCatchmentConfigSchema

logger = logging.getLogger(__name__)


def prepare_simulation_runtime(
    ctx: WorkflowContext,
    *,
    mesh_section_data: MeshCatchmentConfigSchema | None = None,
    constraints_mode: str | None = None,
    external_mesh_input: dict[str, str] | None = None,
    requested_domain_supports: dict[str, object] | None = None,
    spatial_support_registry: object | None = None,
    requested_spatial_support_ids: tuple[str, ...] = (),
) -> None:
    """Run all preparation steps so *ctx* is ready for execution.

    This is the shared preparation path used by ``Simulation``
    and any future consumer.
    """
    from hydromodpy.workflow.steps.data_loading import step_data_loading
    from hydromodpy.workflow.steps.mesh import step_mesh, step_mesh_input
    from hydromodpy.workflow.steps.setup import step_setup
    from hydromodpy.workflow.steps.spatial_supports import step_spatial_supports

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


def execute_simulation(
    ctx: WorkflowContext,
    *,
    after_process: object | None = None,
) -> None:
    """Open store, run the plan, ingest results, finalize.

    Parameters
    ----------
    ctx:
        Fully prepared context (call ``prepare_simulation_runtime`` first).
    after_process:
        Optional callback ``(process_type: str) -> None`` called after each
        process-family block (used by postprocess runners).
    """
    plan = ctx.execution.simulation_plan
    step_open_store(ctx)

    # Write provenance and forcings for loaded data
    if ctx.store is not None:
        step_write_provenance(ctx)
        step_persist_forcings(ctx)

    # Wire the postprocess runner's store if present.
    if ctx.postprocess_runner is not None and ctx.store is not None:
        ctx.postprocess_runner.store = ctx.store
        ctx.postprocess_runner.sim_id = ctx.sim_id

    wall_start = time.monotonic()
    try:
        SimulationRunner(
            callbacks=ProcessCallbacks(
                after_process=after_process,
                after_run=lambda run, result, state: step_ingest_run_results(
                    ctx, run, result,
                ),
            ),
        ).execute(plan, ctx)
        wall_seconds = time.monotonic() - wall_start

        step_save_run_artifacts(ctx, wall_seconds)

        # Clean up solver scratch (deferred because transport needs flow output).
        results_cfg = ctx.cfg.simulation.results
        if not results_cfg.keep_solver_files:
            scratch = ctx.setup.workspace.solver_scratch_folder
            if scratch.exists():
                shutil.rmtree(scratch, ignore_errors=True)

        # Finalize geographic intermediates.
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

        step_finalize_store(ctx, wall_seconds=wall_seconds)
    except BaseException:
        wall_seconds = time.monotonic() - wall_start
        if ctx.store is not None:
            try:
                ctx.store.finalize(ctx.sim_id, status="failed", duration_s=wall_seconds)
            except Exception:
                logger.debug("Could not finalize store on failure")
            ctx.store.close()
            ctx.store = None
        raise
