"""Rebuild the simulated-versus-mapped stream comparison from a finished run.

The calibration criterion builds this partition during a trial and hands it to
nobody: it scores it and moves on. A map of it is what a reader actually looks
at, so this module rebuilds it from what the run persisted, through the SAME
construction the criterion used (:mod:`hydromodpy.core.stream_geometry`), and
hands it to any figure that asks.

Rebuilding rather than persisting is deliberate. The partition depends on a
threshold the reader is allowed to move, and on the mapped network the project
declares; recomputing it costs one graph build and three ``O(n_cells)`` passes,
under a second on a seven thousand cell mesh, which is nothing beside a solve.

Nothing here names a solver. The run has to carry a per-cell release flux, a
mapped hydrographic network and a delineated watershed, and every backend that
produces those gets the same comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.core.stream_geometry import (
    CriterionSupports,
    NetworkGeometry,
    build_network_geometry,
    criterion_supports,
)
from hydromodpy.core.stream_network import build_simulated_network
from hydromodpy.core.topographic_distance import downslope_distance_to_mask

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

logger = get_logger(__name__)

__all__ = (
    "AGREEMENT_EXCESS",
    "AGREEMENT_MISSING",
    "AGREEMENT_NEITHER",
    "AGREEMENT_VALID",
    "NetworkComparison",
    "network_comparison_from_run",
    "unavailable_reason_for_comparison",
)

#: Class of one cell in the three-way agreement map. One integer field rather
#: than three boolean ones, because a cell belongs to exactly one class and a
#: figure that has to combine three masks can combine them wrongly.
AGREEMENT_NEITHER = 0
AGREEMENT_VALID = 1
AGREEMENT_EXCESS = 2
AGREEMENT_MISSING = 3

AGREEMENT_LABELS: dict[int, str] = {
    AGREEMENT_NEITHER: "no stream",
    AGREEMENT_VALID: "simulated and mapped",
    AGREEMENT_EXCESS: "simulated only",
    AGREEMENT_MISSING: "mapped only",
}

_REFERENCE_ROLE = "reference"
"""The canonical role of the mapped network: what the project declares under
``[data.hydrography]`` and burns into the routing DEM, never a model output."""


@dataclass(frozen=True, slots=True)
class NetworkComparison:
    """What a run says about its streams, on the mesh it was solved on."""

    geometry: NetworkGeometry
    supports: CriterionSupports
    agreement: np.ndarray
    """(n_cells,) uint8: one of the ``AGREEMENT_*`` classes per cell."""

    distance_to_mapped_m: np.ndarray
    """(n_cells,) descent length to the mapped network, ``inf`` when none."""

    distance_to_simulated_m: np.ndarray
    """(n_cells,) descent length to the simulated network, ``inf`` when none."""

    tau_specific_ratio: float
    n_cells: int

    @property
    def simulated(self) -> np.ndarray:
        """Cells the model puts a stream on, inside the scored catchment."""
        return self.supports.support_so

    @property
    def mapped(self) -> np.ndarray:
        """Cells the mapped network covers, inside the scored catchment."""
        return self.supports.support_os

    @property
    def counts(self) -> dict[str, float]:
        """The three class sizes, named as a calibration trial publishes them."""
        return self.supports.counts


def unavailable_reason_for_comparison(sim: Run) -> str | None:
    """Return why this run cannot be compared to a mapped network, or ``None``.

    Answered before rendering so a figure is skipped with a sentence rather
    than failing halfway through a graph build.
    """
    if not sim.has_field("release_flux"):
        return (
            "run has no per-cell release_flux: set [simulation.results.derived] release_flux = true"
        )
    if not sim.has_hydrographic_network(_REFERENCE_ROLE):
        return (
            "run carries no 'reference' hydrographic network: declare the mapped "
            "linework under [data.hydrography]"
        )
    # ``Run.mesh`` raises on a run that has no mesh at all, a lumped GR4J one
    # for instance. A gallery asks this question of every figure of every run,
    # so it has to come back as a sentence and never as an exception.
    try:
        mesh = sim.mesh
    except (RuntimeError, KeyError, FileNotFoundError) as exc:
        return f"run carries no mesh to route on ({type(exc).__name__})"
    if mesh is None or mesh.topography is None:
        return "run persisted no mesh topography to route on"
    if not mesh.crs:
        return "run declares no projected CRS, so the mapped network cannot be placed"
    return None


def network_comparison_from_run(
    sim: Run,
    *,
    tau_specific_ratio: float = 1.0e-4,
    diagonal_neighbors: bool = False,
    timestep: int = -1,
    observed_position_accuracy_m: float | None = None,
) -> NetworkComparison:
    """Rebuild the stream comparison of one run.

    ``tau_specific_ratio`` is the fraction of its own recharge below which a
    releasing cell is not counted as a stream, the same knob the calibration
    output carries. Zero reproduces the purely geometric criterion of the paper
    and needs no recharge; any other value needs the run to carry its recharge
    budget, and the run is refused by name when it does not.

    The centres used here are the polygon centroids of the faces, because a
    persisted mesh stores no other. On a Voronoi dual the solver sampled its top
    at the generator seeds instead, so a comparison redrawn from the store can
    route marginally differently from the one a trial scored. It is exact on any
    mesh whose cells are parallelograms, which every structured grid is.
    """
    reason = unavailable_reason_for_comparison(sim)
    if reason is not None:
        raise ValueError(f"stream comparison unavailable for {sim.sim_id}: {reason}")

    from hydromodpy.spatial.mesh.ops.vector_cell_mask import cell_polygons, vector_cell_mask

    mesh = sim.mesh
    vertices = np.asarray(mesh.vertices, dtype=float)
    connectivity = np.asarray(mesh.face_node_connectivity)
    topography = np.asarray(mesh.topography, dtype=float).reshape(-1)
    n_cells = int(topography.size)
    polygons = cell_polygons(vertices, connectivity)
    areas = np.asarray(
        [0.0 if polygon is None else float(polygon.area) for polygon in polygons],
        dtype=float,
    )

    network = sim.hydrographic_network(_REFERENCE_ROLE)
    if network is None or network.empty:
        raise ValueError(f"the 'reference' hydrographic network of {sim.sim_id} holds no feature.")
    observed = np.asarray(
        vector_cell_mask(
            polygons,
            list(network.geometry),
            mesh_crs=mesh.crs,
            geometry_crs=network.crs,
        ),
        dtype=bool,
    )

    geometry = build_network_geometry(
        topography=topography,
        face_node_connectivity=connectivity,
        vertices=vertices,
        observed=observed,
        cell_area_m2=areas,
        mean_recharge_m_s=_mean_recharge_m_s(sim, areas, ratio=tau_specific_ratio),
        tau_specific_ratio=float(tau_specific_ratio),
        delineated_catchment=_delineated_catchment(sim, polygons, mesh.crs),
        diagonal_neighbors=bool(diagonal_neighbors),
        observed_position_accuracy_m=observed_position_accuracy_m,
    )

    release = np.asarray(sim.field("release_flux", timestep=timestep), dtype=float).reshape(-1)
    if release.size != n_cells:
        raise ValueError(
            f"release_flux holds {release.size} cells and the mesh holds {n_cells}; "
            "they were not written for the same run."
        )
    simulated = build_simulated_network(
        release,
        threshold_m3_s=geometry.threshold_m3_s,
        metric=geometry.metric,
    )
    supports = criterion_supports(
        simulated=simulated,
        observed=geometry.observed,
        catchment=geometry.catchment,
        active=geometry.metric.graph.active,
        excluded=geometry.excluded,
    )

    agreement = np.full(n_cells, AGREEMENT_NEITHER, dtype="uint8")
    agreement[supports.missing] = AGREEMENT_MISSING
    agreement[supports.excess] = AGREEMENT_EXCESS
    agreement[supports.valid] = AGREEMENT_VALID

    return NetworkComparison(
        geometry=geometry,
        supports=supports,
        agreement=agreement,
        distance_to_mapped_m=geometry.distance_to_observed,
        distance_to_simulated_m=downslope_distance_to_mask(geometry.metric, simulated.network),
        tau_specific_ratio=float(tau_specific_ratio),
        n_cells=n_cells,
    )


def _delineated_catchment(sim: Run, polygons: np.ndarray, mesh_crs: str) -> np.ndarray | None:
    """Project the delineated watershed onto the cells, by their centre."""
    from hydromodpy.spatial.mesh.ops.vector_cell_mask import vector_cell_mask

    try:
        watershed = sim.geographic("watershed")
    except (KeyError, ValueError, FileNotFoundError) as exc:
        logger.warning(
            "Stream comparison: run %s carries no delineated watershed (%s), so the "
            "catchment is re-derived by descending the model top to its own largest "
            "basin. On a real surface that basin is an internal depression.",
            sim.sim_id,
            type(exc).__name__,
        )
        return None
    if watershed is None or watershed.empty:
        return None
    return np.asarray(
        vector_cell_mask(
            polygons,
            list(watershed.geometry),
            mesh_crs=mesh_crs,
            geometry_crs=watershed.crs,
            rule="centroid",
        ),
        dtype=bool,
    )


def _mean_recharge_m_s(sim: Run, areas: np.ndarray, *, ratio: float) -> float:
    """Return the mean recharge rate of the run, in m/s.

    Read back from the budget the solver wrote, never from the TOML: the
    threshold is a fraction of what the model RECEIVED. A zero ratio makes the
    threshold zero whatever the recharge is, so the run is not asked for one.
    """
    if float(ratio) == 0.0:
        return 0.0
    if not sim.has_field("recharge"):
        raise ValueError(
            f"stream comparison unavailable for {sim.sim_id}: a seepage threshold of "
            f"{ratio:g} is a fraction of the recharge the model received, and this run "
            "persisted no recharge budget. Enable it, or set tau_specific_ratio = 0 to "
            "read the purely geometric criterion."
        )
    recharge_m3_s = np.asarray(sim.field("recharge", timestep=-1), dtype=float).reshape(-1)
    usable = np.isfinite(recharge_m3_s) & np.isfinite(areas) & (areas > 0.0)
    if not np.any(usable):
        raise ValueError(
            f"stream comparison unavailable for {sim.sim_id}: its recharge budget holds "
            "no finite value on a cell of finite area."
        )
    return float(np.mean(recharge_m3_s[usable] / areas[usable]))


def agreement_label(value: int) -> str:
    """Return the human-readable name of one agreement class."""
    try:
        return AGREEMENT_LABELS[int(value)]
    except KeyError as exc:
        raise ValueError(f"unknown stream agreement class {value!r}.") from exc
