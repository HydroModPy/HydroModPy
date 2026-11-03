"""Mesh step: plan one request, build the cell mesh with the chosen engine, cache it if needed."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError, MeshError
from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh import registry as mesh_registry
from hydromodpy.spatial.mesh.cache import (
    ARRAYS_FILENAME,
    DESCRIPTION_FILENAME,
    cache_dir,
    cache_key,
    has_cell_mesh,
    library_versions,
    load_cell_mesh,
    save_cell_mesh,
)
from hydromodpy.spatial.mesh.mesh_config import MeshConfig
from hydromodpy.spatial.mesh.model.quality import quality_warnings
from hydromodpy.spatial.mesh.planning.plan import (
    plan_mesh_request,
    resolved_sizes,
    smoothed_catchment,
)
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.steps.mesh_inputs import planning_inputs

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
    from hydromodpy.spatial.mesh.planning.refinement_zones import RefinementZone
    from hydromodpy.spatial.mesh.refinement_config import RefinementZoneConfig
    from hydromodpy.spatial.mesh.request import MeshRequest

logger = get_logger(__name__)


def _project_root(ctx: WorkflowContext) -> Path:
    """Return the project root the mesh cache lives under."""
    workspace = ctx.setup.workspace
    if workspace is None:
        raise MeshError("The mesh cache lives under the project root, and no workspace is set up.")
    return Path(workspace.project_root)


def step_mesh(ctx: WorkflowContext, *, resume: bool = False) -> None:
    """Build ``setup.cell_mesh`` with the engine of ``[mesh]``.

    An engine that cannot rebuild its mesh bit for bit (``needs_cache``) builds
    it once per request: the project cache answers every later run. With
    ``resume`` a missing cache entry is reported, since meshing again then gives
    a mesh the earlier results were not computed on. A mesh whose cells cross a
    quality threshold of :mod:`hydromodpy.spatial.mesh.model.quality` is logged
    with a warning and used as it is.
    """
    mesh_cfg = ctx.cfg.mesh or MeshConfig()
    inputs = planning_inputs(ctx, mesh_cfg)
    request = plan_mesh_request(mesh_cfg, inputs)
    engine_cls = mesh_registry.get(mesh_cfg.engine)
    key = directory = cell_mesh = None
    if engine_cls.capabilities.needs_cache:
        key = cache_key(request, engine_cls)
        directory = cache_dir(_project_root(ctx), key)
        if has_cell_mesh(directory):
            cell_mesh = load_cell_mesh(directory)
        elif resume:
            logger.warning(
                "The cached mesh of this request is gone (%s); meshing again gives a mesh "
                "that differs from the one the earlier results were computed on.",
                directory,
            )
    if cell_mesh is None:
        cell_mesh = mesh_registry.create(mesh_cfg.engine).build(request)
        if directory is not None:
            save_cell_mesh(cell_mesh, directory)
    for warning in quality_warnings(cell_mesh.qa):
        logger.warning("Mesh quality: %s", warning)
    # The cache holds the mesh as the engine built it. The outline the planner
    # smoothed is a function of the request, so a mesh loaded from the cache gets
    # it as well, and the solver reads its cells against it.
    smoothed = smoothed_catchment(mesh_cfg, inputs)
    if smoothed is not None:
        cell_mesh = cell_mesh.with_smoothed_catchment(smoothed)
    ctx.setup.cell_mesh = cell_mesh
    ctx.setup.mesh_summary = {
        "engine": cell_mesh.identity.engine_id,
        "engine_version": cell_mesh.identity.engine_version,
        "request_hash": request.canonical_hash(),
        "source_runs": list(request.source_runs),
        "zone_runs": _zone_runs(mesh_cfg.refinement_zone, inputs.refinement_zones),
        "cache_key": key,
        "library_versions": library_versions(),
        "qa": _qa_with_notes(cell_mesh, request),
        "sizes": resolved_sizes(mesh_cfg, request),
    }


def _zone_runs(
    cfgs: Sequence[RefinementZoneConfig], zones: Sequence[RefinementZone]
) -> dict[str, str]:
    """The ``sim_id`` of the run each zone read, by the reference its table writes.

    The frozen configuration writes these ``sim_id`` in place of the run names,
    so a replay reads the run the mesh came from, not a later ``.vN`` of it.
    The planner leaves out a zone drawn by a threshold when the engine does not
    grade its cells, and then no run was read. Otherwise it keeps one zone per
    table, in order.
    """
    if len(zones) != len(cfgs):
        return {}
    return {
        cfg.run: zone.source_run
        for cfg, zone in zip(cfgs, zones, strict=True)
        if cfg.run is not None and zone.source_run is not None
    }


def _qa_with_notes(cell_mesh: PlanarCellMesh, request: MeshRequest) -> dict[str, object]:
    """The QA of the mesh, with the planner's notes after the engine's.

    The voronoi engine already copies the planner's notes into its QA, so a
    note the QA holds is not added twice.
    """
    qa = cell_mesh.qa.as_dict()
    qa["notes"] = [*qa["notes"], *(note for note in request.notes if note not in qa["notes"])]
    return qa


class BuildMeshStep:
    """Build the cell mesh and complete the spatial supports."""

    name = "build_mesh"
    reads: ClassVar[tuple[str, ...]] = (
        "ctx",
        "requested_domain_supports",
        "spatial_support_registry",
    )
    writes: ClassVar[tuple[str, ...]] = ("ctx",)
    config_sections: ClassVar[tuple[str, ...]] = ("domain.supports", "mesh")

    def depends_on(self) -> tuple[str, ...]:
        return ("load_data",)

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.workflow.steps.setup import step_spatial_supports

        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("BuildMeshStep requires 'ctx' in state.data")

        requested_supports = state.get("requested_domain_supports") or {}
        registry = state.get("spatial_support_registry")

        step_spatial_supports(
            ctx,
            phase="data",
            requested_domain_supports=requested_supports,
            registry=registry,
        )
        step_mesh(ctx)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )

    def artifacts(self, state_out: PipelineState) -> tuple[str, ...]:
        """Return the cached mesh this step left on disk, none for an engine without cache."""
        ctx = state_out.get("ctx")
        summary = None if ctx is None else ctx.setup.mesh_summary
        key = None if summary is None else summary.get("cache_key")
        if key is None:
            return ()
        directory = cache_dir(_project_root(ctx), key)
        return (str(directory / ARRAYS_FILENAME), str(directory / DESCRIPTION_FILENAME))

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        """Reload the mesh a previous process built, from the project cache.

        A request plans to the same hash in every process, so the cache entry
        a crashed run stored is the one this resume reads. An engine without
        cache is rebuilt, which is exact.
        """
        ctx = prior_state.get("ctx")
        if ctx is None:
            raise ConfigError("BuildMeshStep.rebuild_state requires 'ctx' in state.data")
        if ctx.setup.cell_mesh is None:
            step_mesh(ctx, resume=True)
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )

    def is_prebuilt(self, state: PipelineState) -> bool:
        """True when the in-memory ctx already carries the mesh."""
        ctx = state.get("ctx")
        return ctx is not None and ctx.setup.cell_mesh is not None
