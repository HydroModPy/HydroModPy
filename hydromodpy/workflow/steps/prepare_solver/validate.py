"""Concern 2 of PrepareSolverStep: validation + artefact discovery.

Hosts the helpers that resolve simulation identity (primary solver,
registration kwargs) and that introspect on-disk artefacts (Zarr root,
Parquet directory). These helpers are pure: they read configuration and
the catalog/zarr layout but never write.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import PipelineError
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.simulation.planning.plan import SimulationPlan

logger = get_logger(__name__)


def _primary_solver_for_simulation(plan: SimulationPlan) -> str:
    """Return the primary solver code stored on ``simulations.solver_id``.

    Multi-solver plans (flow + transport, flow + particle tracking) record
    only their main flow run in the catalog dimension column. Companion
    transport / particle solvers are still inspected via the per-run rows
    written by the runner. Mesh-only backends (catchment, etc.) are skipped
    so the chosen code matches one of the rows seeded in the ``solvers``
    dimension table.
    """
    for run in plan.runs:
        if run.process_type == "mesh":
            continue
        return run.solver
    if plan.runs:
        return plan.runs[0].solver
    raise PipelineError("Cannot register simulation: SimulationPlan has no runs")


def collect_registration_kwargs(ctx: WorkflowContext) -> dict:
    """Gather all available metadata from ctx for register_simulation()."""
    kwargs: dict = {"flow_regime": ctx.cfg.flow.flow_regime}

    if getattr(ctx, "config_path", None) is not None:
        kwargs["config_source"] = str(ctx.config_path)

    kwargs["config"] = ctx.cfg.model_dump(mode="json")
    kwargs["config_snapshot"] = collect_effective_config_snapshot(ctx)

    sim_cfg = getattr(ctx.cfg, "simulation", None)
    if sim_cfg is not None:
        description = getattr(sim_cfg, "description", "")
        if description:
            kwargs["description"] = description
        for field_name in (
            "scientific_objective",
            "contact_email",
            "doi",
            "study_area_name",
            "outlet_x",
            "outlet_y",
        ):
            value = getattr(sim_cfg, field_name, None)
            if value is not None and value != "":
                kwargs[field_name] = value
        tags = getattr(sim_cfg, "tags", None)
        if tags:
            kwargs["tags"] = list(tags)

    mesh = ctx.setup.mesh_planar
    if mesh is not None:
        kwargs["n_cells"] = mesh.n_cells
        kwargs["mesh_type"] = getattr(mesh, "cell_type", None)
        kwargs["cell_types"] = [getattr(mesh, "cell_type", "unknown")]
        bbox = getattr(mesh, "bounds", None)
        if bbox is not None:
            kwargs["bbox"] = list(bbox)
        try:
            mesh_bytes = mesh.points_xy.tobytes() + mesh.connectivity.tobytes()
            kwargs["mesh_hash"] = hashlib.sha256(mesh_bytes).hexdigest()
        except Exception:
            pass

    crs = getattr(ctx.cfg.geographic, "crs_project", None)
    if crs is not None:
        kwargs["crs"] = str(crs)

    tg = ctx.setup.time_grid
    if tg is not None:
        boundaries = getattr(tg, "boundaries", None)
        if boundaries and len(boundaries) >= 2:
            kwargs["period_start"] = str(boundaries[0])
            kwargs["period_end"] = str(boundaries[-1])
            kwargs["n_timesteps"] = len(boundaries) - 1
        else:
            datetimes = getattr(tg, "datetimes", None)
            if datetimes:
                start_datetime = getattr(tg, "start_datetime", None)
                kwargs["period_start"] = str(
                    start_datetime if start_datetime is not None else datetimes[0]
                )
                kwargs["period_end"] = str(datetimes[-1])
                kwargs["n_timesteps"] = len(datetimes)
        time_cfg = getattr(ctx.cfg.simulation, "time", None)
        if time_cfg is not None:
            kwargs["time_unit"] = getattr(time_cfg, "step_unit", None)

    return kwargs


def collect_effective_config_snapshot(ctx: WorkflowContext) -> dict:
    """Return the reproducible config snapshot used by the current run."""
    payload = ctx.cfg.model_dump(mode="json")

    effective_results = getattr(ctx, "effective_results_config", None)
    if effective_results is not None:
        simulation_payload = dict(payload.get("simulation") or {})
        simulation_payload["results"] = effective_results.model_dump(mode="json")
        payload["simulation"] = simulation_payload

    domain = getattr(ctx.setup, "domain", None)
    domain_config = getattr(domain, "config", None)
    if domain_config is not None and hasattr(domain_config, "model_dump"):
        payload["domain"] = domain_config.model_dump(mode="json")

    return payload


def _store_sim_artifacts(ctx: WorkflowContext, sim_id: str) -> tuple[str, ...]:
    """Return workspace-relative paths produced for ``sim_id`` by the store."""
    store = getattr(ctx, "store", None)
    if store is None:
        return ()
    workspace = getattr(ctx, "setup", None)
    workspace = getattr(workspace, "workspace", None)
    project_root: Path | None = getattr(workspace, "project_root", None)
    if project_root is None:
        return ()
    found: list[str] = []
    try:
        zarr_path = store.zarr_path_for(sim_id)
    except Exception:
        zarr_path = None
    if zarr_path is not None and zarr_path.exists():
        rel = _relative_or_none(zarr_path, project_root)
        if rel is not None:
            found.append(rel)
    try:
        parquet_dir = store.parquet_dir_for(sim_id)
    except Exception:
        parquet_dir = None
    if parquet_dir is not None and parquet_dir.exists():
        rel = _relative_or_none(parquet_dir, project_root)
        if rel is not None:
            found.append(rel)
    return tuple(found)


def _relative_or_none(path: Path, root: Path) -> str | None:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


__all__ = (
    "_primary_solver_for_simulation",
    "_relative_or_none",
    "_store_sim_artifacts",
    "collect_effective_config_snapshot",
    "collect_registration_kwargs",
)
