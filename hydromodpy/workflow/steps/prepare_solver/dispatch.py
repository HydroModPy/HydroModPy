"""Concern 3 of PrepareSolverStep: registration + store opening.

Hosts the helpers that open the SimulationCatalog, register the
simulation row, and write the per-sim CRS/time metadata to the Zarr.
These functions mutate the catalog and the on-disk store, so they are
kept separate from the pure validation helpers in :mod:`validate`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import PipelineError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.steps.prepare_solver.validate import _primary_solver_for_simulation

if TYPE_CHECKING:
    from hydromodpy.simulation.planning.plan import SimulationPlan
    from hydromodpy.workflow.context import WorkflowContext

logger = get_logger(__name__)

# Catalog solver code -> canonical binary name for provenance lookup.
_SOLVER_BINARY_NAMES: dict[str, str] = {"modflow6": "mf6", "modflow_nwt": "mfnwt"}


def _resolve_solver_binary_path(solver_name: str | None) -> str | None:
    """Resolve the cached solver binary path for provenance, or None.

    Failures (unknown solver, binary not yet installed) are swallowed so a
    provenance lookup never breaks simulation registration.
    """
    binary = _SOLVER_BINARY_NAMES.get(str(solver_name or ""))
    if binary is None:
        return None
    try:
        from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

        return str(ensure_solver_binary(binary))
    except Exception:
        return None


def _crs_grid_mapping_attrs(crs: object) -> dict[str, object]:
    """Return CF grid-mapping attrs for a CRS value."""
    try:
        from pyproj import CRS

        parsed = CRS.from_user_input(crs)
        attrs = dict(parsed.to_cf())
        if "crs_wkt" not in attrs:
            attrs["crs_wkt"] = parsed.to_wkt()
        epsg = parsed.to_epsg()
        if epsg is not None:
            attrs["epsg_code"] = int(epsg)
        return attrs
    except Exception:
        return {"crs_wkt": str(crs)}


def _write_zarr_crs(ctx: WorkflowContext, sim_id: str) -> None:
    """Persist CRS metadata in the simulation Zarr store when configured."""
    geographic_cfg = getattr(ctx.cfg, "geographic", None)
    crs = getattr(geographic_cfg, "crs_project", None)
    if crs is None:
        return
    attrs = _crs_grid_mapping_attrs(crs)
    epsg_raw = attrs.get("epsg_code")
    semi_major_raw = attrs.get("semi_major_axis")
    inverse_flattening_raw = attrs.get("inverse_flattening")
    ctx.store.write_crs(
        sim_id,
        crs_wkt=str(attrs.get("crs_wkt", str(crs))),
        grid_mapping_name=str(attrs.get("grid_mapping_name", "latitude_longitude")),
        epsg_code=int(str(epsg_raw).strip()) if epsg_raw is not None else None,
        semi_major_axis=float(str(semi_major_raw).strip()) if semi_major_raw is not None else None,
        inverse_flattening=(
            float(str(inverse_flattening_raw).strip())
            if inverse_flattening_raw is not None
            else None
        ),
    )


def _write_zarr_time(ctx: WorkflowContext, sim_id: str) -> None:
    """Persist simulation period-end timestamps as CF time coordinates."""
    time_grid = getattr(ctx.setup, "time_grid", None)
    boundaries = getattr(time_grid, "boundaries", None)
    import numpy as np
    import pandas as pd

    if boundaries and len(boundaries) >= 2:
        period_ends = pd.DatetimeIndex(boundaries[1:])
    else:
        datetimes = getattr(time_grid, "datetimes", None)
        if not datetimes:
            return
        period_ends = pd.DatetimeIndex(datetimes)
    if period_ends.tz is None:
        period_ends = period_ends.tz_localize("UTC")
    else:
        period_ends = period_ends.tz_convert("UTC")
    epoch = pd.Timestamp("1970-01-01T00:00:00Z")
    seconds = ((period_ends - epoch).total_seconds()).astype("int64")
    ctx.store.write_time(
        sim_id,
        np.asarray(seconds, dtype="int64"),
        epoch="1970-01-01T00:00:00Z",
        units="seconds since 1970-01-01T00:00:00Z",
    )


def step_register_simulation(
    ctx: WorkflowContext,
    sim_id: str,
    *,
    plan: SimulationPlan,
    project_name: str,
    name: str,
) -> str:
    """Register the simulation in the catalog and return the final run name."""
    from hydromodpy.workflow.steps import prepare_solver as ps_module

    reg_kwargs = ps_module.collect_registration_kwargs(ctx)
    if ctx.parent_sim_id is not None:
        reg_kwargs["parent_sim_id"] = ctx.parent_sim_id

    primary_solver = _primary_solver_for_simulation(plan)
    registration = ctx.store.register_simulation(
        sim_id,
        project=project_name,
        solver=primary_solver,
        name=name,
        if_exists=ctx.cfg.simulation.if_exists,
        **reg_kwargs,
    )
    final_name = registration.name or name
    replaced = registration.replaced_sim_id
    short = sim_id[:8]
    if replaced:
        logger.info("Run '%s' stored [%s] (replaced %s)", final_name, short, replaced[:8])
    else:
        logger.info("Run '%s' stored [%s]", final_name, short)
    if registration.zarr is not None:
        registration.zarr.close()
    _write_zarr_time(ctx, sim_id)
    _write_zarr_crs(ctx, sim_id)

    try:
        project_root = getattr(getattr(ctx.setup, "workspace", None), "project_root", None)
        rng_seed = getattr(ctx.cfg.simulation, "rng_seed", None)
        ctx.store.write_run_environment(
            sim_id,
            project_root=project_root,
            solver_name=primary_solver,
            solver_binary_path=_resolve_solver_binary_path(primary_solver),
            rng_seed=rng_seed,
        )
    except Exception:
        logger.exception("Failed to capture run environment for sim %s", short)
    return final_name


def _register_tracked_input_files(ctx: WorkflowContext) -> None:
    """Walk the config tree and persist every InputFile-marked path."""
    from hydromodpy.core.tracking import collect_input_files

    try:
        entries = collect_input_files(ctx.cfg)
    except Exception as exc:
        logger.warning("Skipping tracked-file registration: %s", exc)
        return

    portable = [e for e in entries if e.portable]
    if not portable:
        return
    written = ctx.store.register_tracked_files(ctx.sim_id, portable)
    logger.debug(
        "Registered %d tracked input file(s) for simulation %s",
        written,
        ctx.sim_id,
    )


def step_open_store(ctx: WorkflowContext) -> None:
    """Open a ``SimulationCatalog`` and register the current simulation.

    Helpers are looked up on the :mod:`hydromodpy.workflow.steps.prepare_solver`
    package namespace so unit tests can monkeypatch them via
    ``prepare_solver_module.<helper>``.
    """
    from hydromodpy.workflow.steps import prepare_solver as ps_module

    results_cfg = getattr(ctx, "effective_results_config", None) or ctx.cfg.simulation.results
    if not results_cfg.persistence.save_catalog:
        return

    from uuid import uuid4

    from hydromodpy.results.catalog import SimulationCatalog

    workspace = ctx.setup.workspace
    if workspace is None:
        raise PipelineError("Workspace is required before opening the simulation catalog.")
    ctx.store = SimulationCatalog.from_workspace(
        workspace,
        persistence=results_cfg.persistence,
    )
    ctx.sim_id = str(uuid4())

    project_name = workspace.project_root.name
    plan = ctx.execution.simulation_plan

    reg_kwargs = ps_module.collect_registration_kwargs(ctx)
    if ctx.parent_sim_id is not None:
        reg_kwargs["parent_sim_id"] = ctx.parent_sim_id
    primary_solver = _primary_solver_for_simulation(plan)
    registration = ctx.store.register_simulation(
        ctx.sim_id,
        project=project_name,
        solver=primary_solver,
        name=ctx.setup.run_id,
        if_exists=ctx.cfg.simulation.if_exists,
        **reg_kwargs,
    )
    if registration.name and registration.name != ctx.setup.run_id:
        ctx.setup.run_id = registration.name
    if registration.zarr is not None:
        registration.zarr.close()
    _write_zarr_time(ctx, ctx.sim_id)
    _write_zarr_crs(ctx, ctx.sim_id)

    try:
        project_root = getattr(workspace, "project_root", None)
        rng_seed = getattr(ctx.cfg.simulation, "rng_seed", None)
        ctx.store.write_run_environment(
            ctx.sim_id,
            project_root=project_root,
            solver_name=primary_solver,
            solver_binary_path=_resolve_solver_binary_path(primary_solver),
            rng_seed=rng_seed,
        )
    except Exception:
        logger.exception("Failed to capture run environment for sim %s", ctx.sim_id[:8])

    ps_module._register_tracked_input_files(ctx)

    if ctx.setup.flow is not None:
        ps_module.step_persist_params(
            ctx.store,
            ctx.sim_id,
            ctx.setup.flow,
            domain=ctx.setup.domain,
        )

    ps_module.step_persist_mesh(ctx, ctx.sim_id)
    ps_module.step_persist_geographic(ctx, ctx.sim_id)


__all__ = (
    "step_open_store",
    "step_register_simulation",
)
