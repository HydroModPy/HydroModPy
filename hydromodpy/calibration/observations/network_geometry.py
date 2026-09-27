"""The bridge between one run and the static geometry of its stream criterion.

The construction itself lives in :mod:`hydromodpy.core.stream_geometry`, so the
criterion and the results layer that redraws a run afterwards share one
derivation. What is left here is what only a calibration knows: which model a
trial produced, what recharge it received, and where its mapped network was
declared.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.core.stream_geometry import NetworkGeometry, build_network_geometry

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


def cell_spacing_m(
    cell_centroids: np.ndarray,
    face_node_connectivity: np.ndarray,
    *,
    within: np.ndarray | None = None,
) -> float:
    """Return the size of one mesh cell: the median distance between neighbouring centres.

    Two cells are neighbours when they share an edge, whatever the descent the
    criterion routes on. ``within`` keeps the pairs whose two cells both lie in
    it, the catchment the criterion scores, so the buffer cells of a refined
    mesh do not set the size. A stream cannot move by less than one cell, which
    is why this is the default width of an interval read on network distances.
    ``reference_length`` (square root of the median cell area) normalises the
    validity ratio; the width uses the centre spacing because a stream moves
    from one cell centre to the next. The two agree on a square grid.
    """
    centres = np.asarray(cell_centroids, dtype=float)
    rows = np.asarray(face_node_connectivity, dtype=np.int64)
    if rows.ndim == 1:
        rows = rows.reshape(1, -1)
    rows = rows[: centres.shape[0]]
    present = rows >= 0
    # Nodes of each face moved to the front in ring order, so the node after
    # slot j is slot (j + 1) modulo the face arity.
    ring = np.take_along_axis(rows, np.argsort(~present, axis=1, kind="stable"), axis=1)
    arity = present.sum(axis=1)
    slots = np.arange(rows.shape[1])
    following = np.take_along_axis(
        ring, np.mod(slots[None, :] + 1, np.maximum(arity, 1)[:, None]), axis=1
    )
    drawn = (slots[None, :] < arity[:, None]) & (ring != following)
    low = np.minimum(ring, following)[drawn]
    high = np.maximum(ring, following)[drawn]
    owner = np.broadcast_to(np.arange(rows.shape[0])[:, None], rows.shape)[drawn]
    key = low * (int(rows.max(initial=0)) + 1) + high
    order = np.argsort(key, kind="stable")
    key, owner = key[order], owner[order]
    shared = key[1:] == key[:-1]
    first, second = owner[:-1][shared], owner[1:][shared]
    keep = first != second
    if within is not None:
        inside = np.asarray(within, dtype=bool).reshape(-1)
        keep &= inside[first] & inside[second]
    delta = centres[first[keep]] - centres[second[keep]]
    distances = np.hypot(delta[:, 0], delta[:, 1])
    distances = distances[np.isfinite(distances)]
    if distances.size == 0:
        raise ValueError("the mesh holds no two neighbouring cells to measure a cell on.")
    return float(np.median(distances))


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

    Read on what :func:`geometry_from_run` already holds: the cell centres the
    geometry routes on, the connectivity of the same solver mesh, and the
    catchment it scores. Nothing else of the solver is asked.
    """
    planar_mesh = run_ctx.model.solver_mesh.planar_mesh
    return cell_spacing_m(
        geometry.metric.centroids,
        dense_face_connectivity(planar_mesh),
        within=geometry.catchment,
    )


def geometry_from_run(
    run_ctx: RunContext, output: CalibOutputNetwork
) -> tuple[NetworkGeometry, ObservedNetwork, ObservedNetworkMask]:
    """Build the static geometry from the model a trial just ran.

    The observed network is resolved exactly ONCE here, from whichever of the
    three sources the output declares, and threaded into the mask projection:
    neither this function nor its caller re-resolves it. The resolution is
    returned alongside the geometry because its provenance (clipped,
    DEM-derived) is a trial diagnostic that ``NetworkGeometry`` itself does not
    carry. The projection is returned for the same reason: how many cells the
    output's ``observed_rasterization`` drew, and how many reaches it kept at
    their midpoint cell.

    Every attribute read here is named in the error it raises when missing, so
    a backend that does not expose one says which one rather than failing deep
    inside a numpy call.
    """
    from hydromodpy.calibration.observations.network_source import resolve_observed_network
    from hydromodpy.calibration.observations.observed_network import (
        delineated_catchment_mask,
        delineated_outlet_xy,
        observed_network_mask,
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
    # Resolved once per trial. Neither the mask projection below nor the
    # caller in metrics/solver_extract.py re-resolves it.
    resolved = resolve_observed_network(run_ctx, output)
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

    # The model top, conditioned on the mesh graph by build_network_geometry.
    # Sampling the raster the geographic step conditioned is NOT equivalent:
    # that surface is pit-free on its own grid, and reading it at mesh centroids
    # both grows new pits and drops the cells whose centroid falls on nodata.
    # Measured on the Nancon, the sampled route left 51.9 per cent of the
    # simulated support unreachable against 0.0 per cent for the flood on the
    # mesh graph itself. The raster polygon and the snapped outlet only place
    # the outlet on that graph; the catchment is read there.
    geometry = build_network_geometry(
        topography=np.asarray(solver_mesh.top, dtype=float).reshape(-1),
        face_node_connectivity=connectivity,
        vertices=np.asarray(planar_mesh.vertices, dtype=float),
        observed=projection.mask,
        cell_area_m2=np.asarray(solver_mesh.cell_areas(), dtype=float).reshape(-1),
        cell_centroids=centres,
        mean_recharge_m_s=mean_recharge_m_s(model),
        tau_specific_ratio=float(output.tau_specific_ratio),
        inactive_mask=inactive,
        excluded=water_body_mask(model, n_cells=int(solver_mesh.n_cells)),
        delineated_catchment=delineated_catchment_mask(run_ctx, planar_mesh, connectivity),
        delineated_outlet_xy=delineated_outlet_xy(run_ctx),
        diagonal_neighbors=bool(output.diagonal_neighbors),
        observed_position_accuracy_m=_accuracy_in_m(output),
        alpha_warning_threshold=float(output.alpha_warning_threshold),
        clipping_warning_share=float(output.clipping_warning_share),
        clipping_warning_gap=float(output.clipping_warning_gap),
    )
    return geometry, resolved, projection


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
    "aquifer_extent",
    "cell_spacing_m",
    "dense_face_connectivity",
    "geometry_from_run",
    "mean_recharge_m_s",
    "mesh_cell_m",
)
