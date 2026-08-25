"""The static geometry of a stream-network comparison, and its partition.

Everything here follows from the topography and from the mapped network, never
from a calibrated parameter: the receiver graph, the linework projected onto the
cells, the catchment, the distance field, the reference length and the
saturation cap. A trial recomputes only the distance towards the network it just
simulated, which is one ``O(n_cells)`` pass. That asymmetry is what makes the
comparison affordable, and geometry does not move when ``K`` does.

It lives in ``core`` because four layers need the SAME construction: the
calibration criterion scores it, the results layer rebuilds it to draw a run
after the fact, and neither may import the other. Two derivations of one
partition is how a figure comes to disagree with the number it illustrates.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.core.depression_filling import fill_depressions_on_graph
from hydromodpy.core.field_routing import (
    accumulate_on_downhill_graph,
    active_surface_mask,
    cell_adjacency_from_face_connectivity,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.core.stream_network import (
    SimulatedNetwork,
    downstream_closure,
    specific_seepage_threshold,
)
from hydromodpy.core.topographic_distance import (
    DownslopeMetric,
    build_downslope_metric,
    downslope_distance_to_mask,
    longest_descent_length,
    shared_node_adjacency,
)

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
    cell_centroids: np.ndarray | None = None,
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

    ``cell_centroids`` are the points ``topography`` was sampled at. On a
    Voronoi dual that is the generator seed, not the polygon centroid the
    vertices give back, and routing on one while measuring the drop on the
    other builds the slope out of two different segments.
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
        centroids=cell_centroids,
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

    excluded_mask = (
        None if excluded is None else np.asarray(excluded, dtype=bool).reshape(-1) & active
    )

    # Open water is surface water: a seepage cell fifty metres from a bank stops
    # at the reservoir, it does not swim across it and carry on to the next
    # mapped reach. Water bodies therefore JOIN the target of both distance
    # fields, while leaving both supports, which the cost does on its own side.
    # They stay in the graph, so an upslope cell still descends through them.
    target = observed_mask if excluded_mask is None else (observed_mask | excluded_mask)
    distance_raw = downslope_distance_to_mask(metric, target)
    sealed = target.copy()
    sealed[outlet] = True
    distance_sealed = downslope_distance_to_mask(metric, sealed)

    closure = downstream_closure(metric, observed_mask)
    alpha = float(observed_mask.sum() / closure.sum()) if closure.any() else float("nan")
    # Measured on the MAPPED network alone even when water bodies joined the
    # target: the diagnostic answers "how much of the surface descends into the
    # linework", and a reservoir absorbing paths would flatter it.
    reach_from = (
        distance_raw if excluded_mask is None else downslope_distance_to_mask(metric, observed_mask)
    )
    reachable = float(np.mean(np.isfinite(reach_from[active]))) if active.any() else float("nan")
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
        saturation_cap_m=longest_descent_length(metric, outlet_mask, within=catchment),
        excluded=excluded_mask,
        alpha_obs_closure=alpha,
        frac_reachable_obs_raw=reachable,
    )


@dataclass(frozen=True, slots=True)
class CriterionSupports:
    """The masks the two distances are averaged over, and their three classes."""

    keep: np.ndarray
    """(n_cells,) bool: the catchment, active, minus the water bodies."""

    support_so: np.ndarray
    """(n_cells,) bool: the simulated network inside ``keep``, support of ``D_so``."""

    support_os: np.ndarray
    """(n_cells,) bool: the mapped network inside ``keep``, support of ``D_os``."""

    valid: np.ndarray
    """(n_cells,) bool: simulated where the map has a stream."""

    excess: np.ndarray
    """(n_cells,) bool: simulated where the map has none."""

    missing: np.ndarray
    """(n_cells,) bool: mapped where the model produces none."""

    seepage: np.ndarray
    """(n_cells,) bool: the sources inside ``keep``, before the downslope closure."""

    @property
    def counts(self) -> dict[str, float]:
        """The three class sizes, named as a trial publishes them."""
        return {
            "n_valid": float(int(self.valid.sum())),
            "n_excess": float(int(self.excess.sum())),
            "n_missing": float(int(self.missing.sum())),
        }


def criterion_supports(
    *,
    simulated: SimulatedNetwork,
    observed: np.ndarray,
    catchment: np.ndarray,
    active: np.ndarray,
    excluded: np.ndarray | None = None,
) -> CriterionSupports:
    """Intersect the criterion's masks into the partition it scores.

    ``excluded`` holds the cells whose surface-water extent is an input rather
    than an output. They leave both supports here and stay in the graph and in
    the target, which the geometry does on its own side: keeping them in the
    support of ``D_so`` would inject one zero per lake cell and move the root
    with the size of the reservoir rather than with the hydrogeology.
    """
    observed_mask = np.asarray(observed, dtype=bool).reshape(-1)
    keep = np.asarray(catchment, dtype=bool).reshape(-1) & np.asarray(active, dtype=bool).reshape(
        -1
    )
    if excluded is not None:
        keep = keep & ~np.asarray(excluded, dtype=bool).reshape(-1)

    support_so = simulated.network & keep
    support_os = observed_mask & keep
    return CriterionSupports(
        keep=keep,
        support_so=support_so,
        support_os=support_os,
        valid=support_so & observed_mask,
        excess=support_so & ~observed_mask,
        missing=support_os & ~simulated.network,
        seepage=simulated.seepage & keep,
    )


__all__ = (
    "CriterionSupports",
    "NetworkGeometry",
    "build_network_geometry",
    "criterion_supports",
    "reference_length",
    "resolve_outlet",
)
