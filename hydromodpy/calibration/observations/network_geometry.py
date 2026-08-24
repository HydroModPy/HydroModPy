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


def geometry_from_run(run_ctx: Any, output: CalibOutputNetwork) -> NetworkGeometry:
    """Build the static geometry from the model a trial just ran.

    Every attribute read here is named in the error it raises when missing, so
    a backend that does not expose one says which one rather than failing deep
    inside a numpy call.
    """
    from hydromodpy.calibration.observations.observed_network import (
        delineated_catchment_mask,
        observed_network_mask,
        water_body_mask,
    )

    model = run_ctx.state.execution.models_by_run_id.get(run_ctx.run.id)
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
    # The criterion routes on the TOPOGRAPHIC catchment, never on the model's
    # active domain: section 4.4 measures 0.03 to 2.5 per cent of unreachable
    # cells on the first against 10.5 to 14.4 on the second. Cutting the graph
    # on the model domain also breaks the catchment into pieces the flood
    # cannot cross, and the descent then stops at the domain boundary rather
    # than at a stream. The domain restricts what the SOLVER computes; the
    # supports are restricted by the catchment, below.
    inactive = ~np.isfinite(np.asarray(solver_mesh.top, dtype=float).reshape(-1))

    # The model top, conditioned on the mesh graph by build_network_geometry.
    # Sampling the raster the geographic step conditioned is NOT equivalent:
    # that surface is pit-free on its own grid, and reading it at mesh centroids
    # both grows new pits and drops the cells whose centroid falls on nodata.
    # Measured on the Nancon, the sampled route left 51.9 per cent of the
    # simulated support unreachable against 0.0 per cent for the flood on the
    # mesh graph itself.
    return build_network_geometry(
        topography=np.asarray(solver_mesh.top, dtype=float).reshape(-1),
        face_node_connectivity=connectivity,
        vertices=np.asarray(planar_mesh.vertices, dtype=float),
        observed=observed_network_mask(run_ctx, output, planar_mesh, connectivity),
        cell_area_m2=np.asarray(solver_mesh.cell_areas(), dtype=float).reshape(-1),
        # The centres MODFLOW 6 itself sees: on a Voronoi grid these are the
        # generator seeds written to the DISV file, which is where the mesh
        # sampled the top the criterion routes on.
        cell_centroids=np.asarray(solver_mesh.cell_centroids(), dtype=float),
        mean_recharge_m_s=mean_recharge_m_s(model),
        tau_specific_ratio=float(output.tau_specific_ratio),
        inactive_mask=inactive,
        excluded=water_body_mask(model, n_cells=int(solver_mesh.n_cells)),
        delineated_catchment=delineated_catchment_mask(run_ctx, planar_mesh, connectivity),
        diagonal_neighbors=bool(output.diagonal_neighbors),
        observed_position_accuracy_m=_accuracy_in_m(output),
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
    "dense_face_connectivity",
    "geometry_from_run",
    "mean_recharge_m_s",
)
