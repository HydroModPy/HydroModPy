"""Concern 2 of PrepareSolverStep: the facts of the run and its artifact paths.

Hosts the helpers that resolve the identity of the run (primary run, the
facts the seal needs, the configuration snapshot) and that introspect on-disk
artifacts (Zarr root, Parquet directory). These helpers are pure: they read
the configuration and the store layout but never write.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from hydromodpy.core.config_kit.written import written_payload
from hydromodpy.core.exceptions import PipelineError
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.core.logging import get_logger
from hydromodpy.core.site import site_fingerprint
from hydromodpy.data.sites.gauge import gauge_of_run
from hydromodpy.results.record.manifest import ManifestSite
from hydromodpy.results.storage.geo_metadata import epsg_from_crs

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.results.storage.run_store import RunStore
    from hydromodpy.solver.base.plan import SimulationPlan

logger = get_logger(__name__)


def primary_run_for_simulation(plan: SimulationPlan) -> tuple[str, str]:
    """Return the process type and the solver code of the primary run.

    Multi-solver plans (flow + transport, flow + particle tracking) record
    only their main flow run as the solver of the run. Mesh-only backends
    (catchment, etc.) are skipped so the chosen code is a solver. The process
    type comes with it, because a solver name alone is not a backend key.
    """
    for run in plan.runs:
        if run.process_type == "mesh":
            continue
        return run.process_type, run.solver
    if plan.runs:
        return plan.runs[0].process_type, plan.runs[0].solver
    raise PipelineError("Cannot open the run: SimulationPlan has no runs")


def _utc(value: Any) -> datetime | None:
    """Return *value* as a UTC-aware instant, or None."""
    if value is None:
        return None
    stamp = pd.Timestamp(value)
    stamp = stamp.tz_localize("UTC") if stamp.tz is None else stamp.tz_convert("UTC")
    return stamp.to_pydatetime()


def collect_run_facts(ctx: WorkflowContext) -> dict[str, Any]:
    """Gather what the configuration and the built model say about the run.

    The keys are fields of :class:`~hydromodpy.results.storage.run_facts.RunFacts`.
    """
    facts: dict[str, Any] = {"flow_regime": ctx.cfg.flow.flow_regime}

    if getattr(ctx, "config_path", None) is not None:
        facts["config_source"] = str(Path(ctx.config_path))

    sim_cfg = getattr(ctx.cfg, "simulation", None)
    if sim_cfg is not None:
        for field_name in ("description", "scientific_objective", "contact_email", "doi"):
            value = getattr(sim_cfg, field_name, None)
            if value is not None and value != "":
                facts[field_name] = value

    cell_mesh = ctx.setup.cell_mesh
    if cell_mesh is not None:
        mesh = cell_mesh.mesh
        facts["n_cells"] = int(cell_mesh.n_cells)
        facts["mesh_topology"] = mesh.single_cell_type.value
        facts["bbox"] = tuple(float(v) for v in mesh.bounds())
        mesh_bytes = mesh.vertices.tobytes() + cell_mesh.connectivity_rows.tobytes()
        facts["mesh_hash"] = hashlib.sha256(mesh_bytes).hexdigest()
    domain = ctx.setup.domain
    if domain is not None:
        try:
            facts["n_layers"] = max(1, len(domain.z_interfaces) - 1)
        except (ValueError, TypeError, AttributeError):
            # A domain without a substratum yet states no layer count; the
            # solver fills it after the solve.
            pass

    crs = getattr(ctx.cfg.geographic, "crs_project", None)
    if crs is not None:
        facts["crs_wkt"] = str(crs)
        facts["crs_epsg"] = epsg_from_crs(str(crs))

    tg = ctx.setup.time_grid
    if tg is not None:
        boundaries = getattr(tg, "boundaries", None)
        if boundaries and len(boundaries) >= 2:
            facts["period_start"] = _utc(boundaries[0])
            facts["period_end"] = _utc(boundaries[-1])
            facts["n_timesteps"] = len(boundaries) - 1
        else:
            datetimes = getattr(tg, "datetimes", None)
            if datetimes:
                facts["n_timesteps"] = len(datetimes)
            # A steady run holds one instant, which is the moment it was
            # prepared, not a period it simulated: it declares no extent.
            if datetimes and len(datetimes) >= 2:
                start_datetime = getattr(tg, "start_datetime", None)
                facts["period_start"] = _utc(
                    start_datetime if start_datetime is not None else datetimes[0]
                )
                facts["period_end"] = _utc(datetimes[-1])
        time_cfg = getattr(ctx.cfg.simulation, "time", None)
        if time_cfg is not None:
            facts["time_unit"] = getattr(time_cfg, "step_unit", None)

    site = site_block(ctx)
    if site is not None:
        facts["site"] = site
    return facts


def site_block(ctx: WorkflowContext) -> ManifestSite | None:
    """Return the ``site`` block of the seal, or None for a run without ``[site]``.

    The gauge is ``[site] gauge``, else the single hydrometric station the run
    loaded (:func:`~hydromodpy.data.sites.gauge.gauge_of_run`).
    """
    declared = getattr(ctx.cfg, "site", None)
    if declared is None:
        return None
    geographic = ctx.cfg.geographic
    catchment = getattr(geographic, "catchment", None)
    crs = str(getattr(geographic, "crs_project", "") or "")
    kind = str(getattr(catchment, "catch_def", "") or "")
    x_outlet = getattr(catchment, "x_outlet", None)
    y_outlet = getattr(catchment, "y_outlet", None)
    outlet = (
        (float(x_outlet), float(y_outlet))
        if x_outlet is not None and y_outlet is not None
        else None
    )
    polygon = getattr(catchment, "polyg_shp_path", None)
    polygon_digest = sha256_of(polygon) if polygon is not None and Path(polygon).is_file() else None
    if outlet is None and polygon_digest is None:
        polygon_digest = hashlib.sha256(f"{declared.name}:{kind}".encode()).hexdigest()
    hydrometry = getattr(getattr(ctx, "loaded_data", None), "hydrometry", None)
    return ManifestSite(
        name=declared.name,
        label=declared.label,
        gauge=gauge_of_run(declared, hydrometry),
        uri=declared.uri,
        fingerprint=site_fingerprint(
            crs=crs, kind=kind, outlet=outlet, polygon_sha256=polygon_digest
        ),
        x_outlet=None if outlet is None else outlet[0],
        y_outlet=None if outlet is None else outlet[1],
        crs=crs or None,
    )


def collect_effective_config_snapshot(ctx: WorkflowContext) -> dict:
    """Return the reproducible config snapshot used by the current run.

    It is the configuration of the run as written, nothing the build decided: the
    domain section is the one the document carries, the same one the run builds
    from. A default the file left out stays out: a validator that reads
    ``model_fields_set`` answers on the snapshot as it did on the file.
    """
    return written_payload(ctx.cfg)


def store_sim_artifacts(ctx: WorkflowContext, sim_id: str, *, store: RunStore) -> tuple[str, ...]:
    """Return workspace-relative paths produced for ``sim_id`` by the store."""
    workspace = getattr(ctx, "setup", None)
    workspace = getattr(workspace, "workspace", None)
    project_root: Path | None = getattr(workspace, "project_root", None)
    if project_root is None:
        return ()
    found: list[str] = []
    for path in (store.fields_path_for(sim_id), store.tables_dir_for(sim_id)):
        if path.exists():
            rel = _relative_or_none(path, project_root)
            if rel is not None:
                found.append(rel)
    return tuple(found)


def _relative_or_none(path: Path, root: Path) -> str | None:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


__all__ = (
    "primary_run_for_simulation",
    "store_sim_artifacts",
    "collect_effective_config_snapshot",
    "collect_run_facts",
    "site_block",
)
