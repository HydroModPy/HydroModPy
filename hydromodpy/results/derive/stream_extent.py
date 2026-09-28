"""Rebuild the flow extents of a finished transient run, as the criterion reads them.

A transient run holds one release field per timestep. Where the network flowed,
how often, and the maximal and minimal extents the two-bound mode of the
network criterion scores, are all counts over that stack. This module counts
them on a stored run, through the one definition of "flowing" of
:mod:`hydromodpy.core.stream_extent`, on the criterion graph that
:func:`hydromodpy.results.derive.stream_network.network_comparison_from_run`
rebuilds. A figure drawn from here therefore cuts the network where a trial
cuts it: seepage above ``tau * R * A``, closed downstream on the conditioned
graph, and above the visible flow when one is set.

The stack is read a chunk of timesteps at a time and only the per-block counts
are kept, so a daily run on a fine mesh never sits whole in memory.

Nothing here scores. The distances belong to the calibration layer; this
module only rebuilds the masks and the cells they share with the maps.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from hydromodpy.core.stream_criterion_defaults import (
    STREAM_CRITERION_DEFAULTS,
    ObservedRasterization,
)
from hydromodpy.core.stream_extent import (
    CHUNK_ELEMENTS,
    DEFAULT_VISIBLE_FLOW,
    Bound,
    CalendarYears,
    ExtentMasks,
    VisibleFlow,
    YearlyFlowCounts,
    calendar_years,
    extent_masks,
    extent_step_problems,
    flowing_cells,
    parse_visible_flow,
)
from hydromodpy.core.stream_geometry import CriterionSupports, NetworkGeometry, criterion_supports
from hydromodpy.results.derive.stream_network import (
    network_comparison_from_run,
    unavailable_reason_for_comparison,
)

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

__all__ = (
    "FLOW_FIELD",
    "GRAPH_ROLES",
    "MAXIMAL_ROLE",
    "MINIMAL_ROLE",
    "BlockFlowCounts",
    "NetworkExtents",
    "block_flow_counts",
    "flow_geometry_from_run",
    "flowing_share",
    "graph_role",
    "network_extents_from_run",
    "run_step_edges",
    "scored_cells",
    "unavailable_reason_for_extents",
    "unavailable_reason_for_flow",
)

FLOW_FIELD = "release_flux"
"""The per-cell release the criterion cuts the network from, in m3/s."""

MAXIMAL_ROLE = "reference"
"""The stored network standing for the maximal map: every mapped reach."""

MINIMAL_ROLE = "reference_permanent"
"""The stored network standing for the minimal map: the permanent reaches."""

GRAPH_ROLES: tuple[str, ...] = (MAXIMAL_ROLE, "generated")
"""The networks the criterion graph can be rebuilt on, in order of preference.

The graph, the seepage threshold and the outlet do not depend on the map: a
map only enters the distances. A run with no mapped network but a network
thresholded from its DEM therefore still counts its flowing cells the way the
criterion would.
"""


def graph_role(sim: Run) -> str | None:
    """Return the stored network the criterion graph is rebuilt on, or None."""
    for role in GRAPH_ROLES:
        if sim.has_hydrographic_network(role):
            return role
    return None


def unavailable_reason_for_flow(
    sim: Run,
    *,
    tau_specific_ratio: float = STREAM_CRITERION_DEFAULTS.tau_specific_ratio,
) -> str | None:
    """Return why the flowing cells of this run cannot be counted, or None.

    Counting needs the release field and the criterion graph, which is built
    on a stored network, the mesh and its CRS; a positive ``tau_specific_ratio``
    also needs the recharge budget the threshold is a fraction of.
    """
    if not sim.has_field(FLOW_FIELD):
        return (
            "run has no per-cell release_flux: set [simulation.results.derived] release_flux = true"
        )
    role = graph_role(sim)
    if role is None:
        return (
            "run carries neither a 'reference' nor a 'generated' hydrographic network, "
            "so the criterion graph that says which cells flow cannot be rebuilt"
        )
    reason = unavailable_reason_for_comparison(sim, role=role)
    if reason is not None:
        return reason
    if float(tau_specific_ratio) > 0.0 and not sim.has_field("recharge"):
        return (
            f"a seepage threshold of tau = {float(tau_specific_ratio):g} is a fraction of the "
            "recharge the model received, and this run persisted no recharge budget"
        )
    return None


def unavailable_reason_for_extents(
    sim: Run,
    *,
    tau_specific_ratio: float = STREAM_CRITERION_DEFAULTS.tau_specific_ratio,
    require_minimal: bool = True,
    scoring_window: tuple[Any, Any] | None = None,
) -> str | None:
    """Return why the two extents of this run cannot be drawn, or None.

    The extents are read over the complete calendar years of a transient run
    that ``scoring_window`` holds, against the maximal map (``reference``) and,
    with ``require_minimal``, the minimal map (``reference_permanent``) the run
    stored beside it.
    """
    n_steps = int(getattr(sim, "n_timesteps", 0) or 0)
    if n_steps < 2:
        return (
            "a steady run holds one state; the maximal and minimal extents are counted "
            "over the timesteps of a transient run"
        )
    if not sim.has_hydrographic_network(MAXIMAL_ROLE):
        return f"run carries no {MAXIMAL_ROLE!r} hydrographic network: no maximal map to draw"
    if require_minimal and not sim.has_hydrographic_network(MINIMAL_ROLE):
        return (
            f"run carries one map only: no {MINIMAL_ROLE!r} hydrographic network, the "
            "permanent reaches its hydrography source writes when it says which reaches "
            "flow all year"
        )
    reason = unavailable_reason_for_flow(sim, tau_specific_ratio=tau_specific_ratio)
    if reason is not None:
        return reason
    edges = run_step_edges(sim)
    if edges is None:
        return "run carries no time axis, so its timesteps cannot be sorted into years"
    years = calendar_years(edges, window=scoring_window)
    if not years.years:
        touched = ", ".join(str(year) for year in years.incomplete) or "none"
        if years.outside_window:
            left_out = ", ".join(str(year) for year in years.outside_window)
            return (
                f"the scoring window holds no complete calendar year of the run "
                f"(it leaves out {left_out}; the run only touches {touched} besides)"
            )
        return f"run covers no complete calendar year (it touches {touched})"
    return None


def run_step_edges(sim: Run) -> np.ndarray | None:
    """Return the ``n_timesteps + 1`` bounds of a run's timesteps, or None.

    A run stamps each timestep with the END of its period. The first bound is
    the start of the run window the catalog recorded; without it the first
    period is taken as long as the second, the rule the calibration applies
    when the time grid is missing. None when the run has no usable time axis.
    """
    import pandas as pd

    n_steps = int(getattr(sim, "n_timesteps", 0) or 0)
    if n_steps < 1:
        return None
    try:
        index = sim.time_index
    except RuntimeError:
        return None
    if index is None or len(index) < n_steps:
        return None
    stamps = pd.DatetimeIndex(index[:n_steps])
    if stamps.tz is not None:
        stamps = stamps.tz_localize(None)
    start = _window_start(sim, stamps[0])
    if start is None:
        if n_steps < 2:
            return None
        start = stamps[0] - (stamps[1] - stamps[0])
    edges = stamps.insert(0, pd.Timestamp(start))
    return edges.to_numpy(dtype="datetime64[ns]")


def _window_start(sim: Run, first_stamp: Any) -> Any:
    """Return the start of the run window the catalog recorded, or None.

    Read on the wall clock it was written with, as ``Run.time_index`` reads
    it: converted to UTC instead, a run starting on 1 January in Paris would
    start on 31 December and its first year would still be whole, but a run
    in a zone west of Greenwich would lose its first year.
    """
    import pandas as pd

    loader = getattr(sim, "_load_row", None)
    if not callable(loader):
        return None
    start = loader().get("period_start")
    if start is None or pd.isna(start):
        return None
    stamp = pd.Timestamp(start)
    if stamp.tz is not None:
        stamp = stamp.tz_localize(None)
    return stamp if stamp < pd.Timestamp(first_stamp) else None


def flow_geometry_from_run(
    sim: Run,
    *,
    role: str | None = None,
    tau_specific_ratio: float = STREAM_CRITERION_DEFAULTS.tau_specific_ratio,
    diagonal_neighbors: bool = STREAM_CRITERION_DEFAULTS.diagonal_neighbors,
    observed_rasterization: ObservedRasterization = (
        STREAM_CRITERION_DEFAULTS.observed_rasterization
    ),
    weighting: Literal["cell", "area"] = "cell",
    observed_position_accuracy_m: float | None = None,
) -> NetworkGeometry:
    """Return the criterion geometry of a run: graph, seepage threshold and outlet.

    ``role`` picks the stored network the geometry is built on; None takes
    the first of :data:`GRAPH_ROLES` the run carries. The graph, the threshold
    and the outlet are the same whatever the network, so the choice only
    decides which map ``geometry.observed`` holds. ``observed_rasterization``,
    ``weighting`` and ``observed_position_accuracy_m`` only shape that map and
    its snap, and take the criterion's defaults.
    """
    chosen = graph_role(sim) if role is None else role
    if chosen is None:
        raise ValueError(
            f"flowing cells unavailable for {sim.sim_id}: "
            f"{unavailable_reason_for_flow(sim, tau_specific_ratio=tau_specific_ratio)}"
        )
    return network_comparison_from_run(
        sim,
        role=chosen,
        tau_specific_ratio=float(tau_specific_ratio),
        diagonal_neighbors=bool(diagonal_neighbors),
        observed_rasterization=observed_rasterization,
        weighting=weighting,
        observed_position_accuracy_m=observed_position_accuracy_m,
    ).geometry


@dataclass(frozen=True, slots=True)
class BlockFlowCounts:
    """How many timesteps each cell flowed, per block of timesteps.

    ``flowing`` and ``seepage`` are ``(n_blocks, n_cells)`` int32 counts, the
    second counting the timesteps a flowing cell was a source itself.
    """

    n_steps: np.ndarray
    flowing: np.ndarray
    seepage: np.ndarray
    visible_flow: VisibleFlow


def block_flow_counts(
    sim: Run,
    geometry: NetworkGeometry,
    blocks: Sequence[np.ndarray],
    *,
    visible_flow: str | VisibleFlow = DEFAULT_VISIBLE_FLOW,
    chunk_elements: int = CHUNK_ELEMENTS,
) -> BlockFlowCounts:
    """Count, per block of timesteps and per cell, the timesteps the cell flows.

    "Flows" is :func:`hydromodpy.core.stream_extent.flowing_cells` on the
    criterion ``geometry``: in the downstream closure of the cells releasing
    above their threshold and, unless ``visible_flow`` is ``"0 L/s"``, carrying
    at least that routed discharge. The release field is read at most
    ``chunk_elements`` values at a time.
    """
    visible = parse_visible_flow(visible_flow)
    n_cells = int(geometry.metric.graph.active.size)
    per_pass = max(1, int(chunk_elements) // max(1, n_cells))
    flowing = np.zeros((len(blocks), n_cells), dtype=np.int32)
    seepage = np.zeros((len(blocks), n_cells), dtype=np.int32)
    for row, block in enumerate(blocks):
        steps = np.asarray(block, dtype=np.int64).reshape(-1)
        for first in range(0, steps.size, per_pass):
            chunk = steps[first : first + per_pass]
            state = flowing_cells(
                _release_rows(sim, chunk, n_cells),
                threshold_m3_s=geometry.threshold_m3_s,
                metric=geometry.metric,
                visible_flow=visible,
                outlet=geometry.outlet,
            )
            flowing[row] += state.flowing.sum(axis=0, dtype=np.int32)
            seepage[row] += state.seepage.sum(axis=0, dtype=np.int32)
    n_steps = np.asarray([np.asarray(block).size for block in blocks], dtype=np.int64)
    return BlockFlowCounts(n_steps=n_steps, flowing=flowing, seepage=seepage, visible_flow=visible)


def flowing_share(
    sim: Run,
    geometry: NetworkGeometry,
    *,
    visible_flow: str | VisibleFlow = DEFAULT_VISIBLE_FLOW,
    chunk_elements: int = CHUNK_ELEMENTS,
) -> np.ndarray:
    """Return, per cell, the share of the run's timesteps the cell flows.

    "Flows" is the definition of :func:`block_flow_counts`, on the criterion
    ``geometry``, over every timestep of the run as one block. The share is
    unweighted: a timestep counts once whatever its length. NaN on the cells
    the criterion graph leaves inactive.
    """
    n_steps = max(1, int(getattr(sim, "n_timesteps", 0) or 0))
    counts = block_flow_counts(
        sim,
        geometry,
        [np.arange(n_steps)],
        visible_flow=visible_flow,
        chunk_elements=chunk_elements,
    )
    share = counts.flowing[0].astype(float) / float(n_steps)
    share[~np.asarray(geometry.metric.graph.active, dtype=bool)] = np.nan
    return share


def _release_rows(sim: Run, steps: np.ndarray, n_cells: int) -> np.ndarray:
    """Return the release field at ``steps`` as a ``(len(steps), n_cells)`` stack."""
    rows = np.empty((steps.size, n_cells), dtype=float)
    for position, step in enumerate(steps.tolist()):
        values = np.asarray(sim.field(FLOW_FIELD, timestep=int(step)), dtype=float).reshape(-1)
        if values.size != n_cells:
            raise ValueError(
                f"{FLOW_FIELD} holds {values.size} cells at timestep {step} and the mesh "
                f"holds {n_cells}; they were not written for the same run."
            )
        rows[position] = values
    return rows


@dataclass(frozen=True, slots=True)
class NetworkExtents:
    """The maximal and minimal extents of a transient run, beside the two maps.

    ``geometry`` is the criterion geometry built on the maximal map.
    ``maximal_observed`` is the union of the maximal and minimal maps, as the
    criterion scores it; ``minimal_observed`` is the minimal map, or None when
    the run stored none. Both are the maps the criterion scores: snapped when
    the run's ``[geographic.snap_streams]`` applies the snap.
    ``frac_minimal_outside_maximal`` is the share of the minimal map, on the
    scored cells (:func:`scored_cells`), that the maximal map does not cover.
    """

    geometry: NetworkGeometry
    maximal_observed: np.ndarray
    minimal_observed: np.ndarray | None
    frac_minimal_outside_maximal: float
    years: CalendarYears
    counts: YearlyFlowCounts
    masks: ExtentMasks
    visible_flow: VisibleFlow
    maximal_flowing_steps: int
    minimal_dry_steps: int
    year_quorum: float
    tau_specific_ratio: float

    def simulated(self, bound: Bound, *, year: int | None = None) -> np.ndarray:
        """Return one simulated extent: climatological, or that ``year``'s."""
        return self.masks.network(
            bound, threshold_m3_s=self.geometry.threshold_m3_s, year=year
        ).network

    def observed(self, bound: Bound) -> np.ndarray:
        """Return the map one bound is compared to."""
        if bound == "maximal":
            return self.maximal_observed
        if self.minimal_observed is None:
            raise ValueError("this run stored no minimal map to compare the minimal extent to.")
        return self.minimal_observed

    def supports(self, bound: Bound, *, year: int | None = None) -> CriterionSupports:
        """Return the valid, excess and missing cells of one bound, in the catchment."""
        return criterion_supports(
            simulated=self.masks.network(
                bound, threshold_m3_s=self.geometry.threshold_m3_s, year=year
            ),
            observed=self.observed(bound),
            catchment=scored_cells(self.geometry),
            active=self.geometry.metric.graph.active,
        )


def network_extents_from_run(
    sim: Run,
    *,
    maximal_flowing_steps: int = 1,
    minimal_dry_steps: int = 1,
    year_quorum: float = 0.5,
    visible_flow: str | VisibleFlow = DEFAULT_VISIBLE_FLOW,
    tau_specific_ratio: float = STREAM_CRITERION_DEFAULTS.tau_specific_ratio,
    diagonal_neighbors: bool = STREAM_CRITERION_DEFAULTS.diagonal_neighbors,
    observed_rasterization: ObservedRasterization = (
        STREAM_CRITERION_DEFAULTS.observed_rasterization
    ),
    weighting: Literal["cell", "area"] = "cell",
    observed_position_accuracy_m: float | None = None,
    scoring_window: tuple[Any, Any] | None = None,
    chunk_elements: int = CHUNK_ELEMENTS,
) -> NetworkExtents:
    """Rebuild the maximal and minimal extents of a transient run.

    The rules are those of ``[calibration.outputs.<n>.extent]``, counted in
    timesteps over the complete calendar years of the run: the maximal extent
    holds the cells flowing at least ``maximal_flowing_steps`` timesteps of a
    year, the minimal one the cells flowing at every timestep but at most
    ``minimal_dry_steps``, and a cell enters a climatological extent when it
    meets its rule in at least ``year_quorum`` of the years. The criterion
    settings of the output (``tau_specific_ratio``, ``diagonal_neighbors``,
    ``observed_rasterization``, ``weighting``, ``observed_position_accuracy_m``)
    build both maps and the graph, with the criterion's defaults.
    ``scoring_window`` is the ``(start, end)`` of the calibration's window,
    naive, either bound None when open: only the complete years it holds are
    counted, as the trial counts them, and a spin-up year outside it is left
    out of the extents and of the quorum.

    The minimal map is read when the run stored one; the maximal map is then
    the union of the two, as the criterion scores it. Refused by name when the
    run is steady, lacks a maximal map, covers no complete year, or when the
    step rules cannot be read on its years.
    """
    reason = unavailable_reason_for_extents(
        sim,
        tau_specific_ratio=tau_specific_ratio,
        require_minimal=False,
        scoring_window=scoring_window,
    )
    if reason is not None:
        raise ValueError(f"network extents unavailable for {sim.sim_id}: {reason}")
    edges = run_step_edges(sim)
    if edges is None:
        raise ValueError(f"network extents unavailable for {sim.sim_id}: run has no time axis.")
    years = calendar_years(edges, window=scoring_window)
    problems = extent_step_problems(
        years.n_steps,
        maximal_flowing_steps=maximal_flowing_steps,
        minimal_dry_steps=minimal_dry_steps,
    )
    if problems:
        raise ValueError(
            f"network extents unavailable for {sim.sim_id}: " + "; ".join(problems) + "."
        )

    settings: dict[str, Any] = {
        "tau_specific_ratio": tau_specific_ratio,
        "diagonal_neighbors": diagonal_neighbors,
        "observed_rasterization": observed_rasterization,
        "weighting": weighting,
        "observed_position_accuracy_m": observed_position_accuracy_m,
    }
    geometry = flow_geometry_from_run(sim, role=MAXIMAL_ROLE, **settings)
    maximal = np.asarray(geometry.observed, dtype=bool)
    minimal: np.ndarray | None = None
    outside = float("nan")
    if sim.has_hydrographic_network(MINIMAL_ROLE):
        minimal = np.asarray(
            flow_geometry_from_run(sim, role=MINIMAL_ROLE, **settings).observed,
            dtype=bool,
        )
        outside = _share_outside(minimal, maximal, scored_cells(geometry))
        maximal = maximal | minimal

    visible = parse_visible_flow(visible_flow)
    blocks = block_flow_counts(
        sim, geometry, years.steps, visible_flow=visible, chunk_elements=chunk_elements
    )
    counts = YearlyFlowCounts(
        years=years.years, n_steps=years.n_steps, flowing=blocks.flowing, seepage=blocks.seepage
    )
    masks = extent_masks(
        counts,
        maximal_flowing_steps=maximal_flowing_steps,
        minimal_dry_steps=minimal_dry_steps,
        year_quorum=year_quorum,
    )
    return NetworkExtents(
        geometry=geometry,
        maximal_observed=maximal,
        minimal_observed=minimal,
        frac_minimal_outside_maximal=outside,
        years=years,
        counts=counts,
        masks=masks,
        visible_flow=visible,
        maximal_flowing_steps=int(maximal_flowing_steps),
        minimal_dry_steps=int(minimal_dry_steps),
        year_quorum=float(year_quorum),
        tau_specific_ratio=float(tau_specific_ratio),
    )


def scored_cells(geometry: NetworkGeometry) -> np.ndarray:
    """Return the cells the criterion scores: catchment, active, not a water body.

    This is the ``keep`` mask of :func:`criterion_supports`. The share of the
    minimal map outside the maximal one and the valid, excess and missing
    counts of :meth:`NetworkExtents.supports` are both read on it.
    """
    keep = np.asarray(geometry.catchment, dtype=bool).reshape(-1) & np.asarray(
        geometry.metric.graph.active, dtype=bool
    ).reshape(-1)
    if geometry.excluded is not None:
        keep = keep & ~np.asarray(geometry.excluded, dtype=bool).reshape(-1)
    return keep


def _share_outside(inner: np.ndarray, outer: np.ndarray, within: np.ndarray) -> float:
    """Return the share of ``inner`` inside ``within`` that ``outer`` leaves out."""
    scored = np.asarray(inner, dtype=bool) & np.asarray(within, dtype=bool)
    if not scored.any():
        return float("nan")
    return float(np.mean(~np.asarray(outer, dtype=bool)[scored]))
