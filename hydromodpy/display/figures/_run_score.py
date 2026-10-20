"""The scores a run recorded, as a comparison figure prints them.

A figure never scores a run itself: the run is scored once, on ``[metrics]
window``, and the figure prints that score with its window and its sample
count. A score computed again on the figure's own pairs would read another
sample and disagree with the one the run is ranked on.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.results.derive.time_alignment import time_method_for
from hydromodpy.results.run.sealed import metrics_of

if TYPE_CHECKING:
    from hydromodpy.results.run import Run


@dataclass(frozen=True)
class RunScore:
    """The scores of one run at one station, on the window they were read on."""

    station: str
    variable: str
    values: dict[str, float]
    """Each finite score, by metric name."""
    start: date
    end: date
    """Last day scored, included."""
    n: int

    def window_line(self) -> str:
        """Say where the scores were read: window and sample count."""
        return f"scored {self.start:%Y-%m-%d} to {self.end:%Y-%m-%d}, n {self.n}"

    def scored(
        self, simulated: pd.DatetimeIndex, first_start: pd.Timestamp | None = None
    ) -> np.ndarray:
        """Say which stamps of a simulated series the score read.

        A mean over a period counts when the whole period lies in the window,
        a state when its stamp does, as the run's own rule reads them. A period
        starts on the stamp before its own; the first one starts on
        *first_start*, and is not counted when that is unknown.
        """
        lo = pd.Timestamp(datetime.combine(self.start, time.min))
        hi = pd.Timestamp(datetime.combine(self.end + timedelta(days=1), time.min))
        stamps = pd.DatetimeIndex(simulated)
        if time_method_for(self.variable) != "mean":
            return np.asarray((stamps >= lo) & (stamps < hi))
        if stamps.size == 0:
            return np.zeros(0, dtype=bool)
        first = pd.NaT if first_start is None else pd.Timestamp(first_start)
        starts = pd.DatetimeIndex([first, *stamps[:-1]])
        return np.asarray((starts >= lo) & (stamps <= hi))


def run_score(run: Run, *, stations: Sequence[str], variable: str) -> RunScore | None:
    """Return the scores *run* recorded for *variable* at the first of *stations* it scored.

    ``None`` when it scored none of them: no ``[metrics] window``, or a
    window too short to hold a score.
    """
    frame = metrics_of(run)
    for station in stations:
        rows = frame[(frame["station"] == station) & (frame["variable"] == variable)]
        values = {
            str(row.metric): float(row.value) for row in rows.itertuples() if _finite(row.value)
        }
        if not values:
            continue
        first = rows.iloc[0]
        start, end, n = first["nse_window_start"], first["nse_window_end"], first["nse_n"]
        if pd.isna(start) or pd.isna(end) or pd.isna(n):
            continue
        return RunScore(
            station=str(station),
            variable=variable,
            values=values,
            start=pd.Timestamp(start).date(),
            end=pd.Timestamp(end).date(),
            n=int(n),
        )
    return None


def _finite(value: Any) -> bool:
    return not pd.isna(value) and bool(np.isfinite(float(value)))
