"""The resolved SFR reaches of a run: who drains into whom, and how long they are."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

_COLUMNS = ["network_id", "ifno", "rlen", "ustrf", "downstream"]

__all__ = ["sfr_reach_links"]


def sfr_reach_links(run: Run) -> pd.DataFrame:
    """Return the reach connectivity of ``run``, one row per reach.

    Columns: ``network_id``, ``ifno``, ``rlen`` (m), ``ustrf`` and ``downstream``
    (the ``ifno`` of every reach this one drains into, empty at an outlet).
    The frame is empty when the run built no stream network.

    A module function rather than a ``Run`` attribute: ``Run`` is capped at 50
    public attributes (``tests/unit/results/test_run_surface.py``).

    Raises
    ------
    KeyError
        When the run was sealed before the table stored the connectivity.
    """
    frame = run._catalog.backend.query(
        "SELECT * FROM sfr_reaches WHERE sim_id = ? ORDER BY network_id, ifno",
        [run.sim_id],
    )
    if frame.empty:
        return pd.DataFrame(columns=_COLUMNS)
    if "downstream" not in frame:
        raise KeyError(
            "the sfr_reaches table of this run holds no connectivity: it was sealed "
            "before the reaches stored the reaches they drain into. Run it again."
        )
    return frame[_COLUMNS].reset_index(drop=True)
