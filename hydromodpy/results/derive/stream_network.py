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
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

from hydromodpy.core.field_routing import cell_centroids_from_mesh
from hydromodpy.core.logging import get_logger
from hydromodpy.core.stream_criterion_defaults import (
    STREAM_CRITERION_DEFAULTS,
    ObservedRasterization,
)
from hydromodpy.core.stream_geometry import (
    CriterionSupports,
    NetworkGeometry,
    build_network_geometry,
    criterion_supports,
)
from hydromodpy.core.stream_network import build_simulated_network
from hydromodpy.core.stream_recharge import criterion_mean_recharge, forcing_period_rates
from hydromodpy.core.stream_snap import SnapStreamsConfig
from hydromodpy.core.time.period_aggregation import period_edges
from hydromodpy.core.topographic_distance import downslope_distance_to_mask
from hydromodpy.core.units import factor_to_m_per_s
from hydromodpy.results.derive.snapped_network import snap_settings_of_run

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
"""The default role: what the project declares under ``[data.hydrography]``
and burns into the routing DEM, never a model output. A caller that scores a
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


def unavailable_reason_for_comparison(sim: Run, *, role: str = _REFERENCE_ROLE) -> str | None:
    """Return why this run cannot be compared to a mapped network, or ``None``.

    ``role`` picks which stored hydrographic network stands in for the
    observation, the same choice :func:`network_comparison_from_run` takes.

    Answered before rendering so a figure is skipped with a sentence rather
    than failing halfway through a graph build.
    """
    if not sim.has_field("release_flux"):
        return (
            "run has no per-cell release_flux: set [simulation.results.derived] release_flux = true"
        )
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
    snap: SnapStreamsConfig | None = None,
    weighting: Literal["cell", "area"] = "cell",
) -> NetworkComparison:
    """Rebuild the stream comparison of one run.

    ``role`` picks which stored hydrographic network stands in for the
    observation: ``"reference"`` (the default) for the mapped network the
    project declares under ``[data.hydrography]``, ``"generated"`` for the
    network the DEM itself was thresholded into under
    ``[geographic.river_network]``.

    ``tau_specific_ratio`` is the fraction of its own recharge below which a
    releasing cell is not counted as a stream, the same knob the calibration
    output carries. Zero reproduces the purely geometric criterion of the paper
    and needs no recharge; any other value needs the run to carry its recharge
    budget, and the run is refused by name when it does not.

    ``diagonal_neighbors`` is the neighbour graph of the descent, and its
    default is the calibration output's: the D8 descent of the paper on a
    quad mesh. A figure redrawn on another graph than the trial scored would
    show a partition the reported numbers were never computed on.

    ``observed_rasterization`` draws the mapped network on the cells by the
    rule the calibration output uses, with the same default: ``"crossing"``,
    the thin line of WhiteboxTools VectorLinesToRaster, or ``"touch"``. A map
    drawn by another rule than the trial would show a mapped network the
    criterion never scored.

    One number does NOT reproduce the trial: ``alpha_obs_closure``. The
    criterion reads the mapped network from the file the calibration output
    declares, whole; a run persists its ``reference`` network CLIPPED to the
    catchment. Measured on the Nancon, 945 features and 181.7 km against 226
    features and 45.6 km. Inside the catchment the two agree cell for cell, so
    every scored quantity matches, but alpha is a whole-mesh ratio and reads
    0.306 on the raw linework against 0.766 on the clipped one. Read the alpha
    of a figure as the catchment one, and the alpha of a trial as the raw one.

    The centres used here are the polygon centroids of the faces, because a
    persisted mesh stores no other. On a Voronoi dual the solver sampled its top
    at the generator seeds instead, and a trial joins those seeds too when it
    draws the mapped network by ``"crossing"``. So a comparison redrawn from the
    store can route, and mark the mapped cells, marginally differently from the
    one a trial scored, and its D_so, D_os and J can differ with it. It is exact
    on any mesh whose cells are parallelograms, which every structured grid is.

    ``snap`` is the ``[geographic.snap_streams]`` setting to redraw with. Left
    None, the setting the run sealed in its configuration is used, so a run
    that scored a snapped map redraws the snapped map it scored.
    ``weighting`` averages the snap floor ``F`` the way the calibration
    output averaged its ``Doptim``, with the same default.
    """
    reason = unavailable_reason_for_comparison(sim, role=role)
    if reason is not None:
        raise ValueError(f"stream comparison unavailable for {sim.sim_id}: {reason}")

    from hydromodpy.spatial.mesh.ops.vector_cell_mask import (
        cell_polygons,
        line_crossing_cell_mask,
        vector_cell_mask,
    )

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

    network = sim.hydrographic_network(role)
    if network is None or network.empty:
        raise ValueError(f"the {role!r} hydrographic network of {sim.sim_id} holds no feature.")
    if observed_rasterization == "touch":
        observed = np.asarray(
            vector_cell_mask(
                polygons,
                list(network.geometry),
                mesh_crs=mesh.crs,
                geometry_crs=network.crs,
            ),
            dtype=bool,
        )
    elif observed_rasterization == "crossing":
        # The persisted mesh stores no other centres than its vertices give,
        # the same ones the descent below routes on.
        observed = np.asarray(
            line_crossing_cell_mask(
                polygons,
                vertices,
                connectivity,
                cell_centroids_from_mesh(vertices, connectivity),
                list(network.geometry),
                mesh_crs=mesh.crs,
                geometry_crs=network.crs,
            ).mask,
            dtype=bool,
        )
    else:
        raise ValueError(
            f"observed_rasterization must be 'crossing' or 'touch', got {observed_rasterization!r}."
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
        delineated_outlet_xy=_delineated_outlet_xy(sim),
        diagonal_neighbors=bool(diagonal_neighbors),
        observed_position_accuracy_m=observed_position_accuracy_m,
        alpha_warning_threshold=float(alpha_warning_threshold),
        clipping_warning_share=float(clipping_warning_share),
        clipping_warning_gap=float(clipping_warning_gap),
        snap=snap_settings_of_run(sim) if snap is None else snap,
        weighting=weighting,
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


def _delineated_outlet_xy(sim: Run) -> tuple[float, float] | None:
    """Return the snapped outlet the geographic step delineated from, or ``None``.

    The trial places its outlet from this same point, so the redraw closes the
    same catchment. ``None`` for a catchment drawn as a polygon.
    """
    from hydromodpy.results.run.geographic import geographic_metadata

    meta = geographic_metadata(sim)
    try:
        point = (float(meta["x_outlet_snapped"]), float(meta["y_outlet_snapped"]))
    except (KeyError, TypeError, ValueError):
        return None
    return point if np.all(np.isfinite(point)) else None


def _mean_recharge_m_s(sim: Run, areas: np.ndarray, *, ratio: float) -> float:
    """Return the mean recharge rate of the run, in m/s, as the trials read it.

    The criterion's one rule (:mod:`hydromodpy.core.stream_recharge`): the
    unweighted mean, over the run's periods, of the rate the recharge forcing
    gives each. It is rebuilt from the station forcing the run stores, put on
    the run's own period edges by the rule the solver forcing is built by, so
    a steady spin-up period counts at its own rate. The budget the solver wrote
    holds the record mean there instead: on the monthly Nancon, 8.656e-9 m/s
    against the 9.075e-9 every trial scored with.

    The budget is read only when the run stores no station forcing, or no
    dates to place it on. A gridded forcing is stored without its time axis,
    and the gridded path writes each period's rate as the forcing gives it, so
    its budget is the forcing on the cells. A zero ratio makes the threshold
    zero whatever the recharge is, so the run is not asked for one.
    """
    if float(ratio) == 0.0:
        return 0.0
    stored = _stored_recharge_forcing_m_s(sim)
    edges = _run_period_edges(sim) if stored is not None else None
    if stored is not None and edges is not None:
        return criterion_mean_recharge(forcing_period_rates(stored, edges))
    return _budget_mean_recharge_m_s(sim, areas, ratio=ratio)


def _stored_recharge_forcing_m_s(sim: Run) -> pd.Series | None:
    """Return the station recharge forcing the run stores, stations averaged, in m/s.

    None when the run stores none under ``forcing/recharge``. Stations are
    averaged before the periods, as the forcing bridge averages them.
    """
    open_zarr = getattr(getattr(sim, "_catalog", None), "open_zarr", None)
    if not callable(open_zarr):
        return None
    store = open_zarr(sim.sim_id)
    try:
        forcing = store.root.get("forcing")
        group = forcing.get("recharge") if forcing is not None else None
        if group is None or not hasattr(group, "group_keys"):
            return None
        stations: list[pd.Series] = []
        for key in group.group_keys():
            node = group[key]
            if "timestamps" not in node or "values" not in node:
                continue
            stamps = np.asarray(node["timestamps"][:], dtype="int64").view("datetime64[ns]")
            values = np.asarray(node["values"][:], dtype="float64")
            # The data managers hand recharge over in mm/day.
            factor = factor_to_m_per_s(str(node.attrs.get("unit") or "mm/day"))
            stations.append(pd.Series(values * factor, index=pd.DatetimeIndex(stamps)))
    finally:
        store.close()
    if not stations:
        return None
    return pd.concat(stations, axis=1).mean(axis=1)


def _run_period_edges(sim: Run) -> pd.DatetimeIndex | None:
    """Return the run's ``n + 1`` period edges, or None when it carries no dates."""
    try:
        edges = sim.periods.edges
    except (AttributeError, KeyError, ValueError, RuntimeError, FileNotFoundError):
        edges = None
    if edges is not None and len(edges) >= 2:
        return pd.DatetimeIndex(edges)
    try:
        stamps = sim.time_index
    except (AttributeError, KeyError, ValueError, RuntimeError, FileNotFoundError):
        return None
    if stamps is None or len(stamps) < 2:
        return None
    return period_edges(stamps)


def _budget_mean_recharge_m_s(sim: Run, areas: np.ndarray, *, ratio: float) -> float:
    """Return the mean recharge rate of the budget the solver wrote, in m/s.

    Every timestep and every cell of finite area, unweighted. The last
    timestep alone is one day of a transient run: 4.5 times the mean on the
    daily Nancon run.
    """
    if not sim.has_field("recharge"):
        raise ValueError(
            f"stream comparison unavailable for {sim.sim_id}: a seepage threshold of "
            f"{ratio:g} is a fraction of the recharge the model received, and this run "
            "persisted no recharge budget. Enable it, or set tau_specific_ratio = 0 to "
            "read the purely geometric criterion."
        )
    from hydromodpy.core.stream_extent import CHUNK_ELEMENTS
    from hydromodpy.results.run.geographic import field_steps

    n_steps = sim.n_timesteps
    steps = list(range(int(n_steps))) if n_steps else [-1]
    per_pass = max(1, CHUNK_ELEMENTS // max(1, int(areas.size)))
    rates: list[np.ndarray] = []
    for first in range(0, len(steps), per_pass):
        chunk = steps[first : first + per_pass]
        stack = np.asarray(field_steps(sim, "recharge", chunk), dtype=float)
        for recharge_m3_s in stack.reshape(len(chunk), -1):
            usable = np.isfinite(recharge_m3_s) & np.isfinite(areas) & (areas > 0.0)
            rates.append(recharge_m3_s[usable] / areas[usable])
    try:
        return criterion_mean_recharge(rates)
    except ValueError as exc:
        raise ValueError(
            f"stream comparison unavailable for {sim.sim_id}: its recharge budget holds "
            "no finite value on a cell of finite area."
        ) from exc


def agreement_label(value: int) -> str:
    """Return the human-readable name of one agreement class."""
    try:
        return AGREEMENT_LABELS[int(value)]
    except KeyError as exc:
        raise ValueError(f"unknown stream agreement class {value!r}.") from exc
