"""The static half of the network criterion, built once per project.

Nothing here depends on a calibrated parameter: the receiver graph, the mapped
network projected onto the mesh, the catchment, the distance field towards the
mapped network, the reference length and the saturation cap all follow from the
topography and from the data. A trial recomputes only the distance towards the
network it just simulated, which is one ``O(n_cells)`` pass.

That asymmetry is what makes the criterion affordable: the expensive half is
geometry, and geometry does not move when ``K`` does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.calibration.observations.simulated_network import (
    downstream_closure,
    specific_seepage_threshold,
)
from hydromodpy.core.field_routing import accumulate_on_downhill_graph, active_surface_mask
from hydromodpy.core.logging import get_logger
from hydromodpy.core.topographic_distance import (
    DownslopeMetric,
    build_downslope_metric,
    downslope_distance_to_mask,
    longest_descent_length,
)

if TYPE_CHECKING:
    from hydromodpy.calibration.config import CalibOutputNetwork

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class NetworkGeometry:
    """Everything the cost needs that does not change from trial to trial."""

    metric: DownslopeMetric
    observed: np.ndarray
    outlet: int
    catchment: np.ndarray
    distance_to_observed: np.ndarray
    distance_to_observed_raw: np.ndarray
    cell_area_m2: np.ndarray
    threshold_m3_s: np.ndarray
    length_scale_m: float
    saturation_cap_m: float
    excluded: np.ndarray | None
    alpha_obs_closure: float
    frac_reachable_obs_raw: float

    @property
    def diagnostics(self) -> dict[str, float]:
        """The three numbers that qualify the data rather than the trial."""
        return {
            "alpha_obs_closure": self.alpha_obs_closure,
            "frac_reachable_obs_raw": self.frac_reachable_obs_raw,
            "n_outlet_sealed": float(0.0 if self.observed[self.outlet] else 1.0),
        }


def reference_length(cell_area_m2: np.ndarray, support: np.ndarray) -> float:
    """Return ``L_ref``, the square root of the MEDIAN cell area.

    The median, not the mean: on a mesh refined along the streams a handful of
    large buffer cells inflate the mean, and the two conventions differ enough
    to move the validity ratio across its bound for a size ratio of three. The
    same convention is already used elsewhere in the package, so there is one
    definition of a cell size in the repository and not two.
    """
    areas = np.asarray(cell_area_m2, dtype=float).reshape(-1)
    kept = areas[np.asarray(support, dtype=bool).reshape(-1) & np.isfinite(areas)]
    if kept.size == 0:
        raise ValueError("the support holds no cell with a finite area.")
    return float(np.sqrt(np.median(kept)))


def resolve_outlet(metric: DownslopeMetric) -> int:
    """Return the cell every path ends in: the largest drained area.

    The outlet is not a product of the DEM, it is the closing point of the
    catchment, usually the gauging station. Writing that it belongs to the
    stream network is true by definition, which is what makes sealing it into
    the target legitimate rather than a fudge.
    """
    active = metric.graph.active
    accumulated = accumulate_on_downhill_graph(metric.graph, np.ones(active.size))
    scored = np.where(active & np.isfinite(accumulated), accumulated, -np.inf)
    if not np.any(np.isfinite(scored)):
        raise ValueError("the mesh holds no active cell to close the catchment on.")
    return int(np.argmax(scored))


def build_network_geometry(
    *,
    topography: np.ndarray,
    face_node_connectivity: np.ndarray,
    vertices: np.ndarray,
    observed: np.ndarray,
    cell_area_m2: np.ndarray,
    mean_recharge_m_s: float,
    tau_specific_ratio: float,
    inactive_mask: np.ndarray | None = None,
    excluded: np.ndarray | None = None,
    diagonal_neighbors: bool = False,
    observed_position_accuracy_m: float | None = None,
) -> NetworkGeometry:
    """Assemble the static geometry of the criterion from mesh primitives.

    ``excluded`` holds the cells whose surface-water extent is an input rather
    than an output: a lake, an ocean-role boundary, a mapped wetland. They stay
    in the graph and in the target, and only leave the two supports.
    """
    surface = np.asarray(topography, dtype=float).reshape(-1)
    inactive = (
        ~active_surface_mask(surface)
        if inactive_mask is None
        else np.asarray(inactive_mask, dtype=bool).reshape(-1)
    )
    metric = build_downslope_metric(
        surface,
        face_node_connectivity,
        vertices=vertices,
        inactive_mask=inactive,
        diagonal_neighbors=diagonal_neighbors,
    )
    active = metric.graph.active

    observed_mask = np.asarray(observed, dtype=bool).reshape(-1) & active
    if not np.any(observed_mask):
        raise ValueError(
            "the mapped stream network projects onto no active cell: check its geometry "
            "and that both its CRS and the mesh CRS are declared."
        )

    outlet = resolve_outlet(metric)
    outlet_mask = np.zeros(active.size, dtype=bool)
    outlet_mask[outlet] = True
    catchment = np.isfinite(downslope_distance_to_mask(metric, outlet_mask)) & active

    distance_raw = downslope_distance_to_mask(metric, observed_mask)
    sealed = observed_mask.copy()
    sealed[outlet] = True
    distance_sealed = downslope_distance_to_mask(metric, sealed)

    closure = downstream_closure(metric, observed_mask)
    alpha = float(observed_mask.sum() / closure.sum()) if closure.any() else float("nan")
    reachable = float(np.mean(np.isfinite(distance_raw[active]))) if active.any() else float("nan")
    if np.isfinite(alpha) and alpha < 0.90:
        logger.warning(
            "The mapped stream network agrees poorly with the routing surface: "
            "alpha_obs_closure = %.3f. Below 0.90 a large share of the D8 trace leaving "
            "the mapped cells falls outside the network, so the distances measure a "
            "DEM-versus-network disagreement rather than hydrogeology. Burn the network "
            "into the routing DEM before calibrating.",
            alpha,
        )

    areas = np.asarray(cell_area_m2, dtype=float).reshape(-1)
    length_scale = reference_length(areas, catchment)
    if observed_position_accuracy_m:
        # The error floor is set by the positional accuracy of the mapped
        # network, which does not depend on the model resolution: a finer mesh
        # divides the denominator without improving the agreement.
        length_scale = max(length_scale, float(observed_position_accuracy_m))

    return NetworkGeometry(
        metric=metric,
        observed=observed_mask,
        outlet=outlet,
        catchment=catchment,
        distance_to_observed=distance_sealed,
        distance_to_observed_raw=distance_raw,
        cell_area_m2=areas,
        threshold_m3_s=specific_seepage_threshold(
            areas, mean_recharge_m_s, ratio=tau_specific_ratio
        ),
        length_scale_m=length_scale,
        saturation_cap_m=longest_descent_length(metric, outlet_mask),
        excluded=None if excluded is None else np.asarray(excluded, dtype=bool).reshape(-1),
        alpha_obs_closure=alpha,
        frac_reachable_obs_raw=reachable,
    )


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
    planar_mesh = solver_mesh.planar_mesh
    connectivity = dense_face_connectivity(planar_mesh)
    inactive = np.asarray(solver_mesh.inactive_mask, dtype=bool)[0]

    return build_network_geometry(
        topography=np.asarray(solver_mesh.top, dtype=float).reshape(-1),
        face_node_connectivity=connectivity,
        vertices=np.asarray(planar_mesh.vertices, dtype=float),
        observed=observed_network_mask(run_ctx, output, planar_mesh, connectivity),
        cell_area_m2=np.asarray(solver_mesh.cell_areas(), dtype=float).reshape(-1),
        mean_recharge_m_s=mean_recharge_m_s(model),
        tau_specific_ratio=float(output.tau_specific_ratio),
        inactive_mask=inactive,
        excluded=water_body_mask(model, n_cells=int(solver_mesh.n_cells)),
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
    "NetworkGeometry",
    "build_network_geometry",
    "dense_face_connectivity",
    "geometry_from_run",
    "mean_recharge_m_s",
    "reference_length",
    "resolve_outlet",
)
