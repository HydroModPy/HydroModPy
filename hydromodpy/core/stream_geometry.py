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

from dataclasses import dataclass, replace
from typing import Literal

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
from hydromodpy.core.stream_snap import (
    SnapStreamsConfig,
    StreamSnap,
    representation_floor_m,
    snap_observed_network,
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

ValidityProvenance = Literal["auto", "auto_floor", "declared_accuracy", "user"]

VALIDITY_PROVENANCE_CODE: dict[str, float] = {
    "auto": 0.0,
    "auto_floor": 1.0,
    "declared_accuracy": 2.0,
    "user": 3.0,
}
"""The number a trial publishes as ``validity_length_provenance``, since
components are floats."""

VALIDITY_PROVENANCE_BY_CODE: dict[float, str] = {
    code: name for name, code in VALIDITY_PROVENANCE_CODE.items()
}
"""The provenance a published code stands for."""


@dataclass(frozen=True, slots=True)
class ValidityLength:
    """The length Eq. 4 bounds ``Doptim`` by, and what set it.

    ``provenance`` names the term that decided the length: ``"user"`` for a
    declared ``validity_length``, ``"auto_floor"`` when the snap floor ``F``
    exceeded ``h``, ``"declared_accuracy"`` when the declared positional
    accuracy exceeded ``h_obs``, and ``"auto"`` for two cells, the paper.
    """

    length_m: float
    provenance: ValidityProvenance

    @property
    def code(self) -> float:
        """The provenance as the float a trial publishes."""
        return VALIDITY_PROVENANCE_CODE[self.provenance]


def resolve_validity_length(
    *,
    h_obs_m: float,
    accuracy_m: float | None = None,
    floor_m: float | None = None,
    declared_m: float | None = None,
) -> ValidityLength:
    """Return the validity length of Eq. 4, in metres.

    A declared length wins. Otherwise ``h = max(h_obs, accuracy)`` when an
    accuracy is declared, else ``h_obs``. Without a floor the length is
    ``2 h``, the two pixels of the paper (HESS 27, p. 3225). With the snap
    floor ``F``, measured in ``diagnose`` and ``apply``, it is
    ``h + max(h, F)``: one cell for the hydrogeology, and one for the map
    error the paper budgets (p. 3224), replaced by ``F`` when ``F`` is larger.
    A floor that is not a number counts as no floor.
    """
    if declared_m is not None:
        return ValidityLength(float(declared_m), "user")
    h_obs = float(h_obs_m)
    scale = h_obs
    provenance: ValidityProvenance = "auto"
    if accuracy_m is not None and float(accuracy_m) > h_obs:
        scale = float(accuracy_m)
        provenance = "declared_accuracy"
    if floor_m is None or not np.isfinite(floor_m):
        return ValidityLength(2.0 * scale, provenance)
    floor = float(floor_m)
    if floor > scale:
        provenance = "auto_floor"
    return ValidityLength(scale + max(scale, floor), provenance)


@dataclass(frozen=True, slots=True)
class NetworkGeometry:
    """Everything the cost needs that does not change from trial to trial.

    ``catchment`` is the scored support: the cells whose descent on the
    conditioned graph reaches ``outlet``. ``catchment_mismatch`` is the area of
    the symmetric difference between it and the delineated raster polygon,
    divided by the polygon's area; NaN when no polygon was given.

    ``observed`` is the map the criterion scores: the snapped map when the
    snap is applied, the raw projection otherwise. ``observed_raw`` is always
    the raw projection. ``h_obs_m`` is the cell size on the mapped network,
    the length ``roptim`` is divided by (Eq. 3). ``snap`` is None when the
    snap is off. ``observed_position_accuracy_m`` is the declared accuracy of
    the map, which only the validity length reads (:meth:`validity_length`).
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
    saturation_cap_m: float
    excluded: np.ndarray | None
    alpha_obs_closure: float
    alpha_obs_closure_catchment: float
    frac_obs_outside_catchment: float
    frac_reachable_obs_raw: float
    h_obs_m: float = float("nan")
    observed_raw: np.ndarray | None = None
    snap: StreamSnap | None = None
    observed_position_accuracy_m: float | None = None

    def validity_length(self, declared_m: float | None = None) -> ValidityLength:
        """Return the Eq. 4 length this map is qualified against.

        ``declared_m`` is the output's ``validity_length`` when it is a length,
        None for ``"auto"``. The floor ``F`` enters only when the snap ran, in
        ``diagnose`` or ``apply`` (:func:`resolve_validity_length`).
        """
        return resolve_validity_length(
            h_obs_m=self.h_obs_m,
            accuracy_m=self.observed_position_accuracy_m,
            floor_m=None if self.snap is None else self.snap.floor_m,
            declared_m=declared_m,
        )

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

        The ``snap_*`` indices travel only when the snap is on: an ``off``
        trial publishes exactly what it published before the snap existed.
        """
        diagnostics = {
            "alpha_obs_closure": self.alpha_obs_closure,
            "alpha_obs_closure_catchment": self.alpha_obs_closure_catchment,
            "frac_obs_outside_catchment": self.frac_obs_outside_catchment,
            "frac_reachable_obs_raw": self.frac_reachable_obs_raw,
            "catchment_mismatch": self.catchment_mismatch,
            "n_outlet_sealed": float(0.0 if self.observed[self.outlet] else 1.0),
            "R_mean_m_s": self.mean_recharge_m_s,
        }
        if self.snap is not None:
            diagnostics.update(self.snap.indices)
        return diagnostics


_last_mean_recharge: float | None = None

RECHARGE_MOVE_TOLERANCE: float = 1e-6
"""Relative change of the mean recharge below which two builds read the same R.

Two builds of one session average the same forcing in a different order, and
float sums then differ in the last digits (9.074855002572016e-09 against
9.074854999999997e-09). That is noise, not a move of the ratio's denominator.
"""

_alpha_warned: bool = False


def _warn_if_recharge_moved(recharge: float) -> None:
    """Warn when the recharge changes between two geometries of one process.

    The criterion fits ``K/R``, so a recharge that moves between two trials
    changes the calibrated quantity while every declared parameter looks
    unchanged. Warning rather than refusing: this module knows a mesh, not a
    session, and two consecutive builds can legitimately belong to two
    projects; a refusal would abort those, while the ``R_mean_m_s`` diagnostic
    already records the value per trial and the warning only makes the move
    visible while it happens. A relative change under
    :data:`RECHARGE_MOVE_TOLERANCE` is float noise and stays silent.

    A trial and the redraw of a run read ``R`` by one rule
    (:mod:`hydromodpy.core.stream_recharge`), so a move is a move of the
    forcing, never of the way it was averaged.
    """
    global _last_mean_recharge
    previous, _last_mean_recharge = _last_mean_recharge, recharge
    if previous is None or np.isclose(recharge, previous, rtol=RECHARGE_MOVE_TOLERANCE, atol=0.0):
        return
    logger.warning(
        "The mean recharge moved between two network criterion builds: %.4g then %.4g m/s. "
        "The criterion calibrates the ratio K/R, so a bound of one per cent holds on the "
        "conductivity only while R stays put. Freeze the recharge for the whole session, "
        "or read R_mean_m_s per trial before reading the calibrated value as a K.",
        previous,
        recharge,
    )


def _report_poor_alpha(alpha_catchment: float, threshold: float) -> None:
    """Say once per process that the map and the model top disagree.

    Every trial of a session and every promoted run rebuilds the geometry on
    the same top and the same map, so the number barely moves. The first build
    warns; the later ones log at INFO, which ``--verbose`` shows.
    """
    global _alpha_warned
    log = logger.info if _alpha_warned else logger.warning
    _alpha_warned = True
    log(
        "The mapped stream network agrees poorly with the model top "
        "(alpha_obs_closure_catchment = %.3f, below %.2f), so the distances carry a "
        "top-versus-map disagreement on top of the hydrogeology. This does not mean the "
        "routing DEM was left unburned: the criterion descends the raw top by design, so "
        "this alpha differs from the one the geographic step reports.",
        alpha_catchment,
        threshold,
    )


def neighbour_spacing_m(
    cell_centroids: np.ndarray,
    face_node_connectivity: np.ndarray,
    *,
    touching: np.ndarray | None = None,
) -> float:
    """Return the median distance between the centres of cells sharing an edge.

    Two cells are neighbours when they share an edge, whatever the descent the
    criterion routes on. ``touching`` keeps the pairs of which at least one
    cell lies in it. At least one, not both: under the crossing rule two
    successive mapped cells along a diagonal often share only a corner.
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
    if touching is not None:
        near = np.asarray(touching, dtype=bool).reshape(-1)
        keep &= near[first] | near[second]
    delta = centres[first[keep]] - centres[second[keep]]
    distances = np.hypot(delta[:, 0], delta[:, 1])
    distances = distances[np.isfinite(distances)]
    if distances.size == 0:
        raise ValueError("the mesh holds no two neighbouring cells to measure a cell on.")
    return float(np.median(distances))


def observed_cell_size_m(
    cell_centroids: np.ndarray,
    face_node_connectivity: np.ndarray,
    *,
    observed: np.ndarray,
    catchment: np.ndarray,
) -> float:
    """Return ``h_obs``, the size of one cell where the mapped network lies.

    It is the median distance between neighbouring cell centres over the
    mapped cells of the catchment (:func:`neighbour_spacing_m`). The distances
    ``D_os`` start from those cells, so on a mesh refined along the streams
    the fine cells set the scale, not the coarse hillslope cells a
    catchment-wide median can land on. On a regular grid it is the cell size.
    It is static: the map does not move with ``K``, the simulated network
    does, and the latter must not set the bound. A catchment holding no mapped
    cell falls back on the catchment itself, which the criterion refuses
    further down with a message naming the empty support.
    """
    mapped = np.asarray(observed, dtype=bool).reshape(-1) & np.asarray(
        catchment, dtype=bool
    ).reshape(-1)
    touching = mapped if mapped.any() else np.asarray(catchment, dtype=bool).reshape(-1)
    return neighbour_spacing_m(cell_centroids, face_node_connectivity, touching=touching)


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
    snap: SnapStreamsConfig | None = None,
    weighting: Literal["cell", "area"] = "cell",
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

    ``snap`` is the ``[geographic.snap_streams]`` setting, None meaning off.
    In ``diagnose`` the snapped map, its indices and the floor ``F`` are
    computed and the raw map is scored; in ``apply`` the snapped map is scored.
    The length scale is ``h_obs`` (:func:`observed_cell_size_m`), read on the
    raw map. ``observed_position_accuracy_m`` does not change it: it is kept
    for the validity length only (:meth:`NetworkGeometry.validity_length`).
    ``weighting`` is the weighting of the output that scores this geometry;
    only the floor ``F`` reads it, so ``F`` is averaged like the ``Doptim``
    it bounds.
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

    # Read on the RAW map: the snap radius is counted in it, and the map an
    # observation was drawn on does not move with the snap.
    h_obs = observed_cell_size_m(
        metric.centroids, face_node_connectivity, observed=observed_mask, catchment=catchment
    )
    observed_raw = observed_mask
    stream_snap: StreamSnap | None = None
    if snap is not None and snap.enabled:
        stream_snap = snap_observed_network(
            metric=metric,
            observed=observed_raw,
            outlet=outlet,
            catchment=catchment,
            cell_area_m2=areas,
            adjacency=adjacency,
            h_obs_m=h_obs,
            settings=snap,
            water_bodies=excluded_mask,
        )
        if snap.mode == "apply":
            observed_mask = stream_snap.snapped & active

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
        _report_poor_alpha(alpha_catchment, float(alpha_warning_threshold))

    recharge = float(mean_recharge_m_s)
    _warn_if_recharge_moved(recharge)

    saturation_cap = longest_descent_length(metric, outlet_mask, within=catchment)
    if stream_snap is not None:
        keep = catchment if excluded_mask is None else (catchment & ~excluded_mask)
        stream_snap = replace(
            stream_snap,
            floor_m=representation_floor_m(
                metric=metric,
                raw=observed_raw,
                snapped=stream_snap.snapped & active,
                outlet=outlet,
                keep=keep,
                saturation_cap_m=saturation_cap,
                water_bodies=excluded_mask,
                # The same averaging as the scored Doptim, which reads
                # geometry.cell_area_m2 below under the "area" weighting.
                weights=areas if weighting == "area" else None,
            ),
        )
        logger.info(
            "Network criterion: snap %s, radius %.4g m, %d mapped cell(s), p90 displacement "
            "%.4g m, %.1f%% rejected, length ratio %.3f, floor F = %.4g m.",
            stream_snap.mode,
            stream_snap.radius_m,
            int(stream_snap.raw.sum()),
            stream_snap.displacement_p90_m,
            100.0 * stream_snap.rejected_share,
            stream_snap.length_ratio,
            stream_snap.floor_m,
        )

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
        saturation_cap_m=saturation_cap,
        excluded=excluded_mask,
        alpha_obs_closure=alpha,
        alpha_obs_closure_catchment=alpha_catchment,
        frac_obs_outside_catchment=outside,
        frac_reachable_obs_raw=reachable,
        h_obs_m=h_obs,
        observed_raw=observed_raw,
        snap=stream_snap,
        observed_position_accuracy_m=(
            float(observed_position_accuracy_m) if observed_position_accuracy_m else None
        ),
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
    "VALIDITY_PROVENANCE_BY_CODE",
    "VALIDITY_PROVENANCE_CODE",
    "CriterionSupports",
    "NetworkGeometry",
    "ValidityLength",
    "ValidityProvenance",
    "build_network_geometry",
    "criterion_supports",
    "neighbour_spacing_m",
    "observed_cell_size_m",
    "resolve_outlet",
    "resolve_validity_length",
)
