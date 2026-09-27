"""The static geometry of a stream-network comparison, and its partition.

Everything here follows from the topography and from the mapped network, never
from a calibrated parameter: the receiver graph, the linework projected onto the
cells, the catchment, the distance field, the reference length and the
saturation cap. A trial recomputes only the distance towards the network it just
simulated, which is one ``O(n_cells)`` pass. That asymmetry is what makes the
comparison affordable, and geometry does not move when ``K`` does.

One surface carries all of it. The model top is conditioned on the mesh graph
by a priority flood seeded on the border of the active domain, the standard
form of Barnes et al. (2014). The outlet and the scored catchment are read on
that same graph: the catchment is every cell whose descent reaches the outlet.
The raster polygon of the geographic step only builds the domain and places
the outlet, and its gap to the graph catchment is published.

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
    domain_edge_cells,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.core.stream_criterion_defaults import STREAM_CRITERION_DEFAULTS
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
    resolve_diagonal_neighbors,
    shared_node_adjacency,
)

logger = get_logger(__name__)

#: Rings of neighbours the delineated outlet may move across to reach the most
#: accumulated cell of the criterion graph. Two cells is the ``SnapPourPoints``
#: distance of the paper (twice the resolution): on a quad mesh descended D8
#: the two rings are its five-by-five window.
OUTLET_SNAP_RINGS = 2

#: Share of the delineated polygon's area the graph catchment may differ by
#: before the gap is logged as a warning. It decides what is LOGGED only.
CATCHMENT_MISMATCH_WARNING_SHARE = 0.05


@dataclass(frozen=True, slots=True)
class NetworkGeometry:
    """Everything the cost needs that does not change from trial to trial.

    ``catchment`` is the scored support: the cells whose descent on the
    conditioned graph reaches ``outlet``. ``catchment_mismatch`` is the area of
    the symmetric difference between it and the delineated raster polygon,
    divided by the polygon's area; NaN when no polygon was given.
    """

    metric: DownslopeMetric
    observed: np.ndarray
    outlet: int
    catchment: np.ndarray
    catchment_mismatch: float
    distance_to_observed: np.ndarray
    distance_to_observed_raw: np.ndarray
    cell_area_m2: np.ndarray
    threshold_m3_s: np.ndarray
    mean_recharge_m_s: float
    length_scale_m: float
    saturation_cap_m: float
    excluded: np.ndarray | None
    alpha_obs_closure: float
    alpha_obs_closure_catchment: float
    frac_obs_outside_catchment: float
    frac_reachable_obs_raw: float

    @property
    def diagnostics(self) -> dict[str, float]:
        """The numbers that qualify the data rather than the trial.

        ``R_mean_m_s`` is the denominator of the calibrated ratio: the criterion
        fits ``K/R``, so a per-trial record of ``R`` is what makes a recharge
        moving mid-session readable in ``trials.jsonl`` afterwards.

        ``alpha_obs_closure`` and ``alpha_obs_closure_catchment`` are the same
        ratio on two supports, the whole mesh and the scored catchment. They
        part company exactly when the mapped linework is wider than the
        catchment, which ``frac_obs_outside_catchment`` says outright, so the
        gap between them is attributable rather than mysterious.

        ``catchment_mismatch`` says how far the scored catchment, read on the
        criterion graph, sits from the polygon the geographic step delineated
        on its raster.
        """
        return {
            "alpha_obs_closure": self.alpha_obs_closure,
            "alpha_obs_closure_catchment": self.alpha_obs_closure_catchment,
            "frac_obs_outside_catchment": self.frac_obs_outside_catchment,
            "frac_reachable_obs_raw": self.frac_reachable_obs_raw,
            "catchment_mismatch": self.catchment_mismatch,
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
    same convention is already used elsewhere in the package to normalise a
    length. The interval width of a calibration reads another size, the median
    distance between the centres of neighbouring cells (``cell_spacing_m``),
    because a stream moves from one cell centre to the next. The two agree on
    a square grid.
    """
    areas = np.asarray(cell_area_m2, dtype=float).reshape(-1)
    kept = areas[np.asarray(support, dtype=bool).reshape(-1) & np.isfinite(areas)]
    if kept.size == 0:
        raise ValueError("the support holds no cell with a finite area.")
    return float(np.sqrt(np.median(kept)))


def _rings_around(start: int, adjacency: list[set[int]], rings: int) -> np.ndarray:
    """Return ``start`` and every cell at most ``rings`` neighbour steps from it."""
    reached = {int(start)}
    frontier = {int(start)}
    for _ in range(int(rings)):
        frontier = {int(n) for cell in frontier for n in adjacency[cell]} - reached
        reached |= frontier
    return np.fromiter(sorted(reached), dtype=int)


def resolve_outlet(
    metric: DownslopeMetric,
    *,
    within: np.ndarray | None = None,
    near: tuple[float, float] | None = None,
    adjacency: list[set[int]] | None = None,
    rings: int = OUTLET_SNAP_RINGS,
    cell_area_m2: np.ndarray | None = None,
) -> int:
    """Return the closing cell of the catchment: the largest drained area.

    The outlet is not a product of the DEM, it is the closing point of the
    catchment, usually the gauging station. Writing that it belongs to the
    stream network is true by definition, which is what makes sealing it into
    the target legitimate rather than a fudge.

    ``near`` is the outlet the geographic step delineated from, in the mesh
    CRS. The search then starts at the active cell whose centre is nearest to
    it and keeps the most accumulated cell within ``rings`` neighbour steps on
    ``adjacency``, the graph the metric descends: the ``SnapPourPoints`` rule
    of the paper, read on the mesh. Without ``near``, ``within`` restricts the
    search to a catchment; without either, the largest basin of the mesh wins.

    ``cell_area_m2`` weighs the accumulation into a drained area, which a mesh
    of unequal cells needs; the cell count is used without it.
    """
    graph = metric.graph
    active = graph.active
    weights = (
        np.ones(active.size)
        if cell_area_m2 is None
        else np.asarray(cell_area_m2, dtype=float).reshape(-1)
    )
    accumulated = accumulate_on_downhill_graph(graph, weights)
    candidates = active & np.isfinite(accumulated)
    if not np.any(candidates):
        raise ValueError("the mesh holds no active cell to close the catchment on.")
    if near is not None:
        if adjacency is None:
            raise ValueError("snapping the outlet needs the adjacency the metric descends.")
        point = np.asarray(near, dtype=float).reshape(2)
        offset = metric.centroids - point[None, :]
        gap = np.where(candidates, np.hypot(offset[:, 0], offset[:, 1]), np.inf)
        window = np.zeros(active.size, dtype=bool)
        window[_rings_around(int(np.argmin(gap)), adjacency, rings)] = True
        candidates &= window
    elif within is not None:
        candidates &= np.asarray(within, dtype=bool).reshape(-1)
        if not np.any(candidates):
            raise ValueError("the catchment holds no active cell to close on.")
    scored = np.where(candidates, accumulated, -np.inf)
    return int(np.argmax(scored))


def _catchment_mismatch(
    polygon: np.ndarray | None, catchment: np.ndarray, areas: np.ndarray
) -> float:
    """Return ``area(polygon XOR catchment) / area(polygon)``, NaN without a polygon."""
    if polygon is None:
        return float("nan")
    weights = np.where(np.isfinite(areas), areas, 0.0)
    polygon_area = float(weights[polygon].sum())
    if polygon_area <= 0.0:
        return float("nan")
    return float(weights[polygon ^ catchment].sum()) / polygon_area


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
    delineated_outlet_xy: tuple[float, float] | None = None,
    diagonal_neighbors: bool = STREAM_CRITERION_DEFAULTS.diagonal_neighbors,
    observed_position_accuracy_m: float | None = None,
    alpha_warning_threshold: float = STREAM_CRITERION_DEFAULTS.alpha_warning_threshold,
    clipping_warning_share: float = STREAM_CRITERION_DEFAULTS.clipping_warning_share,
    clipping_warning_gap: float = STREAM_CRITERION_DEFAULTS.clipping_warning_gap,
    catchment_mismatch_warning_share: float = CATCHMENT_MISMATCH_WARNING_SHARE,
) -> NetworkGeometry:
    """Assemble the static geometry of the criterion from mesh primitives.

    The surface, the outlet and the catchment all come from one graph: the
    model top conditioned by a priority flood seeded on the border of the
    active domain. ``delineated_outlet_xy`` is the outlet the geographic step
    delineated from (its snapped pour point, in the mesh CRS); the outlet is
    the most accumulated cell within :data:`OUTLET_SNAP_RINGS` of it. Without
    it, the most accumulated cell of ``delineated_catchment`` closes the
    catchment, and without either the largest basin of the mesh does. The
    catchment scored is every cell whose descent reaches that outlet.
    ``delineated_catchment``, the raster polygon projected on the cells, is
    only compared to it: ``catchment_mismatch`` publishes the gap, and a gap
    above ``catchment_mismatch_warning_share`` is logged as a warning.

    ``excluded`` holds the cells whose surface-water extent is an input rather
    than an output: a lake, an ocean-role boundary, a mapped wetland. They stay
    in the graph and in the target, and only leave the two supports.

    ``cell_centroids`` are the points ``topography`` was sampled at. On a
    Voronoi dual that is the generator seed, not the polygon centroid the
    vertices give back, and routing on one while measuring the drop on the
    other builds the slope out of two different segments.

    The three thresholds decide only what is LOGGED, never what is computed:
    ``alpha_warning_threshold`` is the agreement below which the distances are
    said to carry a top-versus-map disagreement, and the two ``clipping_``
    values are the share of mapped cells outside the catchment and the gap
    between the two ratios above which that clipping is worth reporting. Their
    defaults come from :data:`STREAM_CRITERION_DEFAULTS`, the one Pydantic
    object the calibration output and the redrawn figures also read, so a
    threshold is never written twice.

    ``diagonal_neighbors`` defaults to the D8 descent of the paper. It is
    resolved against the mesh once, here, and the one neighbour graph that
    comes out feeds the depression flood, the receiver graph, the downstream
    closure of both networks and the saturation cap alike.
    """
    surface = np.asarray(topography, dtype=float).reshape(-1)
    diagonal_neighbors = resolve_diagonal_neighbors(
        face_node_connectivity, n_cells=surface.size, requested=bool(diagonal_neighbors)
    )
    inactive = (
        ~active_surface_mask(surface)
        if inactive_mask is None
        else np.asarray(inactive_mask, dtype=bool).reshape(-1)
    )
    # THE SAME neighbour graph the metric will descend. The flood only
    # guarantees a strictly lower neighbour among the cells it walked: fed the
    # eight-neighbour graph while the metric reads the four-neighbour one, it
    # leaves every filled cell spilling over a diagonal the metric cannot take,
    # and 99.8 per cent of the catchment stops reaching the outlet instead of 0.
    adjacency = (
        shared_node_adjacency(face_node_connectivity, n_cells=surface.size)
        if diagonal_neighbors
        else cell_adjacency_from_face_connectivity(face_node_connectivity, n_cells=surface.size)
    )
    # Condition the surface ON THIS GRAPH before measuring lengths along it. A
    # raster conditioned before delineation is pit-free on its own grid only;
    # sampled onto the mesh it grows new pits, and the descent then stops in
    # depressions that do not exist hydrologically (13.6 per cent of the
    # seepage support on the Nancon before any flood).
    #
    # The flood is seeded on the border of the active domain, where water
    # leaves the model, and not on the catchment outlet alone. Sealing one
    # outlet declares the whole domain endorheic towards it: a buffer valley
    # draining off the domain is filled up to a col of the divide, and its
    # seepage then crosses into the catchment down hillslopes that do not
    # seep. Measured on the Nancon proxy: +16 per cent of network cells near
    # the root, and the root shifted by 24 per cent.
    edges = domain_edge_cells(face_node_connectivity, ~inactive & np.isfinite(surface))
    if not np.any(edges):
        raise ValueError("the mesh holds no active cell to condition the criterion surface on.")
    fill_report = fill_depressions_on_graph(np.where(inactive, np.nan, surface), adjacency, edges)
    logger.info(
        "Network criterion: %d cell(s) raised so every cell drains to the domain border, "
        "up to %.2f m.",
        fill_report.n_filled,
        fill_report.max_fill,
    )

    metric = build_downslope_metric(
        fill_report.surface,
        face_node_connectivity,
        vertices=vertices,
        centroids=cell_centroids,
        inactive_mask=inactive,
        diagonal_neighbors=diagonal_neighbors,
        adjacency=adjacency,
    )
    active = metric.graph.active

    observed_mask = np.asarray(observed, dtype=bool).reshape(-1) & active
    if not np.any(observed_mask):
        raise ValueError(
            "the mapped stream network projects onto no active cell: check its geometry "
            "and that both its CRS and the mesh CRS are declared."
        )

    polygon: np.ndarray | None = None
    if delineated_catchment is not None:
        polygon = np.asarray(delineated_catchment, dtype=bool).reshape(-1) & active
        if not np.any(polygon):
            raise ValueError(
                "the delineated catchment projects onto no active cell of the mesh: "
                "check the CRS of the watershed the geographic step wrote."
            )
    elif delineated_outlet_xy is None:
        # Never silent. A synthetic domain legitimately has no watershed; a real
        # run that lost it (a concurrent run cleaning the preparation
        # directory, for one) closes on the largest basin of its domain, which
        # need not be the gauged one, and produces a plausible number from the
        # wrong support.
        logger.warning(
            "Network criterion: no delineated catchment and no outlet for this run. "
            "Closing on the largest basin of the conditioned model top instead. Check "
            "that the geographic step ran and that its preparation directory was not "
            "removed while the trial was scoring."
        )

    areas = np.asarray(cell_area_m2, dtype=float).reshape(-1)
    outlet = resolve_outlet(
        metric,
        within=polygon,
        near=delineated_outlet_xy,
        adjacency=adjacency,
        cell_area_m2=np.where(np.isfinite(areas), areas, 0.0),
    )
    outlet_mask = np.zeros(active.size, dtype=bool)
    outlet_mask[outlet] = True
    # The scored catchment is closed upstream on the graph the distances use:
    # no descent from outside enters it, and every cell of it reaches the
    # outlet without being raised towards it.
    catchment = np.isfinite(downslope_distance_to_mask(metric, outlet_mask)) & active
    mismatch = _catchment_mismatch(polygon, catchment, areas)
    if np.isfinite(mismatch) and mismatch > float(catchment_mismatch_warning_share):
        logger.warning(
            "Network criterion: the catchment read on the criterion graph differs from the "
            "delineated polygon by %.1f%% of its area (%d cells against %d). The criterion "
            "scores the graph catchment. A large gap usually means an outlet placed on "
            "another branch, or a mesh much coarser than the DEM the polygon came from.",
            100.0 * mismatch,
            int(catchment.sum()),
            int(polygon.sum()) if polygon is not None else 0,
        )
    else:
        logger.info(
            "Network criterion: graph catchment of %d cell(s) closed on cell %d; gap to the "
            "delineated polygon %.2f%% of its area.",
            int(catchment.sum()),
            outlet,
            100.0 * mismatch if np.isfinite(mismatch) else float("nan"),
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
    # The same ratio on the support the criterion actually scores. A mapped
    # linework wider than the catchment drags the whole-mesh ratio for a reason
    # that is not an agreement defect: outside the catchment the mesh is a
    # buffer, nothing there is required to descend into the network, and the
    # trace of those reaches inflates the closure alone. Measured on the
    # Nancon when one outlet sealed the whole mesh, the raw linework put 1362
    # of its 2479 mapped cells outside the catchment and read 0.306 on the mesh
    # against 0.693 on the catchment. With the flood seeded on the domain
    # border, buffer reaches drain off the domain instead of across the divide,
    # and the two ratios come close (0.81 against 0.77 on the study proxy).
    outside = float(np.mean(~catchment[observed_mask])) if observed_mask.any() else float("nan")
    closure_in = closure & catchment
    alpha_catchment = (
        float((observed_mask & catchment).sum() / closure_in.sum())
        if closure_in.any()
        else float("nan")
    )
    # Measured on the MAPPED network alone even when water bodies joined the
    # target: the diagnostic answers "how much of the catchment descends into
    # the linework without the sealed outlet", and a reservoir absorbing paths
    # would flatter it. On the catchment, not the mesh: buffer cells drain off
    # the domain border and are not required to meet the network.
    reach_from = (
        distance_raw if excluded_mask is None else downslope_distance_to_mask(metric, observed_mask)
    )
    reachable = float(np.mean(np.isfinite(reach_from[catchment])))
    gap = abs(alpha_catchment - alpha)
    # Only when the clipping MOVES the number. A linework spilling out of the
    # catchment over ground that routes the same way leaves the two ratios
    # equal, and a warning there would be noise on every ordinary project.
    if (
        np.isfinite(gap)
        and outside > float(clipping_warning_share)
        and gap > float(clipping_warning_gap)
    ):
        logger.warning(
            "%.0f%% of the mapped stream cells sit outside the scored catchment, and "
            "that alone moves the ratio by %.3f: alpha_obs_closure = %.3f on the mesh "
            "against alpha_obs_closure_catchment = %.3f on the support the criterion "
            "scores. Those reaches trace through the buffer, where no cell is required to "
            "descend into the network. Read the catchment one, or clip the linework to the "
            "catchment to make the two agree.",
            100.0 * outside,
            gap,
            alpha,
            alpha_catchment,
        )
    if np.isfinite(alpha_catchment) and alpha_catchment < float(alpha_warning_threshold):
        logger.warning(
            "The mapped stream network agrees poorly with the MODEL TOP: "
            "alpha_obs_closure_catchment = %.3f, below %.2f. A large share of the D8 trace "
            "leaving the mapped cells falls outside the network, so the distances carry a "
            "top-versus-map disagreement on top of the hydrogeology. This is NOT evidence "
            "the routing DEM was left unburned: the criterion descends the raw top by "
            "design, never the burned surface, so read this beside the alpha the geographic "
            "step reports and expect the two to differ.",
            alpha_catchment,
            float(alpha_warning_threshold),
        )

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
        catchment_mismatch=mismatch,
        distance_to_observed=distance_sealed,
        distance_to_observed_raw=distance_raw,
        cell_area_m2=areas,
        threshold_m3_s=specific_seepage_threshold(areas, recharge, ratio=tau_specific_ratio),
        mean_recharge_m_s=recharge,
        length_scale_m=length_scale,
        saturation_cap_m=longest_descent_length(metric, outlet_mask, within=catchment),
        excluded=excluded_mask,
        alpha_obs_closure=alpha,
        alpha_obs_closure_catchment=alpha_catchment,
        frac_obs_outside_catchment=outside,
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
