"""``step_build_model``: freeze the ``Flow`` of a run into the ``Model`` its solver reads.

The setup and data steps fill a ``Flow``. Once the mesh, the domain, the time
grid and the data are in place, this step reads them once, picks the rasters of
the river network, reads the earlier run a hotstart names, and puts the result
on ``setup.model``. A solver adapter reads that ``Model`` and nothing else, so
everything a backend needs is decided here, before the solve.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.catchment.drainage.channel_tree import (
    ChannelExits,
    channel_exits,
    read_channel_tree,
)
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.mesh.cells.zonal_stats import rasterize_cell_ids
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.model.domain.geometry import (
    CatchmentGeometry,
    ChannelRasters,
    RasterGeometry,
    channel_rasters_for_run,
)
from hydromodpy.model.initial.state import PriorState
from hydromodpy.model.model import (
    Geometry,
    Model,
    ModelOptions,
    ModelTime,
    model_from_flow,
)
from hydromodpy.results.storage.prior_state import read_prior_state
from hydromodpy.workflow.steps.prepare_solver.restart import resolve_restart_source

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.results.storage.run_store import RunStore

logger = get_logger(__name__)


def step_build_model(ctx: WorkflowContext, *, store: RunStore | None = None) -> Model | None:
    """Build the ``Model`` of the run, put it on ``ctx.setup.model`` and return it.

    A run with no ``Flow`` has no model and ``setup.model`` is None. ``store`` is
    the open store of the run, which names the project when the workspace does
    not. A hotstart reference (a path, a run name or a ``sim_id``) is resolved
    here, so a run that resumes or a calibration trial reads a named source as
    a first run does. The earlier run is opened once, its mesh is checked
    against this run and a mismatch is refused before the solve.

    Raises
    ------
    ConfigError
        When the hotstart reference names no run, or the run has no cell mesh.
    IncompatibleMeshError
        When the hotstart run was solved on another mesh.
    """
    setup = ctx.setup
    flow = getattr(setup, "flow", None)
    if flow is None:
        setup.model = None
        return None
    geographic = getattr(setup, "geographic", None)
    raster = _raster_geometry(geographic)
    geometry = Geometry(
        cells=setup.cell_mesh,
        domain=setup.domain,
        raster=raster,
        catchment=_catchment_geometry(ctx, geographic),
        channel_exits=_channel_exits(
            setup.cell_mesh,
            None if raster is None else raster.channel,
            traces_bound=bool(getattr(setup, "sfr_reach_traces", None)),
        ),
    )
    model = model_from_flow(
        flow,
        geometry=geometry,
        time=ModelTime.from_flow(flow, getattr(setup, "time_grid", None)),
        options=ModelOptions.from_settings(ctx.cfg.solver),
        initial=_prior_state(ctx, store=store),
    )
    setup.model = model
    return model


def _raster_geometry(geographic: object | None) -> RasterGeometry | None:
    """The DEM grid and its settings, with the river rasters chosen once for the run."""
    if geographic is None:
        return None
    return RasterGeometry.from_geographic(geographic, channel=channel_rasters_for_run(geographic))


def _channel_exits(
    cells: PlanarCellMesh | None, rasters: ChannelRasters | None, *, traces_bound: bool
) -> ChannelExits | None:
    """The river network A read on the cells of the mesh, or None when the run has none.

    A is read when the river network step ran for the run, or when an SFR
    network was delineated from it (``traces_bound``, set by the data step
    before this one), and the three rasters exist. Rasters that an earlier
    configuration left in the folder are never read. A backend that needs A
    and finds none says so itself, because it alone knows whether SFR lies on
    the network.
    """
    if cells is None or rasters is None or rasters.link is None:
        return None
    if not (rasters.enabled or traces_bound):
        return None
    link, pointer, accumulation = rasters.link, rasters.pointer, rasters.accumulation
    if not all(path is not None and os.path.exists(path) for path in (link, pointer, accumulation)):
        return None
    vertices = np.asarray(cells.mesh.vertices, dtype=float)[:, :2]
    tree = read_channel_tree(
        link_tif=link,
        pointer_tif=pointer,
        accumulation_tif=accumulation,
        bounds=(
            float(vertices[:, 0].min()),
            float(vertices[:, 1].min()),
            float(vertices[:, 0].max()),
            float(vertices[:, 1].max()),
        ),
    )
    if np.any(tree.link):
        labels = rasterize_cell_ids(cells.mesh, transform=tree.transform, out_shape=tree.link.shape)
    else:
        labels = np.empty((0, 0), dtype=np.int32)
    return channel_exits(tree, labels, n_cells=int(cells.mesh.n_cells))


def _catchment_geometry(
    ctx: WorkflowContext, geographic: object | None
) -> CatchmentGeometry | None:
    """The catchment outline and outlet, in the CRS of the project."""
    if geographic is None:
        return None
    crs = getattr(getattr(ctx.cfg, "geographic", None), "crs_project", None)
    return CatchmentGeometry.from_geographic(geographic, crs=crs)


def _prior_state(ctx: WorkflowContext, *, store: RunStore | None) -> PriorState | None:
    """Return the state ``[flow] restart_from`` names, or None when the run has no hotstart."""
    reference = getattr(getattr(ctx.cfg, "flow", None), "restart_from", None)
    if not reference:
        return None
    cell_mesh = ctx.setup.cell_mesh
    if cell_mesh is None:
        raise ConfigError("flow.restart_from needs the cell mesh of the run, and none was built.")
    source = resolve_restart_source(_project_root(ctx, store), reference)
    return read_prior_state(str(source.path), cell_mesh, sim_id=source.sim_id)


def _project_root(ctx: WorkflowContext, store: RunStore | None) -> Path:
    """The project a hotstart name is looked up in."""
    workspace = getattr(ctx.setup, "workspace", None)
    root = getattr(workspace, "project_root", None)
    if root is None and store is not None:
        root = store.workspace_path or store.run_dir.parent.parent
    if root is None:
        raise ConfigError("flow.restart_from names a run, and the run has no project to look in.")
    return Path(root)


__all__ = ["step_build_model"]
