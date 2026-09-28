"""How often each cell flowed over a transient run, as the network criterion says.

Both persistence figures ask the same question of the same field: at how many
timesteps did a cell flow. They differ only in what they do with the count, so
the counting lives here and each figure keeps its own map.

"Flowing" is the definition the network criterion scores, and no other
(:func:`hydromodpy.core.stream_extent.flowing_cells`): a cell flows when it lies
in the downstream closure of the cells releasing above ``tau * R * A`` on the
criterion graph and, unless the visible flow is ``"0 L/s"``, when the routed
release reaching it is at least the visible flow. The counts are rebuilt by
:mod:`hydromodpy.results.derive.stream_extent`, per calendar year, and kept per
run so the two maps of one gallery read the stack once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.stream_criterion_defaults import STREAM_CRITERION_DEFAULTS
from hydromodpy.core.stream_extent import DEFAULT_VISIBLE_FLOW, VisibleFlow, parse_visible_flow
from hydromodpy.display.figures._memo import RunMemo
from hydromodpy.display.figures._stream_comparison import flowing_words
from hydromodpy.results.derive.stream_extent import (
    FLOW_FIELD,
    block_flow_counts,
    flow_geometry_from_run,
    run_step_edges,
    unavailable_reason_for_flow,
)

if TYPE_CHECKING:
    import pandas as pd

    from hydromodpy.core.stream_geometry import NetworkGeometry
    from hydromodpy.results.run import Run

__all__ = (
    "FLOW_FIELD",
    "WHOLE_RUN_LABEL",
    "CycleFlow",
    "cycle_flow",
    "cycles",
    "definition_note",
    "flow_geometry",
    "frame_note",
    "flow_unavailable_reason",
    "resolve_cycle",
    "span_label",
    "step_midpoints",
)

WHOLE_RUN_LABEL = "the whole run"
"""Name of the single cycle used when the run carries no usable time axis."""

_GEOMETRY_MEMO = RunMemo()
_FLOW_MEMO = RunMemo()


@dataclass(frozen=True, slots=True)
class CycleFlow:
    """The flowing counts of a run, one row per cycle, and how they were cut.

    ``flowing[i]`` counts, per cell, the timesteps of ``labels[i]`` it flowed;
    ``steps[i]`` are those timesteps. The cycles cover every timestep once.
    """

    labels: tuple[str, ...]
    steps: tuple[np.ndarray, ...]
    flowing: np.ndarray
    visible_flow: VisibleFlow
    tau_specific_ratio: float

    @property
    def n_timesteps(self) -> int:
        """Timesteps counted over all cycles."""
        return int(sum(block.size for block in self.steps))

    def block(self, label: str) -> tuple[np.ndarray, np.ndarray]:
        """Return the timesteps of one cycle and the per-cell flowing count."""
        row = self.labels.index(label)
        return self.steps[row], self.flowing[row]

    def total(self) -> np.ndarray:
        """Return the per-cell flowing count over the whole record."""
        return self.flowing.sum(axis=0)


def flow_unavailable_reason(sim: Run) -> str | None:
    """Return why the flowing cells of this run cannot be counted, or None."""
    return unavailable_reason_for_flow(sim)


def flow_geometry(
    sim: Run,
    *,
    tau_specific_ratio: float | None = None,
    diagonal_neighbors: bool | None = None,
) -> NetworkGeometry:
    """Return the criterion geometry of a run, memoised on the run and the knobs."""
    tau = _tau(tau_specific_ratio)
    diagonal = (
        STREAM_CRITERION_DEFAULTS.diagonal_neighbors
        if diagonal_neighbors is None
        else bool(diagonal_neighbors)
    )
    return _GEOMETRY_MEMO.get_or_build(
        sim,
        (tau, diagonal),
        lambda: flow_geometry_from_run(sim, tau_specific_ratio=tau, diagonal_neighbors=diagonal),
    )


def cycle_flow(
    sim: Run,
    *,
    visible_flow: str | None = None,
    tau_specific_ratio: float | None = None,
    diagonal_neighbors: bool | None = None,
) -> CycleFlow:
    """Return how many timesteps each cell flowed in each cycle of the run.

    ``visible_flow`` defaults to
    :data:`hydromodpy.core.stream_extent.DEFAULT_VISIBLE_FLOW`, the threshold
    the two-bound mode of the criterion reads a transient run with.
    """
    n_steps = int(sim.n_timesteps or 0)
    if n_steps == 0:
        raise ValueError(f"no timestep recorded for sim {sim.sim_id}")
    visible = parse_visible_flow(DEFAULT_VISIBLE_FLOW if visible_flow is None else visible_flow)
    tau = _tau(tau_specific_ratio)

    def build() -> CycleFlow:
        geometry = flow_geometry(sim, tau_specific_ratio=tau, diagonal_neighbors=diagonal_neighbors)
        blocks = cycles(sim, n_steps)
        counts = block_flow_counts(sim, geometry, list(blocks.values()), visible_flow=visible)
        return CycleFlow(
            labels=tuple(blocks),
            steps=tuple(blocks.values()),
            flowing=counts.flowing,
            visible_flow=visible,
            tau_specific_ratio=tau,
        )

    return _FLOW_MEMO.get_or_build(sim, (visible, tau, diagonal_neighbors), build)


def definition_note(flow: CycleFlow) -> str:
    """Return how "flowing" was cut, in words, for the note of a persistence map."""
    return flowing_words(flow.tau_specific_ratio, flow.visible_flow)


def frame_note(flow: CycleFlow, counted: np.ndarray | None) -> str:
    """Return the note under a persistence map: how "flowing" was cut, where cells count.

    ``counted`` is the catchment mask the key counts over, ``None`` when the
    key counts every cell of the mesh.
    """
    where = "in the catchment" if counted is not None else "over the whole mesh"
    return f"{definition_note(flow)}\ncells counted {where}"


def cycles(sim: Run, n_steps: int) -> dict[str, np.ndarray]:
    """Return the timestep indices of each calendar year in the run.

    A timestep belongs to the calendar year its middle falls in, the rule the
    network criterion sorts its years by. A run whose time axis cannot be
    built keeps one block over everything, and its label says so.
    """
    steps = np.arange(n_steps)
    years = cycle_years(sim, n_steps)
    if years is None:
        return {WHOLE_RUN_LABEL: steps}
    return {str(year): steps[years == year] for year in sorted(set(years.tolist()))}


def cycle_years(sim: Run, n_steps: int) -> np.ndarray | None:
    """Return the calendar year of each timestep, or None without a time axis."""
    middles = step_midpoints(sim, n_steps)
    if middles is None:
        return None
    return np.asarray(middles.year, dtype="int64")


def step_midpoints(sim: Run, n_steps: int) -> pd.DatetimeIndex | None:
    """Return the middle of each timestep, or None without a time axis.

    A run stamps a timestep with the END of its stress period, so a monthly
    January can be stamped either 31 January or 1 February, and reading the
    year off that stamp puts December of a run ending on a period boundary
    into the following year. The middle of the step falls inside the step
    under either spelling, which is what makes the calendar year it lands in
    the one the step belongs to.
    """
    import pandas as pd

    edges = run_step_edges(sim)
    if edges is None or edges.size < n_steps + 1:
        return None
    bounds = edges[: n_steps + 1]
    return pd.DatetimeIndex(bounds[:-1] + (bounds[1:] - bounds[:-1]) / 2)


def span_label(sim: Run, steps: np.ndarray) -> str:
    """Return ``"YYYY-MM to YYYY-MM"`` for a block of timesteps, or ``""``.

    Both maps collapse a stack of timesteps onto one image, and a reader
    comparing two of them is comparing two windows before anything else. The
    window therefore belongs in the title, spelled the same way in both.
    """
    if steps.size == 0:
        return ""
    middles = step_midpoints(sim, int(steps.max()) + 1)
    if middles is None:
        return ""
    first, last = middles[int(steps.min())], middles[int(steps.max())]
    if first.year == last.year and first.month == last.month:
        return f"{first:%Y-%m}"
    return f"{first:%Y-%m} to {last:%Y-%m}"


def resolve_cycle(blocks: dict[str, np.ndarray], cycle: str | None, *, figure: str) -> str:
    """Return the cycle to read: the one asked for, or the last complete one.

    The last cycle of a run is usually cut short by the end of the simulated
    window, and a reach classified over three months reads as perennial when
    it is only untested. The longest of the final cycles is preferred.
    """
    if cycle is not None:
        if str(cycle) not in blocks:
            raise ValueError(f"{figure}: no cycle {cycle!r}; this run has {', '.join(blocks)}")
        return str(cycle)
    labels = list(blocks)
    longest = max(len(blocks[name]) for name in labels)
    complete = [name for name in labels if len(blocks[name]) == longest]
    return complete[-1]


def _tau(value: float | None) -> float:
    """Return the seepage threshold ratio, the criterion's default when None."""
    return float(STREAM_CRITERION_DEFAULTS.tau_specific_ratio if value is None else value)
