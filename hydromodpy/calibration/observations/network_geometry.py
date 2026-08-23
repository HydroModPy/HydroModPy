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
from hydromodpy.core.depression_filling import fill_depressions_on_graph
from hydromodpy.core.field_routing import (
    accumulate_on_downhill_graph,
    active_surface_mask,
    cell_adjacency_from_face_connectivity,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.core.topographic_distance import (
    DownslopeMetric,
    build_downslope_metric,
    downslope_distance_to_mask,
    longest_descent_length,
    shared_node_adjacency,
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
    mean_recharge_m_s: float
    length_scale_m: float
    saturation_cap_m: float
    excluded: np.ndarray | None
    alpha_obs_closure: float
    frac_reachable_obs_raw: float

    @property
    def diagnostics(self) -> dict[str, float]:
        """The numbers that qualify the data rather than the trial.

        ``R_mean_m_s`` is the denominator of the calibrated ratio: the criterion
        fits ``K/R``, so a per-trial record of ``R`` is what makes a recharge
        moving mid-session readable in ``trials.jsonl`` afterwards.
        """
        return {
            "alpha_obs_closure": self.alpha_obs_closure,
            "frac_reachable_obs_raw": self.frac_reachable_obs_raw,
            "n_outlet_sealed": float(0.0 if self.observed[self.outlet] else 1.0),
            "R_mean_m_s": self.mean_recharge_m_s,
        }


_last_mean_recharge: float | None = None


def _warn_if_recharge_moved(recharge: float) -> None:
    """Warn when the recharge changes between two geometries of one process.

    The criterion fits ``K/R``, so a recharge that moves between two trials
    changes the calibrated quantity while every declared parameter looks
    unchanged. Warning rather than refusing: this module knows a mesh, not a
    session, and two consecutive builds can legitimately belong to two
    projects; a refusal would abort those, while the ``R_mean_m_s`` diagnostic
    already records the value per trial and the warning only makes the move
    visible while it happens.
    """
    global _last_mean_recharge
    previous, _last_mean_recharge = _last_mean_recharge, recharge
    if previous is None or previous == recharge:
        return
    logger.warning(
        "The mean recharge moved between two network criterion builds: %r then %r m/s. "
        "The criterion calibrates the ratio K/R, so a bound of one per cent holds on the "
        "conductivity only while R stays put. Freeze the recharge for the whole session, "
        "or read R_mean_m_s per trial before reading the calibrated value as a K.",
        previous,
        recharge,
    )


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


def resolve_outlet(metric: DownslopeMetric, *, within: np.ndarray | None = None) -> int:
    """Return the cell every path ends in: the largest drained area.

    The outlet is not a product of the DEM, it is the closing point of the
    catchment, usually the gauging station. Writing that it belongs to the
    stream network is true by definition, which is what makes sealing it into
    the target legitimate rather than a fudge.

    ``within`` restricts the search to a catchment. Without it the accumulation
    is read over the whole mesh, and on an unconditioned surface the maximum
    sits in the largest internal depression rather than at the gauge.
    """
    active = metric.graph.active
    if within is not None:
        active = active & np.asarray(within, dtype=bool).reshape(-1)
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
    delineated_catchment: np.ndarray | None = None,
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
    fill_report = None
    catchment_outlet: int | None = None
    if delineated_catchment is None:
        # Never silent: without the delineated catchment the criterion falls back
        # to descending the raw model top to its own largest basin, which on a
        # real surface is an internal depression holding a few per cent of the
        # mesh. A synthetic domain legitimately has no watershed; a real run that
        # lost it (a concurrent run cleaning the preparation directory, for one)
        # produces a plausible number from the wrong support.
        logger.warning(
            "Network criterion: no delineated catchment for this run. Falling back to "
            "the largest basin of the raw model top, whose depressions are not "
            "resolved. Check that the geographic step ran and that its preparation "
            "directory was not removed while the trial was scoring."
        )
    if delineated_catchment is not None:
        # Condition the surface ON THIS GRAPH before measuring lengths along it.
        # A raster conditioned before delineation is pit-free on its own grid
        # only; sampled onto the mesh it grows new pits, and the descent then
        # stops in depressions that do not exist hydrologically. Measured on the
        # Nancon: 13.6 per cent of the seepage support never reached its target
        # before the flood, 0.0 per cent after, and the outlet moved from an
        # internal depression at 130.3 m to the true low point at 106.4 m.
        catchment_seed = np.asarray(delineated_catchment, dtype=bool).reshape(-1)
        candidates = np.where(catchment_seed & ~inactive, surface, np.inf)
        # The flood and the criterion must seal the SAME cell. After the flood
        # every path in the catchment ends at this one by construction, so
        # resolving a different outlet afterwards leaves the cells that drain
        # here unable to reach the sealed target.
        catchment_outlet = int(np.argmin(candidates))
        outlets = np.zeros(surface.size, dtype=bool)
        outlets[catchment_outlet] = True
        # THE SAME neighbour graph the metric will descend. The flood only
        # guarantees a strictly lower neighbour among the cells it walked: fed
        # the eight-neighbour graph while the metric reads the four-neighbour
        # one, it leaves every filled cell spilling over a diagonal the metric
        # cannot take, and 99.8 per cent of the catchment stops reaching the
        # outlet instead of 0.
        adjacency = (
            shared_node_adjacency(face_node_connectivity, n_cells=surface.size)
            if diagonal_neighbors
            else cell_adjacency_from_face_connectivity(face_node_connectivity, n_cells=surface.size)
        )
        fill_report = fill_depressions_on_graph(
            np.where(inactive, np.nan, surface), adjacency, outlets
        )
        surface = fill_report.surface
        logger.info(
            "Network criterion: %d cell(s) raised to close the depressions of the "
            "surface it measures on, up to %.2f m.",
            fill_report.n_filled,
            fill_report.max_fill,
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

    if delineated_catchment is not None:
        # The catchment the geographic pipeline closed on the declared gauge,
        # delineated on the conditioned routing surface. The model top is never
        # conditioned, so descending it to its own largest basin picks an
        # internal depression instead: measured on the Nancon, 2.3 per cent of
        # the mesh and not one cell of the mapped network.
        catchment = np.asarray(delineated_catchment, dtype=bool).reshape(-1) & active
        if not np.any(catchment):
            raise ValueError(
                "the delineated catchment projects onto no active cell of the mesh: "
                "check the CRS of the watershed the geographic step wrote."
            )
        outlet = catchment_outlet
    else:
        outlet = resolve_outlet(metric)
        seed = np.zeros(active.size, dtype=bool)
        seed[outlet] = True
        catchment = np.isfinite(downslope_distance_to_mask(metric, seed)) & active

    outlet_mask = np.zeros(active.size, dtype=bool)
    outlet_mask[outlet] = True

    if fill_report is not None:
        # After the flood every catchment cell must reach the sealed outlet.
        # Anything else means the surface the flood conditioned is not the one
        # the metric descends.
        to_outlet = downslope_distance_to_mask(metric, outlet_mask)
        stranded = float(np.mean(~np.isfinite(to_outlet[catchment])))
        logger.info(
            "Network criterion: %.2f%% of the catchment does not reach the sealed outlet "
            "after conditioning.",
            100.0 * stranded,
        )

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

    recharge = float(mean_recharge_m_s)
    _warn_if_recharge_moved(recharge)

    return NetworkGeometry(
        metric=metric,
        observed=observed_mask,
        outlet=outlet,
        catchment=catchment,
        distance_to_observed=distance_sealed,
        distance_to_observed_raw=distance_raw,
        cell_area_m2=areas,
        threshold_m3_s=specific_seepage_threshold(areas, recharge, ratio=tau_specific_ratio),
        mean_recharge_m_s=recharge,
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
    "NetworkGeometry",
    "build_network_geometry",
    "dense_face_connectivity",
    "geometry_from_run",
    "mean_recharge_m_s",
    "reference_length",
    "resolve_outlet",
)
