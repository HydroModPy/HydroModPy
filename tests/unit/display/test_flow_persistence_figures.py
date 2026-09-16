"""Persistence and intermittence are counted per cycle, not per fixed block.

Three cells over two calendar years of monthly steps: one carries flow at
every step, one only in winter, one never. The answers are written here
rather than read back from the figure, because the whole point of both maps
is the count, and a count is either right or wrong.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures._flow_persistence import cycles, flowing_stack
from hydromodpy.display.figures.flow_intermittence_map import FlowIntermittenceMap
from hydromodpy.display.figures.flow_persistence_map import FlowPersistenceMap

PERENNIAL, SEASONAL, DRY = 0, 1, 2
"""Cell indices: flowing always, flowing in winter only, never flowing."""

WINTER_MONTHS = (1, 2, 3, 11, 12)
"""Months the seasonal cell carries flow: five of twelve, both years."""


class _Run:
    """Three square cells in a row, carrying a monthly accumulated flux."""

    sim_id = "sim-persistence"
    name = "nancon"

    def __init__(
        self, n_years: int = 2, *, with_time: bool = True, exclusive_bounds: bool = False
    ) -> None:
        # A timestep is stamped with the end of its stress period, which a
        # solver spells either as the last day of the month or as the first
        # day of the next one. Both are the same twelve months.
        freq = "MS" if exclusive_bounds else "ME"
        start = "2001-02-01" if exclusive_bounds else "2001-01-31"
        self._index = pd.date_range(start, periods=12 * n_years, freq=freq)
        self._with_time = with_time
        stack = np.zeros((len(self._index), 3), dtype="float64")
        stack[:, PERENNIAL] = 1.0e-3
        for step, stamp in enumerate(self._index):
            if stamp.month in WINTER_MONTHS:
                stack[step, SEASONAL] = 1.0e-5
        self._stack = stack
        self.n_timesteps = len(self._index)
        self.mesh = SimpleNamespace(
            vertices=np.asarray([[x, y, 0.0] for y in (0.0, 1.0) for x in range(4)], dtype=float),
            face_node_connectivity=np.asarray([[i, i + 1, 5 + i, 4 + i] for i in range(3)]),
        )

    @property
    def time_index(self) -> pd.DatetimeIndex:
        if not self._with_time:
            raise RuntimeError("simulation has no n_timesteps recorded")
        return self._index

    def has_field(self, variable: str, **_) -> bool:
        return variable == "accumulation_flux"

    def field(self, variable: str, timestep: int = -1, **_) -> np.ndarray:
        if variable != "accumulation_flux":
            raise KeyError(variable)
        return self._stack[int(timestep)]


def _axes():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt.subplots()[1]


def _drawn(ax) -> np.ndarray:
    """Values the face collection was handed, masked where nothing was drawn."""
    return np.asarray(ax.collections[0].get_array())


def test_the_flowing_record_counts_every_step_above_the_threshold() -> None:
    flowing = flowing_stack(_Run())
    assert flowing.shape == (24, 3)
    assert flowing[:, PERENNIAL].all()
    assert flowing[:, SEASONAL].sum() == 2 * len(WINTER_MONTHS)
    assert not flowing[:, DRY].any()


def test_a_threshold_above_the_seasonal_flux_silences_that_cell() -> None:
    flowing = flowing_stack(_Run(), threshold=1.0e-4)
    assert flowing[:, PERENNIAL].all()
    assert not flowing[:, SEASONAL].any()


def test_cycles_follow_the_calendar_and_not_a_fixed_block_length() -> None:
    blocks = cycles(_Run(n_years=2), 24)
    assert list(blocks) == ["2001", "2002"]
    assert [len(steps) for steps in blocks.values()] == [12, 12]


def test_a_period_end_on_the_next_month_does_not_open_a_thirteenth_cycle() -> None:
    """The December of a run stamped on period bounds belongs to its own year."""
    blocks = cycles(_Run(n_years=2, exclusive_bounds=True), 24)
    assert list(blocks) == ["2001", "2002"]
    assert [len(steps) for steps in blocks.values()] == [12, 12]


def test_a_run_without_a_time_axis_keeps_one_block_and_says_so() -> None:
    blocks = cycles(_Run(with_time=False), 24)
    assert list(blocks) == ["the whole run"]
    assert len(blocks["the whole run"]) == 24


def test_the_persistence_share_is_the_fraction_of_steps_carrying_flow() -> None:
    ax = _axes()
    FlowPersistenceMap().render(_Run(), ax, overlays=())
    drawn = _drawn(ax)
    assert drawn[PERENNIAL] == pytest.approx(100.0)
    assert drawn[SEASONAL] == pytest.approx(100.0 * len(WINTER_MONTHS) / 12.0)
    assert not np.isfinite(drawn[DRY])


def test_the_persistence_share_can_be_read_over_one_cycle_like_intermittence() -> None:
    """Same window, same cells: the seasonal cell flows five steps of twelve."""
    ax = _axes()
    FlowPersistenceMap().render(_Run(), ax, cycle="2002", overlays=())
    drawn = _drawn(ax)
    assert drawn[PERENNIAL] == pytest.approx(100.0)
    assert drawn[SEASONAL] == pytest.approx(100.0 * len(WINTER_MONTHS) / 12.0)
    assert not np.isfinite(drawn[DRY])


def test_persistence_refuses_a_cycle_the_run_does_not_have() -> None:
    with pytest.raises(ValueError, match="no cycle"):
        FlowPersistenceMap().render(_Run(), _axes(), cycle="1999", overlays=())


def test_intermittence_separates_the_cell_that_stops_from_the_one_that_does_not() -> None:
    ax = _axes()
    FlowIntermittenceMap().render(_Run(), ax, cycle="2002", overlays=())
    drawn = _drawn(ax)
    assert drawn[PERENNIAL] == pytest.approx(0.0)
    assert drawn[SEASONAL] == pytest.approx(1.0)
    assert not np.isfinite(drawn[DRY])


def test_intermittence_refuses_a_cycle_the_run_does_not_have() -> None:
    with pytest.raises(ValueError, match="no cycle"):
        FlowIntermittenceMap().render(_Run(), _axes(), cycle="1999", overlays=())


def test_neither_map_applies_to_a_single_timestep() -> None:
    sim = _Run()
    sim.n_timesteps = 1
    assert "single timestep" in (FlowIntermittenceMap().unavailable_reason(sim) or "")
    assert "more than one timestep" in (FlowPersistenceMap().unavailable_reason(sim) or "")
