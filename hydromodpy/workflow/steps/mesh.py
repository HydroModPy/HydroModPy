"""Mesh step: plan one request, build the cell mesh with the chosen engine, store it."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import ConfigError, MeshError
from hydromodpy.core.logging import get_logger
from hydromodpy.mesh import registry as mesh_registry
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.mesh.planar.quality import quality_warnings
from hydromodpy.mesh.planning.plan import plan_mesh_request, resolved_sizes, smoothed_catchment
from hydromodpy.mesh.stored import (
    ARRAYS_FILENAME,
    DESCRIPTION_FILENAME,
    SCHEMA_VERSION,
    library_versions,
    read_mesh,
)
from hydromodpy.results.products.key import product_key
from hydromodpy.results.products.store import ProductStore, products_root
from hydromodpy.workflow.products import ask
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.mesh_inputs import planning_inputs

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
    from hydromodpy.mesh.planning.refinement_zones import RefinementZone
    from hydromodpy.mesh.refinement_config import RefinementZoneConfig
    from hydromodpy.mesh.request import MeshRequest

logger = get_logger(__name__)


def mesh_product_key(request: MeshRequest, engine_cls: type) -> str:
    """Return the product key of one request meshed by one engine build.

    The key reads the request hash, the engine id and version, the library
    builds and the code of the layers ``mesh`` may read, so a change in any of
    them keys a new product.
    """
    return product_key(
        "mesh",
        codec=SCHEMA_VERSION,
        package="mesh",
        inputs={},
        processing={"request": request.canonical_hash()},
        engine={
            "engine_id": engine_cls.engine_id,
            "engine_version": engine_cls.engine_version,
            **library_versions(),
        },
    )


def _read_mesh(directory: Path, *, request: MeshRequest, engine_cls: type) -> PlanarCellMesh:
    """Read a stored mesh, refusing one whose identity is not this request's.

    A product installed under a key its content does not hold must never serve
    another mesh than the one asked for: the engine id, version and request hash
    written next to the arrays are compared to the request and the engine.
    """
    cell_mesh = read_mesh(directory)
    identity = cell_mesh.identity
    if (
        identity.engine_id != engine_cls.engine_id
        or identity.engine_version != engine_cls.engine_version
        or identity.request_hash != request.canonical_hash()
    ):
        raise MeshError(
            f"The stored mesh in {directory} holds {identity.engine_id} "
            f"{identity.engine_version} of request {identity.request_hash}, not "
            f"{engine_cls.engine_id} {engine_cls.engine_version} of request "
            f"{request.canonical_hash()}. Delete it."
        )
    return cell_mesh


def step_mesh(ctx: WorkflowContext) -> None:
    """Build ``setup.cell_mesh`` with the engine of ``[mesh]``, through the product store.

    Every engine goes through the store: a present product is read back, a
    missing one is built and stored under the workspace cap. A resumed run asks
    for the key its ``products.json`` cites, so the mesh a crashed run stored is
    the one this resume reads. A mesh whose cells cross a quality threshold of
    :mod:`hydromodpy.mesh.planar.quality` is logged with a warning and used as
    it is.
    """
    mesh_cfg = ctx.cfg.mesh or MeshConfig()
    inputs = planning_inputs(ctx, mesh_cfg)
    request = plan_mesh_request(mesh_cfg, inputs)
    engine_cls = mesh_registry.mesh_engines.get(mesh_cfg.engine)
    key = mesh_product_key(request, engine_cls)
    cell_mesh = ask(
        ctx,
        "mesh",
        key=key,
        build=lambda: mesh_registry.mesh_engines.create(mesh_cfg.engine).build(request),
        read=lambda directory: _read_mesh(directory, request=request, engine_cls=engine_cls),
        rebuild_differs=engine_cls.capabilities.needs_cache,
    )
    for warning in quality_warnings(cell_mesh.qa):
        logger.warning("Mesh quality: %s", warning)
    # The store holds the mesh as the engine built it. The outline the planner
    # smoothed is a function of the request, so a mesh read from the store gets
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
        "zone_runs": zone_runs(mesh_cfg.refinement_zone, inputs.refinement_zones),
        # The key ask used: on a resume, the one the run cited when it was read.
        "product_key": ctx.setup.products["mesh"],
        "library_versions": library_versions(),
        "qa": _qa_with_notes(cell_mesh, request),
        "sizes": resolved_sizes(mesh_cfg, request),
    }


def zone_runs(
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
        """Return the stored mesh this step left on disk, for the step journal."""
        ctx = state_out.get("ctx")
        summary = None if ctx is None else ctx.setup.mesh_summary
        key = None if summary is None else summary.get("product_key")
        if key is None:
            return ()
        directory = ProductStore(products_root(ctx.cfg.workspace.project_root)).path(key)
        return (str(directory / ARRAYS_FILENAME), str(directory / DESCRIPTION_FILENAME))

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        """Reload the mesh a previous process stored, from the product store.

        A request plans to the same hash in every process, so the product a
        crashed run stored is the one this resume reads: ``ask`` takes the key
        the run cited in its ``products.json``.
        """
        ctx = prior_state.get("ctx")
        if ctx is None:
            raise ConfigError("BuildMeshStep.rebuild_state requires 'ctx' in state.data")
        if ctx.setup.cell_mesh is None:
            step_mesh(ctx)
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
        )

    def is_prebuilt(self, state: PipelineState) -> bool:
        """True when the in-memory ctx already carries the mesh."""
        ctx = state.get("ctx")
        return ctx is not None and ctx.setup.cell_mesh is not None
