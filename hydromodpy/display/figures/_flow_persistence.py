"""How often each cell carried accumulated drainage over a transient run.

Both persistence figures ask the same question of the same field: at how many
timesteps did a cell carry flow. They differ only in what they do with the
count, so the counting lives here and each figure keeps its own map.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd

    from hydromodpy.results.run import Run


FLOW_FIELD = "accumulation_flux"
"""Drain outflow accumulated downslope: positive means the cell carries flow."""

WHOLE_RUN_LABEL = "the whole run"
"""Name of the single cycle used when the run carries no usable time axis."""


def flowing_stack(sim: Run, *, threshold: float = 0.0) -> np.ndarray:
    """Return the ``(n_timesteps, n_cells)`` boolean record of who carried flow.

    A cell is flowing when its accumulated drain outflow is above
    ``threshold``. The default keeps the legacy criterion, strictly positive,
    which on this field means at least one upslope release reached the cell.
    """
    n_steps = int(sim.n_timesteps or 0)
    if n_steps == 0:
        raise ValueError(f"no timestep recorded for sim {sim.sim_id}")
    rows = [
        np.nan_to_num(np.asarray(sim.field(FLOW_FIELD, timestep=index), dtype="float64")).ravel()
        > float(threshold)
        for index in range(n_steps)
    ]
    return np.vstack(rows)


def cycles(sim: Run, n_steps: int) -> dict[str, np.ndarray]:
    """Return the timestep indices of each calendar year in the run.

    The legacy code cut the record into fixed blocks of twelve, which is a
    year only when the steps are months. Reading the time axis instead makes
    the classification mean the same thing at any timestep length. A run whose
    time axis cannot be built keeps one block over everything, and its label
    says so.
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
    into the following year: a thirteenth month, and a cycle one step long.
    The middle of the step falls inside the step under either spelling, which
    is what makes the calendar year it lands in the one the step belongs to.
    """
    import pandas as pd

    try:
        index = sim.time_index
    except RuntimeError:
        return None
    if index is None or len(index) < n_steps:
        return None
    stamps = pd.DatetimeIndex(index[:n_steps])
    if len(stamps) < 2:
        return stamps
    spans = (stamps[1:] - stamps[:-1]).to_numpy()
    return stamps - np.concatenate([spans[:1], spans]) / 2


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
