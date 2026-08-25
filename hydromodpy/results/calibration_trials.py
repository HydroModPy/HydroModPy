"""Read the per-trial rows a calibration session recorded for one run.

``Run.has_table("calibration_iterations")`` answers by querying the catalog on
``sim_id``. Anything that decides a figure is available on that answer has to
read the rows back the same way, otherwise the gate and the reader disagree and
the figure reports itself available and then raises mid-render.

Two carriers hold those rows in this codebase, and both are legitimate: a
:class:`~hydromodpy.results.run.Run`, whose rows live in the catalog, and the
run-shaped adapter the calibration report builds from a session journal without
a catalog behind it. :func:`calibration_trials` resolves either into the same
frame, so a figure has one call to make and no shape to test for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

__all__ = ("calibration_trials",)

_TABLE = "calibration_iterations"


def _rows_carried_by(source: Any) -> pd.DataFrame | None:
    """Return the rows a run-shaped adapter carries itself, if it carries any."""
    rows = getattr(source, "calibration_iterations", None)
    if rows is None:
        return None
    return rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows))


def _rows_in_the_catalog(run: Run) -> pd.DataFrame:
    """Return the trials of the calibration this run belongs to.

    Keyed on the SESSION, not on the run. A promoted run carries the single row
    of the trial it was promoted from, and a figure about a calibration wants
    the calibration: read by sim_id, the crossing of two distances and the trace
    of a bisection both come back as one point.

    A run that belongs to no session falls back to its own rows, which is what
    a run-shaped adapter with a hand-built table gets.
    """
    backend = run._catalog.backend  # noqa: SLF001 - same package, one reader
    sid = run._sim_id  # noqa: SLF001
    sessions = backend.query(
        f"SELECT DISTINCT session_id FROM {_TABLE} WHERE sim_id = ?",  # noqa: S608
        [sid],
    )
    if sessions.empty:
        return backend.query(
            f"SELECT * FROM {_TABLE} WHERE sim_id = ? ORDER BY iteration",  # noqa: S608
            [sid],
        )
    return backend.query(
        f"SELECT * FROM {_TABLE} WHERE session_id IN "  # noqa: S608
        f"(SELECT DISTINCT session_id FROM {_TABLE} WHERE sim_id = ?) "
        "ORDER BY session_id, iteration",
        [sid],
    )


def calibration_trials(source: Run | Any, *, session_id: str | None = None) -> pd.DataFrame:
    """Return the calibration iterations recorded for ``source``.

    Parameters
    ----------
    source
        A run, or the run-shaped adapter the calibration report builds.
    session_id
        Keep only the trials of that session. A source whose rows carry no
        session column is returned whole: it already is one session.

    Raises
    ------
    ValueError
        When no trial can be read. The message says which of the two cases it
        is, because "no session ran" and "the session recorded nothing" call
        for different answers from the reader.
    """
    frame = _rows_carried_by(source)
    if frame is None:
        if not hasattr(source, "_catalog"):
            raise ValueError(
                f"no calibration trial can be read from {type(source).__name__}: "
                f"it carries no {_TABLE} and is not a run."
            )
        frame = _rows_in_the_catalog(source)

    if session_id is not None and "session_id" in frame.columns:
        frame = frame[frame["session_id"].astype(str) == str(session_id)]

    if frame.empty:
        scope = "" if session_id is None else f" for session {session_id!r}"
        raise ValueError(f"no trial recorded{scope} by this calibration.")
    return frame.reset_index(drop=True)
