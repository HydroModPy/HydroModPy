"""Thread-local capture of the simulated/observed series one trial scored.

Only opt-in, when ``[calibration].persist_trial_series`` is on. A trial writes
no field (fields.zarr is never touched here), only the point/series values an
output was actually scored on, at their own aligned time stamps: the pairs
:mod:`hydromodpy.calibration.metrics.scalar` and
:mod:`hydromodpy.calibration.metrics.observed_pairing` already build to
compute a cost, kept instead of being reduced to one.

Why thread-local
-----------------
One :class:`TrialSeriesSink` is built once per calibration session and shared
by every trial, because the scorer that records into it (``StationScorer`` or
``ObservableScorer``) is itself built once and reused across trials. Trials
run concurrently through a ``ThreadPoolExecutor``
(:mod:`hydromodpy.calibration.optim.engine`), so a plain list would race.
``threading.local`` instead gives every worker thread its own ``rows``: a
trial records into the storage of the thread that ran it, and the evaluator
drains exactly those rows, on that same thread, right after the trial
finishes and before the thread is handed the next one.

Network and spatial outputs are not recorded here: their cost is already a
scalar in ``trials.jsonl``, and neither carries a comparable simulated/observed
pair at a time stamp.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from typing import Any


class TrialSeriesSink(threading.local):
    """Per-thread buffer of ``(output, station, time, simulated, observed)`` rows."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def record(
        self,
        *,
        output: str | None,
        station: str | None,
        times: Iterable[Any],
        simulated: Iterable[float],
        observed: Iterable[float],
    ) -> None:
        """Append one output's aligned, already-scored series to this thread's rows."""
        for time, sim, obs in zip(times, simulated, observed, strict=True):
            self.rows.append(
                {
                    "output": output,
                    "station": station,
                    "time": time,
                    "simulated": float(sim),
                    "observed": float(obs),
                }
            )

    def drain(self) -> list[Mapping[str, Any]]:
        """Return and clear the rows recorded on the calling thread."""
        rows, self.rows = self.rows, []
        return rows


__all__ = ["TrialSeriesSink"]
