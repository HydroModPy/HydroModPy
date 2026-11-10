"""``step_build_model``: freeze the ``Flow`` of a run into the ``Model`` its solver reads.

The setup and data steps fill a ``Flow``. Once the mesh, the domain, the time
grid and the data are in place, this step reads them once, picks the rasters of
the river network, reads the earlier run a hotstart names, and puts the result
on ``setup.model``. A solver adapter reads that ``Model`` and nothing else, so
everything a backend needs is decided here, before the solve.

Window ``k`` of a chain is built from the ``Model`` of the whole simulation, because
the data and the soil reservoir run on the whole simulation. The first window of a
chain that starts from a steady or cyclic state keeps that whole ``Model`` in the
start (``over``), so its start is the one of the run in one piece. A later window
starts from the final state of the window before it, and its first period is no
longer steady. Then every per-period forcing is cut to the periods of the window.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from pydantic import BaseModel

from hydromodpy.catchment.drainage.channel_tree import (
    ChannelExits,
    channel_exits,
    read_channel_tree,
)
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.time.window import ChainWindow
from hydromodpy.mesh.cells.zonal_stats import rasterize_cell_ids
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.domain.geometry import (
    CatchmentGeometry,
    ChannelRasters,
    RasterGeometry,
    channel_rasters_for_run,
)
from hydromodpy.model.forcing.native import NativeSeries
from hydromodpy.model.initial.state import CyclicStart, InitialState, PriorState, SteadyStart
from hydromodpy.model.model import (
    Geometry,
    Model,
    ModelOptions,
    ModelTime,
    model_from_flow,
)
from hydromodpy.model.sinks_sources.etp import FlowEtpConfig
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.results.storage.prior_state import read_prior_state
from hydromodpy.workflow.steps.prepare_solver.restart import WindowSource, resolve_restart_source

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.results.storage.run_store import RunStore

logger = get_logger(__name__)


def step_build_model(
    ctx: WorkflowContext,
    *,
    store: RunStore | None = None,
    window_source: WindowSource | None = None,
) -> Model | None:
    """Build the ``Model`` of the run, put it on ``ctx.setup.model`` and return it.

    A run with no ``Flow`` has no model and ``setup.model`` is None. ``store`` is
    the open store of the run, which names the project when the workspace does
    not. A hotstart reference (a path, a run name or a ``sim_id``) is resolved
    here, so a run that resumes or a calibration trial reads a named source as
    a first run does. The earlier run is opened once, its mesh is checked
    against this run and a mismatch is refused before the solve.

    ``window_source`` is the run window ``k - 1`` of a chain left, which window
    ``k > 1`` starts from instead of ``[flow] restart_from`` and ``[flow.ic]``.

    Raises
    ------
    ConfigError
        When the hotstart reference names no run, when window ``k > 1`` has no
        source, or when the run has no cell mesh.
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
    window = getattr(setup, "chain_window", None)
    whole_grid = getattr(setup, "whole_time_grid", None)
    time_grid = getattr(setup, "time_grid", None)
    initial = _initial_state(ctx, store=store, window=window, window_source=window_source)
    model = model_from_flow(
        flow,
        geometry=geometry,
        time=ModelTime.from_flow(
            flow, time_grid if window is None or whole_grid is None else whole_grid
        ),
        options=ModelOptions.from_settings(ctx.cfg.solver),
        initial=initial,
    )
    if window is not None:
        model = window_model(model, window, grid=time_grid)
    setup.model = model
    return model


def _initial_state(
    ctx: WorkflowContext,
    *,
    store: RunStore | None,
    window: ChainWindow | None,
    window_source: WindowSource | None,
) -> PriorState | None:
    """The start state a run reads from an earlier run, or None when it computes its own.

    Window ``k > 1`` of a chain reads ``window_source``. Every other run reads the
    state ``[flow] restart_from`` names, which is the start of window 1.
    """
    if window is None or window.index == 1:
        return _prior_state(ctx, store=store)
    if window_source is None:
        raise ConfigError(
            f"window {window.index} starts from the final state of window {window.index - 1}, "
            "and no source was given. Run window "
            f"{window.index - 1} first, or set window = 'all'."
        )
    cell_mesh = ctx.setup.cell_mesh
    if cell_mesh is None:
        raise ConfigError("A window after the first needs the cell mesh of the run.")
    return read_prior_state(str(window_source.run_dir), cell_mesh, sim_id=window_source.sim_id)


def window_model(model: Model, window: ChainWindow, *, grid: Any) -> Model:
    """The model of ``window``, cut from ``model``, the model of the whole simulation.

    ``grid`` is the grid of the periods of the window. Its first period is steady
    only in window 1. The first window of a chain of more than one window that
    starts from a steady or cyclic state keeps ``model`` in the start, as ``over``,
    so the steady solve and the cycles read the forcings of the whole simulation.
    Every per-period forcing is cut to the periods of the window: the recharge and
    ETP values, the wells, the ``values`` forcings of lakes, SFR, barriers and
    boundaries, and the native recharge.
    """
    nper = len(model.time.grid.period_lengths_seconds)

    def cut(values: Any) -> Any:
        return cut_periods(values, window.first_period, window.stop_period, nper)

    initial: InitialState = model.initial
    if window.index == 1 and window.count > 1 and isinstance(initial, (SteadyStart, CyclicStart)):
        initial = replace(initial, over=model)
    recharge, etp = model.recharge, model.etp
    return replace(
        model,
        boundaries=BoundaryConditionBundle(
            conditions=_cut_tree(model.boundaries.conditions, cut),
            active_ids=model.boundaries.active_ids,
        ),
        recharge=_cut_tree(recharge, cut),
        etp=_cut_tree(etp, cut),
        native_recharge=cut_native(model.native_recharge, window),
        wells=_cut_tree(model.wells, cut),
        lakes=_cut_tree(model.lakes, cut),
        sfr=_cut_tree(model.sfr, cut),
        flow_barriers=_cut_tree(model.flow_barriers, cut),
        initial=initial,
        time=ModelTime(
            grid=grid,
            regime=model.time.regime,
            first_period_steady=model.time.first_period_steady and window.index == 1,
        ),
    )


def cut_periods(values: Any, first: int, stop: int, nper: int) -> Any:
    """``values`` cut to periods ``first`` to ``stop``, when it holds one value per period.

    A list, a tuple, an array whose first axis is the periods (a ``(nper, ncpl)``
    recharge map included), a pandas object or a table ``{period: value}`` of
    ``nper`` entries is cut. Anything else, a number for instance, holds for every
    period and comes back as it is.
    """
    if isinstance(values, (str, bytes)):
        return values
    if hasattr(values, "iloc") and len(values) == nper:
        cut = values.iloc[first:stop]
        return cut.reset_index(drop=True) if pd.api.types.is_integer_dtype(cut.index) else cut
    if isinstance(values, np.ndarray) and values.ndim >= 1 and values.shape[0] == nper:
        return values[first:stop]
    if isinstance(values, (list, tuple)) and len(values) == nper:
        return type(values)(values[first:stop])
    if isinstance(values, Mapping) and set(values) == set(range(nper)):
        return {period - first: values[period] for period in range(first, stop)}
    return values


def _cut_tree(tree: Any, cut: Callable[[Any], Any]) -> Any:
    """``tree`` with each per-period forcing cut by ``cut``, the objects it did not change shared.

    A per-period forcing is the ``values`` of a ``{"kind": "values"}`` forcing, the
    ``values`` of the recharge and the ETP, and the ``flux`` of a well.
    """
    if isinstance(tree, Mapping):
        if tree.get("kind") == "values" and "values" in tree:
            return {**tree, "values": cut(tree["values"])}
        return {key: _cut_tree(value, cut) for key, value in tree.items()}
    if isinstance(tree, BaseModel):
        updates: dict[str, Any] = {}
        for name in ("values", "flux"):
            if _is_per_period(tree, name):
                held = getattr(tree, name)
                cut_value = cut(held)
                if cut_value is not held:
                    updates[name] = cut_value
        for name in type(tree).model_fields:
            if name not in updates and name not in ("values", "flux"):
                child = getattr(tree, name)
                if isinstance(child, (Mapping, BaseModel, list, tuple)):
                    cut_child = _cut_tree(child, cut)
                    if cut_child is not child:
                        updates[name] = cut_child
        return tree.model_copy(update=updates) if updates else tree
    if isinstance(tree, (list, tuple)):
        items = [_cut_tree(item, cut) for item in tree]
        if any(new is not old for new, old in zip(items, tree, strict=True)):
            return type(tree)(items)
    return tree


def _is_per_period(tree: BaseModel, name: str) -> bool:
    """Whether the attribute ``name`` of the payload ``tree`` holds a value per period."""
    if name not in type(tree).model_fields:
        return False
    if name == "flux":
        return not isinstance(getattr(tree, name), (int, float))
    return isinstance(tree, (FlowRechargeConfig, FlowEtpConfig)) or (
        getattr(tree, "kind", None) == "values"
    )


def cut_native(series: NativeSeries | None, window: ChainWindow) -> NativeSeries | None:
    """The native recharge cut to ``window``, or as it is when its steps do not meet the window edges."""
    if series is None:
        return None
    starts = pd.DatetimeIndex(series.starts)
    first = starts.searchsorted(window.start)
    last = starts.searchsorted(window.end)
    if (
        first >= len(starts)
        or last >= len(starts)
        or starts[first] != window.start
        or starts[last] != window.end
    ):
        return series
    return NativeSeries(
        starts=starts[first : last + 1], values=np.asarray(series.values)[first:last]
    )


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
