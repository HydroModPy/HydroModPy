"""Records of a run or a session that more than one special figure reads or marks.

The station a run was scored at, the completed trials of a session, the two marks of
the returned and of the acceptable trials, and the particles that moved with their
travel times. The returned trial and the acceptable cost of a phase come from
``results/session/acceptance.py``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.display.frames.series import scores
from hydromodpy.display.subject import FigureNotApplicable, read_table
from hydromodpy.display.theme import Theme, unit_text
from hydromodpy.results.run.particles import moving_tracks

STAR_SIZE = 65
RING_SIZE = 40


def scored_station(run: Any, variable: str, station: str | None) -> str | None:
    """Return ``station``, else the station of the first score of ``variable``, else None."""
    if station is not None:
        return station
    rows = scores(run, [(variable, None)])
    return None if rows.empty else str(rows["station"].iloc[0])


def completed_trials(session: Any) -> pd.DataFrame:
    """Return the completed trials of a session that hold a cost, in trial order."""
    trials = read_table(session, "trials")
    return trials[(trials["status"] == "completed") & trials["cost"].notna()].sort_values("trial")


def axis_label(name: str, units: str | None) -> str:
    """Return ``name (unit)`` with the unit set in the theme text, or ``name`` alone."""
    unit = unit_text(units or "")
    return f"{name} ({unit})" if unit else name


def mark_returned(ax: Any, x: Any, y: Any, theme: Theme) -> None:
    """Mark the trial the session returned with a star."""
    ax.scatter([x], [y], marker="*", s=STAR_SIZE, color=theme.roles["best"],
               edgecolors=theme.ink, linewidths=theme.line_width, zorder=5,
               label="Returned trial")  # fmt: skip


def ring_acceptable(
    ax: Any, x: Any, ys: list[Any], cost: Any, threshold: float | None, theme: Theme
) -> None:
    """Ring each point of the ``ys`` curves whose cost is at or under ``threshold``.

    The ring has one legend entry that gives the threshold. Without a threshold nothing is
    ringed.
    """
    if threshold is None:
        return
    kept = np.asarray(cost, float) <= threshold
    if not kept.any():
        return
    ax.scatter(
        np.tile(np.asarray(x, float)[kept], len(ys)),
        np.concatenate([np.asarray(y, float)[kept] for y in ys]),
        s=RING_SIZE, facecolors="none", edgecolors=theme.ink, linewidths=theme.line_width,
        zorder=4, label=f"Cost under {threshold:.3g}",
    )  # fmt: skip


def moving_particles(run: Any) -> tuple[list[np.ndarray], np.ndarray]:
    """Return the ``(x, y)`` path of each particle that moved and its travel time in years.

    A particle that never left its release cell, or that has no time, is left out.
    """
    paths, years = moving_tracks(run)
    if not paths:
        raise FigureNotApplicable(
            f"Run {run.name!r} holds no particle that moved with a travel time, so no "
            "pathline exists."
        )
    return [path[:, :2] for path in paths], years
