"""The bridge between one run and the static geometry of its stream criterion.

The construction itself lives in :mod:`hydromodpy.catchment.stream_network.geometry`, so the
criterion and the results layer that redraws a run afterwards share one
derivation. What is left here is what only a calibration knows: which model a
trial produced, what recharge it received, and where its mapped network was
declared.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.catchment.algorithms.network_heads import HeadCandidates
from hydromodpy.catchment.stream_network.geometry import (
    NetworkGeometry,
    build_network_geometry,
    open_water_mask,
    share_outside,
)
from hydromodpy.catchment.stream_network.heads import (
    HeadsSettings,
    concat_candidates,
    trace_from_heads,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.mesh.planar.geometry import padded_rows
from hydromodpy.model.forcing.recharge_rates import mean_recharge_m_s

if TYPE_CHECKING:
    from hydromodpy.calibration.config_network import CalibOutputNetwork
    from hydromodpy.calibration.observations.network_source import ObservedNetwork
    from hydromodpy.calibration.observations.observed_network import ObservedNetworkMask
    from hydromodpy.solver.base.plan import RunContext

logger = get_logger(__name__)


def dense_face_connectivity(planar_mesh: Any) -> np.ndarray:
    """Return the face-node table of the mesh, ``-1`` in the free slots of a row.

    The routing primitives read a rectangular table and ignore the negative
    padding, which is the convention of the planar mesh and of the persisted one.
    """
    connectivity = planar_mesh.flat_connectivity
    if len(connectivity) == 0:
        raise ValueError("the planar mesh holds no cell.")
    return padded_rows(connectivity, n_nodes=len(planar_mesh.vertices))


def aquifer_extent(
    run_ctx: RunContext, n_cells: int
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Return the imposed aquifer thickness and the closed columns, per cell.

    The thickness is read on the mesh the model was built from: the top minus
    the base of the lowest layer. A closed column has no top active cell to
    read a water table from: it holds no active cell, or a lake covers it. The
    model says which in ``inactive_mask``, the mask its surface processes skip.
    Each is None when the model does not carry it, or carries it on another
    cell count.
    """
    mesh = run_ctx.solver_run.solver_model.solver_mesh
    thickness = None
    botm = getattr(mesh, "botm", None)
    if botm is not None:
        base = np.asarray(botm, dtype=float)
        base = base.reshape(-1) if base.ndim == 1 else base[-1].reshape(-1)
        top = np.asarray(mesh.top, dtype=float).reshape(-1)
        if base.size == n_cells and top.size == n_cells:
            thickness = top - base
    inactive = None
    mask = getattr(run_ctx.solver_run.solver_model, "inactive_mask", None)
    if mask is not None:
        closed = np.asarray(mask, dtype=bool).reshape(-1)
        inactive = closed if closed.size == n_cells else None
    return thickness, inactive


def mesh_cell_m(run_ctx: RunContext, geometry: NetworkGeometry) -> float:
    """Return the size of one cell of the mesh a trial's network criterion scored.

    It is ``h_obs``, the median distance between neighboring cell centers over
    the mapped cells of the catchment, the same length ``r_optim`` is divided
    by. The width of an interval and the validity ratio then read one scale,
    measured where the distances start. On a regular grid it is the cell size.
    ``run_ctx`` is not read: the geometry already holds the measure.
    """
    del run_ctx
    return float(geometry.h_obs_m)


@dataclass(frozen=True)
class NetworkMaps:
    """The geometry of every map one network output is scored against.

    ``maximal`` is built on the union of the maximal and the minimal maps, so
    the maximal map contains the minimal one even where the two files
    disagree; ``frac_minimal_outside_maximal`` publishes by how much they
    did, as the share of the minimal cells of the scored catchment the
    maximal map misses. ``maximal_projection`` is the projection of that
    union, so the cells counted beside the maximal bound are the cells
    scored. ``minimal`` and its companions are None when the output
    declares no minimal map, and the share is NaN.

    The two geometries share the surface, the outlet and the catchment, which
    depend on the topography alone; they differ by the map drawn on them and
    everything read from it.
    """

    maximal: NetworkGeometry
    maximal_source: ObservedNetwork
    maximal_projection: ObservedNetworkMask
    minimal: NetworkGeometry | None = None
    minimal_source: ObservedNetwork | None = None
    minimal_projection: ObservedNetworkMask | None = None
    frac_minimal_outside_maximal: float = float("nan")


def union_projection(
    maximal: ObservedNetworkMask, minimal: ObservedNetworkMask
) -> ObservedNetworkMask:
    """Return the projection of the union of two maps drawn with one rasterization.

    The mask is the union of the two masks. The reach counts add up, since
    each counts reaches of its own file.
    """
    from hydromodpy.calibration.observations.observed_network import ObservedNetworkMask

    return ObservedNetworkMask(
        mask=np.asarray(maximal.mask, dtype=bool) | np.asarray(minimal.mask, dtype=bool),
        rasterization=maximal.rasterization,
        n_fallback_parts=int(maximal.n_fallback_parts) + int(minimal.n_fallback_parts),
        n_outside_parts=int(maximal.n_outside_parts) + int(minimal.n_outside_parts),
    )


def network_maps_from_run(run_ctx: RunContext, output: CalibOutputNetwork) -> NetworkMaps:
    """Build the static geometry of every map the output declares, from the model a trial ran.

    Each map is resolved exactly ONCE here, from whichever source the output
    declares, and threaded into its mask projection: neither this function
    nor its caller re-resolves it. The resolutions are returned alongside the
    geometries because their provenance (clipped, DEM-derived) is a trial
    diagnostic that ``NetworkGeometry`` itself does not carry. The projections
    are returned for the same reason: how many cells the output's
    ``map.drawn_by`` drew, and how many reaches it kept at their
    midpoint cell.

    Under ``map.drawn_by = "heads"`` no cell is projected: each map
    gives its free ends, the minimal map is traced from its own heads and the
    maximal one from the heads of both, so it contains the minimal trace. The
    projection returned is then the trace itself.

    Every attribute read here is named in the error it raises when missing, so
    a backend that does not expose one says which one rather than failing deep
    inside a numpy call.
    """
    from hydromodpy.calibration.observations.network_source import (
        cut_to_the_catchment,
        resolve_observed_network,
    )
    from hydromodpy.calibration.observations.observed_network import (
        catchment_outline_mask,
        delineated_catchment_mask,
        delineated_outlet_xy,
        observed_network_mask,
        resolve_minimal_network,
    )

    model = run_ctx.solver_run.solver_model
    if model is None:
        raise ValueError(f"no model recorded for run {run_ctx.run.id!r}")
    solver_mesh = getattr(model, "solver_mesh", None)
    if solver_mesh is None:
        raise ValueError(
            "the network criterion needs the solver mesh of the run: the backend "
            "exposes no 'solver_mesh' attribute."
        )
    if not hasattr(solver_mesh, "cell_centers"):
        raise ValueError(
            "the network criterion needs the cell centres the solver mesh sampled its top "
            "at: the mesh exposes no 'cell_centers' method, and deriving them from the "
            "vertices would route on other points than the elevations were read at."
        )
    planar_mesh = solver_mesh.planar_mesh
    connectivity = dense_face_connectivity(planar_mesh)
    # The centers MODFLOW 6 itself sees: on a Voronoi grid these are the
    # generator seeds written to the DISV file, which is where the mesh
    # sampled the top the criterion routes on. The crossing rule joins them.
    centres = np.asarray(solver_mesh.cell_centers(), dtype=float)
    # Resolved once per trial. Neither the mask projections below nor the
    # caller in metrics/solver_extract.py re-resolves them.
    resolved = cut_to_the_catchment(run_ctx, resolve_observed_network(run_ctx, output), output)
    minimal_source = resolve_minimal_network(run_ctx, output)
    if minimal_source is not None:
        minimal_source = cut_to_the_catchment(run_ctx, minimal_source, output)
    # The criterion routes on the TOPOGRAPHIC surface, never on the model's
    # active domain: section 4.4 measures 0.03 to 2.5 per cent of unreachable
    # cells on the first against 10.5 to 14.4 on the second. Cutting the graph
    # on the model domain also breaks the catchment into pieces the flood
    # cannot cross, and the descent then stops at the domain boundary rather
    # than at a stream. The domain restricts what the SOLVER computes; the
    # supports are restricted by the catchment the graph closes, below.
    inactive = ~np.isfinite(np.asarray(solver_mesh.top, dtype=float).reshape(-1))

    # Read once and shared by both maps: none of it depends on the map.
    topography = np.asarray(solver_mesh.top, dtype=float).reshape(-1)
    vertices = np.asarray(planar_mesh.vertices, dtype=float)
    areas = np.asarray(solver_mesh.cell_areas(), dtype=float).reshape(-1)
    recharge = mean_recharge_m_s(model)
    excluded = open_water_mask(
        getattr(model, "open_water_cell_ids", None), int(solver_mesh.n_cells)
    )
    polygon = delineated_catchment_mask(run_ctx, planar_mesh, connectivity)
    outline = catchment_outline_mask(run_ctx, planar_mesh, connectivity)
    outlet_xy = delineated_outlet_xy(run_ctx)

    def on_map(
        observed: np.ndarray | None = None,
        heads: tuple[HeadCandidates, HeadsSettings] | None = None,
    ) -> NetworkGeometry:
        # The model top, conditioned on the mesh graph by build_network_geometry.
        # Sampling the raster the geographic step conditioned is NOT equivalent:
        # that surface is pit-free on its own grid, and reading it at mesh
        # centroids both grows new pits and drops the cells whose centroid falls
        # on nodata. Measured on the Nancon, the sampled route left 51.9 per cent
        # of the simulated support unreachable against 0.0 per cent for the flood
        # on the mesh graph itself. The raster polygon and the snapped outlet
        # only place the outlet on that graph; the catchment is read there.
        return build_network_geometry(
            topography=topography,
            face_node_connectivity=connectivity,
            vertices=vertices,
            observed=observed,
            heads=heads,
            cell_area_m2=areas,
            cell_centroids=centres,
            mean_recharge_m_s=recharge,
            tau_specific_ratio=float(output.model.seepage_threshold),
            inactive_mask=inactive,
            excluded=excluded,
            delineated_catchment=polygon,
            catchment_outline=outline,
            delineated_outlet_xy=outlet_xy,
            diagonal_neighbors=output.model.neighbours == "D8",
            observed_position_accuracy_m=_accuracy_in_m(output),
            alpha_warning_threshold=float(output.verdict.alpha_warning_threshold),
            clipping_warning_share=float(output.verdict.clipping_warning_share),
            clipping_warning_gap=float(output.verdict.clipping_warning_gap),
        )

    if output.map.drawn_by == "heads":
        return _heads_maps(
            run_ctx, output, resolved, minimal_source, on_map=on_map, cell_area_m2=areas
        )

    projection = observed_network_mask(
        run_ctx,
        resolved,
        planar_mesh,
        connectivity,
        rasterization=output.map.drawn_by,
        cell_centres=centres,
    )
    minimal_projection = (
        None
        if minimal_source is None
        else observed_network_mask(
            run_ctx,
            minimal_source,
            planar_mesh,
            connectivity,
            rasterization=output.map.drawn_by,
            cell_centres=centres,
        )
    )

    if minimal_projection is None:
        return NetworkMaps(
            maximal=on_map(projection.mask),
            maximal_source=resolved,
            maximal_projection=projection,
        )
    # The maximal map contains the minimal one by definition. Two files that
    # disagree are scored on their union, and the gap is published. The
    # projection kept for the maximal map is the union too, so the cell counts
    # published beside it describe the map actually scored.
    union = union_projection(projection, minimal_projection)
    maximal = on_map(union.mask)
    minimal = on_map(minimal_projection.mask)
    outside = share_outside(minimal_projection.mask, projection.mask, maximal)
    if np.isfinite(outside) and outside > 0.0:
        logger.warning(
            "The minimal map holds %.1f%% of its catchment cells outside the maximal map. "
            "The maximal map is scored as the union of the two.",
            100.0 * outside,
        )
    return NetworkMaps(
        maximal=maximal,
        maximal_source=resolved,
        maximal_projection=union,
        minimal=minimal,
        minimal_source=minimal_source,
        minimal_projection=minimal_projection,
        frac_minimal_outside_maximal=outside,
    )


def heads_settings(output: CalibOutputNetwork) -> HeadsSettings:
    """Return where a head of this output may land, in meters and square meters."""
    return HeadsSettings(
        snap_radius_m=float(_length_in_m(output.map.heads.radius)),
        min_drained_area_m2=float(output.map.heads.min_drained_area) * 1.0e6,
    )


def _heads_maps(
    run_ctx: RunContext,
    output: CalibOutputNetwork,
    resolved: ObservedNetwork,
    minimal_source: ObservedNetwork | None,
    *,
    on_map: Callable[..., NetworkGeometry],
    cell_area_m2: np.ndarray,
) -> NetworkMaps:
    """Build the maps of a heads output: each traced down the criterion graph.

    The minimal map is traced from its own heads, the maximal one from the
    heads of both (D8 of the heads spec), so the maximal trace contains the
    minimal one. ``frac_minimal_outside_maximal`` is read against the trace
    of the maximal map's own heads, the gap the two files carry.

    The foot of each dam of the model is a head of both maps: the stream below
    a dam has no free end, so without it the reach under a reservoir is drawn
    only when the descent happens to leave the lake through the dam.
    """
    from hydromodpy.calibration.observations.observed_network import (
        ObservedNetworkMask,
        observed_head_candidates,
    )

    settings = heads_settings(output)
    dam_foot = dam_foot_cells_of_model(run_ctx.solver_run.solver_model)
    candidates = observed_head_candidates(run_ctx, resolved, dam_foot=dam_foot)
    if minimal_source is None:
        maximal = on_map(heads=(candidates, settings))
        return NetworkMaps(
            maximal=maximal,
            maximal_source=resolved,
            maximal_projection=ObservedNetworkMask(mask=maximal.observed, rasterization="heads"),
        )
    minimal_candidates = observed_head_candidates(run_ctx, minimal_source, dam_foot=dam_foot)
    maximal = on_map(heads=(concat_candidates(candidates, minimal_candidates), settings))
    minimal = on_map(heads=(minimal_candidates, settings))
    own = trace_from_heads(maximal.metric, candidates, cell_area_m2=cell_area_m2, settings=settings)
    outside = share_outside(minimal.observed, own.traced, maximal)
    if np.isfinite(outside) and outside > 0.0:
        logger.warning(
            "The minimal map traces %.1f%% of its catchment cells outside the trace of the "
            "maximal map's own heads. The maximal map is traced from the heads of both.",
            100.0 * outside,
        )
    return NetworkMaps(
        maximal=maximal,
        maximal_source=resolved,
        maximal_projection=ObservedNetworkMask(mask=maximal.observed, rasterization="heads"),
        minimal=minimal,
        minimal_source=minimal_source,
        minimal_projection=ObservedNetworkMask(mask=minimal.observed, rasterization="heads"),
        frac_minimal_outside_maximal=outside,
    )


def dam_foot_cells_of_model(model: Any) -> np.ndarray:
    """Return the cell below each dam of the built model, sorted, possibly none.

    Both MODFLOW models declare ``dam_foot_cells`` (``{lake id: cell}``); the
    MODFLOW 6 build fills it, the NWT model leaves it empty.
    """
    return np.unique(np.asarray(list(model.dam_foot_cells.values()), dtype=np.int64))


def _length_in_m(value: Any) -> float:
    """Return a length field in meters, a pint quantity or a bare number."""
    magnitude = getattr(value, "to", None)
    if callable(magnitude):
        return float(value.to("m").magnitude)
    return float(value)


def _accuracy_in_m(output: CalibOutputNetwork) -> float | None:
    """Return the declared positional accuracy in meters, or None."""
    accuracy = output.map.position_accuracy
    return None if accuracy is None else _length_in_m(accuracy)


__all__ = (
    "NetworkMaps",
    "aquifer_extent",
    "dam_foot_cells_of_model",
    "dense_face_connectivity",
    "heads_settings",
    "mesh_cell_m",
    "network_maps_from_run",
)
