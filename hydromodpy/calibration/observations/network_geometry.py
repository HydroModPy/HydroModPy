"""The bridge between one run and the static geometry of its stream criterion.

The construction itself lives in :mod:`hydromodpy.core.stream_geometry`, so the
criterion and the results layer that redraws a run afterwards share one
derivation. What is left here is what only a calibration knows: which model a
trial produced, what recharge it received, and where its mapped network was
declared.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.core.stream_geometry import NetworkGeometry, build_network_geometry
from hydromodpy.core.stream_snap import SnapStreamsConfig

if TYPE_CHECKING:
    from hydromodpy.calibration.config import CalibOutputNetwork
    from hydromodpy.calibration.observations.network_source import ObservedNetwork
    from hydromodpy.calibration.observations.observed_network import ObservedNetworkMask
    from hydromodpy.simulation.planning.plan import RunContext

logger = get_logger(__name__)


def mean_recharge_m_s(model: Any) -> float:
    """Read the mean recharge back from the built model, not from the TOML.

    Unit conversion and spatial distribution can diverge between what a user
    wrote and what the solver received, and the calibrated ratio is only a
    ratio if the recharge that divides it is the one the model actually used.
    """
    recharge = getattr(model, "recharge", None)
    if recharge is None:
        raise ValueError(
            "the built model declares no recharge, so the specific seepage threshold "
            "and the K/R ratio have no denominator."
        )
    if isinstance(recharge, dict):
        values = np.concatenate(
            [np.asarray(item, dtype=float).reshape(-1) for item in recharge.values()]
        )
    else:
        values = np.asarray(recharge, dtype=float).reshape(-1)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("the recharge the model holds is not a finite number.")
    return float(np.mean(finite))


def dense_face_connectivity(planar_mesh: Any) -> np.ndarray:
    """Return a rectangular face-node table, padding ragged rows with ``-1``.

    A Voronoi dual holds cells of different arity, so its connectivity comes
    back ragged; the routing primitives read a rectangular table and ignore the
    negative padding, which is the convention the persisted mesh already uses.
    """
    connectivity = planar_mesh.flat_connectivity
    if isinstance(connectivity, np.ndarray) and connectivity.ndim == 2:
        return connectivity.astype(int, copy=False)
    rows = [np.asarray(row, dtype=int).reshape(-1) for row in connectivity]
    if not rows:
        raise ValueError("the planar mesh holds no cell.")
    dense = np.full((len(rows), max(row.size for row in rows)), -1, dtype=int)
    for index, row in enumerate(rows):
        dense[index, : row.size] = row
    return dense


def aquifer_extent(
    run_ctx: RunContext, n_cells: int
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Return the imposed aquifer thickness and the top-layer inactive cells, per cell.

    Both are read on the mesh the model was built from. The thickness is the
    top minus the base of the lowest layer. ``inactive_mask`` is what became
    IDOMAIN = 0, lake cells included. Each is None when the mesh does not carry
    it, or carries it on another cell count.
    """
    mesh = run_ctx.model.solver_mesh
    thickness = None
    botm = getattr(mesh, "botm", None)
    if botm is not None:
        base = np.asarray(botm, dtype=float)
        base = base.reshape(-1) if base.ndim == 1 else base[-1].reshape(-1)
        top = np.asarray(mesh.top, dtype=float).reshape(-1)
        if base.size == n_cells and top.size == n_cells:
            thickness = top - base
    inactive = None
    mask = getattr(mesh, "inactive_mask", None)
    if mask is not None:
        layers = np.asarray(mask, dtype=bool)
        first = layers.reshape(-1) if layers.ndim == 1 else layers[0].reshape(-1)
        inactive = first if first.size == n_cells else None
    return thickness, inactive


def mesh_cell_m(run_ctx: RunContext, geometry: NetworkGeometry) -> float:
    """Return the size of one cell of the mesh a trial's network criterion scored.

    It is ``h_obs``, the median distance between neighbouring cell centres over
    the mapped cells of the catchment, the same length ``roptim`` is divided
    by. The width of an interval and the validity ratio then read one scale,
    measured where the distances start. On a regular grid it is the cell size.
    ``run_ctx`` is not read: the geometry already holds the measure.
    """
    del run_ctx
    return float(geometry.h_obs_m)


def snap_settings(run_ctx: RunContext) -> SnapStreamsConfig | None:
    """Return the ``[geographic.snap_streams]`` setting of the run, or None when off.

    The snap is common to every consumer of the mapped network, so it is read
    from the run configuration and not from the calibration output.
    """
    cfg = getattr(getattr(run_ctx, "state", None), "cfg", None)
    setting = getattr(getattr(cfg, "geographic", None), "snap_streams", None)
    if setting is None or not setting.enabled:
        return None
    return setting


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


def share_outside(inner: np.ndarray, outer: np.ndarray, within: np.ndarray) -> float:
    """Return the share of ``inner`` cells of ``within`` that ``outer`` misses, NaN if none."""
    inside = np.asarray(inner, dtype=bool).reshape(-1) & np.asarray(within, dtype=bool).reshape(-1)
    total = int(inside.sum())
    if total == 0:
        return float("nan")
    missed = inside & ~np.asarray(outer, dtype=bool).reshape(-1)
    return float(missed.sum() / total)


def network_maps_from_run(run_ctx: RunContext, output: CalibOutputNetwork) -> NetworkMaps:
    """Build the static geometry of every map the output declares, from the model a trial ran.

    Each map is resolved exactly ONCE here, from whichever source the output
    declares, and threaded into its mask projection: neither this function
    nor its caller re-resolves it. The resolutions are returned alongside the
    geometries because their provenance (clipped, DEM-derived) is a trial
    diagnostic that ``NetworkGeometry`` itself does not carry. The projections
    are returned for the same reason: how many cells the output's
    ``observed_rasterization`` drew, and how many reaches it kept at their
    midpoint cell.

    Every attribute read here is named in the error it raises when missing, so
    a backend that does not expose one says which one rather than failing deep
    inside a numpy call.
    """
    from hydromodpy.calibration.observations.network_source import resolve_observed_network
    from hydromodpy.calibration.observations.observed_network import (
        delineated_catchment_mask,
        delineated_outlet_xy,
        observed_network_mask,
        resolve_minimal_network,
        water_body_mask,
    )

    model = run_ctx.model
    if model is None:
        raise ValueError(f"no model recorded for run {run_ctx.run.id!r}")
    solver_mesh = getattr(model, "solver_mesh", None)
    if solver_mesh is None:
        raise ValueError(
            "the network criterion needs the solver mesh of the run: the backend "
            "exposes no 'solver_mesh' attribute."
        )
    if not hasattr(solver_mesh, "cell_centroids"):
        raise ValueError(
            "the network criterion needs the cell centres the solver mesh sampled its top "
            "at: the mesh exposes no 'cell_centroids' method, and deriving them from the "
            "vertices would route on other points than the elevations were read at."
        )
    planar_mesh = solver_mesh.planar_mesh
    connectivity = dense_face_connectivity(planar_mesh)
    # The centres MODFLOW 6 itself sees: on a Voronoi grid these are the
    # generator seeds written to the DISV file, which is where the mesh
    # sampled the top the criterion routes on. The crossing rule joins them.
    centres = np.asarray(solver_mesh.cell_centroids(), dtype=float)
    # Resolved once per trial. Neither the mask projections below nor the
    # caller in metrics/solver_extract.py re-resolves them.
    resolved = resolve_observed_network(run_ctx, output)
    minimal_source = resolve_minimal_network(run_ctx, output)
    # The criterion routes on the TOPOGRAPHIC surface, never on the model's
    # active domain: section 4.4 measures 0.03 to 2.5 per cent of unreachable
    # cells on the first against 10.5 to 14.4 on the second. Cutting the graph
    # on the model domain also breaks the catchment into pieces the flood
    # cannot cross, and the descent then stops at the domain boundary rather
    # than at a stream. The domain restricts what the SOLVER computes; the
    # supports are restricted by the catchment the graph closes, below.
    inactive = ~np.isfinite(np.asarray(solver_mesh.top, dtype=float).reshape(-1))
    projection = observed_network_mask(
        run_ctx,
        resolved,
        planar_mesh,
        connectivity,
        rasterization=output.observed_rasterization,
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
            rasterization=output.observed_rasterization,
            cell_centres=centres,
        )
    )

    # Read once and shared by both maps: none of it depends on the map.
    topography = np.asarray(solver_mesh.top, dtype=float).reshape(-1)
    vertices = np.asarray(planar_mesh.vertices, dtype=float)
    areas = np.asarray(solver_mesh.cell_areas(), dtype=float).reshape(-1)
    recharge = mean_recharge_m_s(model)
    excluded = water_body_mask(model, n_cells=int(solver_mesh.n_cells))
    polygon = delineated_catchment_mask(run_ctx, planar_mesh, connectivity)
    outlet_xy = delineated_outlet_xy(run_ctx)
    # One snap setting for every map: in 'apply' each map is scored snapped.
    snap = snap_settings(run_ctx)

    def on_map(observed: np.ndarray) -> NetworkGeometry:
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
            cell_area_m2=areas,
            cell_centroids=centres,
            mean_recharge_m_s=recharge,
            tau_specific_ratio=float(output.tau_specific_ratio),
            inactive_mask=inactive,
            excluded=excluded,
            delineated_catchment=polygon,
            delineated_outlet_xy=outlet_xy,
            diagonal_neighbors=bool(output.diagonal_neighbors),
            observed_position_accuracy_m=_accuracy_in_m(output),
            alpha_warning_threshold=float(output.alpha_warning_threshold),
            clipping_warning_share=float(output.clipping_warning_share),
            clipping_warning_gap=float(output.clipping_warning_gap),
            snap=snap,
            weighting=output.weighting,
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
    outside = share_outside(minimal_projection.mask, projection.mask, maximal.catchment)
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


def _accuracy_in_m(output: CalibOutputNetwork) -> float | None:
    """Return the declared positional accuracy in metres, or None."""
    accuracy = getattr(output, "observed_position_accuracy", None)
    if accuracy is None:
        return None
    magnitude = getattr(accuracy, "to", None)
    if callable(magnitude):
        return float(accuracy.to("m").magnitude)
    return float(accuracy)


__all__ = (
    "NetworkMaps",
    "aquifer_extent",
    "dense_face_connectivity",
    "mean_recharge_m_s",
    "mesh_cell_m",
    "network_maps_from_run",
    "share_outside",
    "snap_settings",
)
