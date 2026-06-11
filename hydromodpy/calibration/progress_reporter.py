"""Console progress reporting for the calibration ask/tell loop."""

from __future__ import annotations

import math
import threading

from hydromodpy.calibration.optimizer import EvaluationResult
from hydromodpy.core import progress
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


class ConsoleProgressReporter:
    """Live progress bar over calibration trials.

    Implements the engine ``ProgressReporter`` protocol: one bar tick per
    trial with live best/crashed/cached counters in the description.
    Counters are lock-guarded because updates may arrive from worker
    threads when the engine evaluates batches in parallel.
    """

    def __init__(self, method: str, max_iter: int) -> None:
        self._method = method
        self._lock = threading.Lock()
        self._best = math.inf
        self._crashed = 0
        self._cached = 0
        self._closed = False
        self._task = progress.task(self._description(), total=max_iter)
        self._handle = self._task.__enter__()

    def update(self, trial_id: int, result: EvaluationResult) -> None:
        with self._lock:
            if result.from_cache:
                self._cached += 1
            if result.status != "completed":
                self._crashed += 1
            obj = result.objective_value
            if result.status == "completed" and math.isfinite(obj) and obj < self._best:
                self._best = obj
            description = self._description()
        self._handle.update(description=description)
        self._handle.advance()
        logger.debug(
            "trial %d: objective=%.6g status=%s duration=%.2fs from_cache=%s",
            trial_id,
            result.objective_value,
            result.status,
            result.duration_s,
            result.from_cache,
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._task.__exit__(None, None, None)

    def _description(self) -> str:
        head = f"Calibrating ({self._method})"
        details: list[str] = []
        if math.isfinite(self._best):
            details.append(f"best {self._best:.4g}")
        if self._crashed:
            details.append(f"{self._crashed} crashed")
        if self._cached:
            details.append(f"{self._cached} cached")
        return f"{head} - {', '.join(details)}" if details else head


__all__ = ["ConsoleProgressReporter"]
