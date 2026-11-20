"""The resolved SFR reaches of a run: who drains into whom, and how long they are."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from hydromodpy.results.run.tables import read_run_table

if TYPE_CHECKING:
    from hydromodpy.results.run.view import Run

_COLUMNS = ["reach_id", "network_id", "reach", "rlen", "ustrf", "downstream"]

__all__ = ["sfr_reach_links"]


def sfr_reach_links(run: Run) -> pd.DataFrame:
    """Return the reach connectivity of ``run``, one row per reach.

    Columns: ``reach_id`` (the ``station_id`` of the reach in ``timeseries``),
    ``network_id``, ``reach``, ``rlen`` (m), ``ustrf`` and ``downstream`` (the
    ``reach`` of every reach this one drains into, empty at an outlet). A reach
    number starts at 1, as the TOML writes it. The frame is empty when the run
    built no stream network.

    A module function rather than a ``Run`` attribute: ``Run`` is capped at 50
    public attributes (``tests/unit/results/test_run_surface.py``).
    """
    frame = read_run_table(run, "sfr_reaches")
    if frame.empty:
        return pd.DataFrame(columns=_COLUMNS)
    return frame.sort_values(["network_id", "reach"], kind="stable")[_COLUMNS].reset_index(
        drop=True
    )
