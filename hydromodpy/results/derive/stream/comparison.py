"""Rebuild the simulated-versus-mapped stream comparison from a finished run.

The calibration criterion builds this partition during a trial and hands it to
nobody: it scores it and moves on. A map of it is what a reader actually looks
at, so this module rebuilds it from what the run persisted, through the SAME
construction the criterion used (:mod:`hydromodpy.catchment.stream_network.geometry`), and
hands it to any figure that asks.

Rebuilding rather than persisting is deliberate. The partition depends on a
threshold the reader is allowed to move, and on the mapped network the project
declares; recomputing it costs one graph build and three ``O(n_cells)`` passes,
under a second on a seven thousand cell mesh, which is nothing beside a solve.

What the criterion read beside the mesh is persisted by the run and read back
here, never derived again: the centers of the solver, the cells of open water, the
cells of the catchment outline and the mean recharge
(:mod:`hydromodpy.results.derive.stream.criterion_inputs`). The figure therefore
scores the cells the trials scored.

Nothing here names a solver. The run has to carry a per-cell release flux, a
mapped hydrographic network and a delineated watershed, and every backend that
produces those gets the same comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.catchment.algorithms.network_heads import HeadCandidates
from hydromodpy.catchment.drainage.distance import downslope_distance_to_mask
from hydromodpy.catchment.stream_network.geometry import (
    CriterionSupports,
    NetworkGeometry,
    build_network_geometry,
    criterion_supports,
)
from hydromodpy.catchment.stream_network.heads import HeadsSettings
from hydromodpy.catchment.stream_network.network import build_simulated_network
from hydromodpy.core.logging import get_logger
from hydromodpy.core.scoring.stream_defaults import (
    STREAM_CRITERION_DEFAULTS,
    ObservedRasterization,
)
from hydromodpy.mesh.planar.geometry import cell_polygons
from hydromodpy.results.derive.stream.criterion_inputs import (
    basin_reference,
    map_heads,
    mapped_cells,
    snapped_outlet,
)
from hydromodpy.results.run.geographic import geographic_metadata

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

logger = get_logger(__name__)

__all__ = (
    "AGREEMENT_EXCESS",
    "AGREEMENT_MISSING",
    "AGREEMENT_NEITHER",
    "AGREEMENT_VALID",
    "NetworkComparison",
    "has_recharge_source",
    "network_comparison_from_run",
    "no_release_flux_reason",
    "no_recharge_reason",
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
"""The default role: what the project declares under ``[data.hydrography]``
never a model output. A caller that scores a
DEM-derived observation instead passes ``role="generated"``."""


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


def no_release_flux_reason(sim: Run) -> str:
    """Say why a run has no per-cell release flux, and what its store kept."""
    return _with_kept_budget("run has no per-cell release_flux", "release_flux", sim)


def no_recharge_reason() -> str:
    """Say why the recharge a seepage threshold is a fraction of cannot be read."""
    return (
        "This run kept no criterion mean recharge, so a seepage threshold cannot be read "
        "on it. Replay it with hmp replay, or set tau_specific_ratio = 0."
    )


def _with_kept_budget(reason: str, field: str, sim: Run) -> str:
    """Append to ``reason`` what the run kept of the per-cell budget, when it matters."""
    from hydromodpy.results.derive.config_flags import missing_field_explanation

    explanation = missing_field_explanation([field], sim)
    return f"{reason}. {explanation}" if explanation else reason


def unavailable_reason_for_comparison(sim: Run, *, role: str = _REFERENCE_ROLE) -> str | None:
    """Return why this run cannot be compared to a mapped network, or ``None``.

    ``role`` picks which stored hydrographic network stands in for the
    observation, the same choice :func:`network_comparison_from_run` takes.

    Answered before rendering so a figure is skipped with a sentence rather
    than failing halfway through a graph build.
    """
    if not sim.has_field("release_flux"):
        return no_release_flux_reason(sim)
    if not sim.has_hydrographic_network(role):
        return f"run carries no {role!r} hydrographic network"
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
    if sim.descent.open_water() is None:
        return (
            "run kept no open-water cells of its mesh (mesh/open_water), which the criterion "
            "leaves out of both supports. Replay it with hmp replay"
        )
    return None


def network_comparison_from_run(
    sim: Run,
    *,
    role: str = _REFERENCE_ROLE,
    tau_specific_ratio: float = STREAM_CRITERION_DEFAULTS.tau_specific_ratio,
    diagonal_neighbors: bool = STREAM_CRITERION_DEFAULTS.diagonal_neighbors,
    observed_rasterization: ObservedRasterization = (
        STREAM_CRITERION_DEFAULTS.observed_rasterization
    ),
    timestep: int = -1,
    observed_position_accuracy_m: float | None = None,
    alpha_warning_threshold: float = STREAM_CRITERION_DEFAULTS.alpha_warning_threshold,
    clipping_warning_share: float = STREAM_CRITERION_DEFAULTS.clipping_warning_share,
    clipping_warning_gap: float = STREAM_CRITERION_DEFAULTS.clipping_warning_gap,
    heads_snap_radius_m: float = STREAM_CRITERION_DEFAULTS.heads_snap_radius_m,
    heads_min_drained_area_km2: float = STREAM_CRITERION_DEFAULTS.heads_min_drained_area_km2,
    clip_map_to_catchment: bool = STREAM_CRITERION_DEFAULTS.clip_map_to_catchment,
) -> NetworkComparison:
    """Rebuild the stream comparison of one run.

    ``role`` picks which stored hydrographic network stands in for the
    observation: ``"reference"`` (the default) for the mapped network the
    project declares under ``[data.hydrography]``, ``"generated"`` for the
    network the DEM itself was thresholded into under
    ``[geographic.river_network]``.

    ``tau_specific_ratio`` is the fraction of the mean basin recharge over its area below which a
    releasing cell is not counted as a stream, the same knob the calibration
    output carries. Zero reproduces the purely geometric criterion of the paper
    and needs no recharge; any other value needs the run to carry its recharge
    budget, and the run is refused by name when it does not.

    ``diagonal_neighbors`` is the neighbor graph of the descent, and its
    default is the calibration output's: the D8 descent of the paper on a
    quad mesh. A figure redrawn on another graph than the trial scored would
    show a partition the reported numbers were never computed on.

    ``observed_rasterization`` draws the mapped network on the cells by the
    rule the calibration output uses, with the same default: ``"crossing"``,
    the thin line of WhiteboxTools VectorLinesToRaster, ``"touch"``, or
    ``"heads"``, the free ends of the map traced down the criterion graph,
    each landing within ``heads_snap_radius_m`` on a cell draining at least
    ``heads_min_drained_area_km2``. A map drawn by another rule than the trial
    would show a mapped network the criterion never scored.

    ``clip_map_to_catchment`` is the same key of the calibration output. A run
    persists its ``reference`` network cut to the catchment, and a trial cuts a
    file the same way, so the two draw one map, and under ``"heads"`` an end the
    cut made is no head. A run scored with the key off read its file whole and
    took every free end for a candidate: the redraw then takes every free end of
    the cut map, and ``alpha_obs_closure``, a whole-mesh ratio, reads the cut map
    where the trial read the whole file. ``[data.hydrography] mask_path`` writes
    another mask than the watershed the run stores, and the redraw knows only the
    watershed.

    The centers are the ones the run stored (``mesh.cell_centers()``), which are the
    centers the solver sampled its top at, the generator seeds on a Voronoi mesh.
    ``catchment_mismatch`` reads the cells of the catchment outline the run stored,
    and ``basin_mismatch`` the stored basin of D. Cells of open water leave both
    supports, as in a trial.
    """
    reason = unavailable_reason_for_comparison(sim, role=role)
    if reason is not None:
        raise ValueError(f"stream comparison unavailable for {sim.sim_id}: {reason}")

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
    centres = np.asarray(mesh.cell_centers(), dtype=float)

    network = sim.hydrographic_network(role)
    if network is None or network.empty:
        raise ValueError(f"the {role!r} hydrographic network of {sim.sim_id} holds no feature.")
    lines = list(network.geometry)
    outlet_xy = _snapped_outlet_of(sim)
    observed: np.ndarray | None = None
    heads: tuple[HeadCandidates, HeadsSettings] | None = None
    if observed_rasterization == "heads":
        heads = (
            map_heads(
                lines,
                mesh_crs=mesh.crs,
                geometry_crs=network.crs,
                outlet_xy=outlet_xy,
                dam_foot=np.asarray(sim.descent.dam_foot, dtype=np.int64),
                **(_cut_of_the_map(sim) if clip_map_to_catchment else {}),
            ),
            HeadsSettings(
                snap_radius_m=float(heads_snap_radius_m),
                min_drained_area_m2=float(heads_min_drained_area_km2) * 1.0e6,
            ),
        )
    elif observed_rasterization in ("crossing", "touch"):
        observed = mapped_cells(
            observed_rasterization,
            lines,
            polygons=polygons,
            vertices=vertices,
            connectivity=connectivity,
            centres=centres,
            mesh_crs=mesh.crs,
            geometry_crs=network.crs,
        ).mask
    else:
        raise ValueError(
            "observed_rasterization must be 'heads', 'crossing' or 'touch', "
            f"got {observed_rasterization!r}."
        )

    open_water = np.asarray(sim.descent.open_water(), dtype=bool)
    outline = sim.descent.catchment_cells()
    geometry = build_network_geometry(
        topography=topography,
        face_node_connectivity=connectivity,
        vertices=vertices,
        observed=observed,
        heads=heads,
        cell_area_m2=areas,
        cell_centroids=centres,
        mean_recharge_m_s=_criterion_recharge(sim, ratio=tau_specific_ratio),
        tau_specific_ratio=float(tau_specific_ratio),
        excluded=open_water if open_water.any() else None,
        delineated_catchment=basin_reference(
            sim.descent.stored_basin(), outline, source=f"run {sim.sim_id}"
        ),
        catchment_outline=outline,
        delineated_outlet_xy=outlet_xy,
        diagonal_neighbors=bool(diagonal_neighbors),
        observed_position_accuracy_m=observed_position_accuracy_m,
        alpha_warning_threshold=float(alpha_warning_threshold),
        clipping_warning_share=float(clipping_warning_share),
        clipping_warning_gap=float(clipping_warning_gap),
    )

    release = np.asarray(sim.field("release_flux", time=timestep), dtype=float).reshape(-1)
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


def _cut_of_the_map(sim: Run) -> dict[str, object]:
    """Return the outline the stored map was cut along, empty when the run stores none."""
    try:
        watershed = sim.geographic("watershed")
    except (KeyError, ValueError, FileNotFoundError):
        return {}
    if watershed is None or watershed.empty:
        return {}
    return {"cut_outline": watershed.union_all(), "cut_crs": watershed.crs}


def _snapped_outlet_of(sim: Run) -> tuple[float, float] | None:
    """Return the snapped pour point the geographic step stored, or ``None``."""
    meta = geographic_metadata(sim)
    return snapped_outlet(meta.get("x_outlet_snapped"), meta.get("y_outlet_snapped"))


def _criterion_recharge(sim: Run, *, ratio: float) -> float:
    """Return the mean recharge the trials read, 0 for a purely geometric criterion.

    A zero ratio makes the threshold zero whatever the recharge is, so the run is
    not asked for one. Any other ratio needs the number the run kept.
    """
    if float(ratio) == 0.0:
        return 0.0
    kept = sim.descent.criterion_recharge()
    if kept is None:
        raise ValueError(f"stream comparison unavailable for {sim.sim_id}: {no_recharge_reason()}")
    return float(kept)


def has_recharge_source(sim: Run) -> bool:
    """Return whether the run kept the mean recharge a positive seepage threshold needs."""
    return sim.descent.criterion_recharge() is not None


def agreement_label(value: int) -> str:
    """Return the human-readable name of one agreement class."""
    try:
        return AGREEMENT_LABELS[int(value)]
    except KeyError as exc:
        raise ValueError(f"unknown stream agreement class {value!r}.") from exc
