"""Trial solves kept on disk until their promotion.

A promoted trial used to be solved twice: once lightweight to score it, then in
full to write its run. The second solve repeats the first one. A lightweight
trial changes what the store receives, never what the solver writes: the
adapters read neither the lightweight flag nor the catalog handle, so both
solves write the same MODFLOW files from the same inputs.

This module keeps the first solve instead:

- :class:`RecordingLauncher` runs the plan of a trial like the default launcher
  and remembers what each run produced.
- :class:`TrialSolveRetention` decides which trial solves stay on disk while
  they may still be promoted, deletes the others as soon as they can no longer
  be, and deletes the rest when the session ends.
- :class:`KeptSolveLauncher` is the launcher of a promotion: it hands the kept
  solve to the run-solver step instead of solving, so the promoted run goes on
  from extraction exactly as a replay would.

``HMP_KEEP_TRIAL_SCRATCH`` still means "keep everything": retention never
deletes a folder, neither the solves it drops nor the ones left at the end.
"""

from __future__ import annotations

import shutil
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.calibration.runners.sandbox import keep_trial_scratch
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.calibration.config import CalibrationConfig
    from hydromodpy.simulation.planning.plan import (
        ProcessRun,
        RunExecutionResult,
        SimulationPlan,
    )

logger = get_logger(__name__)


def retention_capacity(cfg: CalibrationConfig) -> int | None:
    """Return how many trial solves a session keeps: ``None`` for all of them.

    The count follows what the session promotes. ``save_runs = "all"`` promotes
    every completed trial, ``"best_n"`` the ``save_best_n`` best, and
    ``rerun_best_with_outputs`` the best one. Nothing promoted, nothing kept.
    """
    if cfg.save_runs == "all":
        return None
    count = int(cfg.save_best_n) if cfg.save_runs == "best_n" else 0
    if cfg.rerun_best_with_outputs:
        count = max(count, 1)
    return count


@dataclass(frozen=True)
class KeptSolve:
    """The solve of one trial, kept for its promotion.

    ``results`` holds what each run of the plan produced, keyed by run id: the
    model the adapter built, the folder the solver wrote and the execution
    metrics the run recorded about itself. ``folders`` is everything the trial
    wrote under the run scratch, which is what goes when the solve is dropped.
    """

    trial_id: int
    cost: float
    folders: tuple[Path, ...]
    results: Mapping[str, RunExecutionResult] = field(default_factory=dict)

    def missing_output(self) -> Path | None:
        """Return a solver folder of this solve that is gone, or None."""
        for result in self.results.values():
            folder = getattr(result, "solver_output_dir", None)
            if folder is not None and not Path(folder).is_dir():
                return Path(folder)
        return None


class RecordingLauncher:
    """Run a plan with the default launcher and remember what each run produced.

    The run-solver step of a lightweight trial throws the results of the
    launcher away: nothing is written. A promotion needs them, the execution
    metrics in particular, which a replay records beside the run.
    """

    def __init__(self) -> None:
        self.results: dict[str, RunExecutionResult] = {}

    def execute(
        self,
        plan: SimulationPlan,
        state: Any,
        *,
        callbacks: Any | None = None,
        store: Any | None = None,
    ) -> tuple[tuple[ProcessRun, RunExecutionResult], ...]:
        """Execute ``plan`` like :class:`SimulationRunner` and keep its results."""
        from hydromodpy.simulation.execution.runner import SimulationRunner

        executed = SimulationRunner().execute(plan, state, callbacks=callbacks, store=store)
        for run, result in executed or ():
            self.results[str(run.id)] = result
        return tuple(executed or ())


class KeptSolveLauncher:
    """Hand a kept trial solve to the run-solver step instead of solving.

    It walks the plan the way :class:`SimulationRunner` does: it opens each
    process family, fires the same callbacks, and records each run's model and
    solver folder in the execution registry. The run-solver step then records
    the execution metrics and the engine identity of the promoted run as it
    does after a real solve, and extraction reads the kept folder.
    """

    def __init__(self, kept: KeptSolve) -> None:
        self.kept = kept

    def execute(
        self,
        plan: SimulationPlan,
        state: Any,
        *,
        callbacks: Any | None = None,
        store: Any | None = None,
    ) -> tuple[tuple[ProcessRun, RunExecutionResult], ...]:
        """Record the kept solve of every run of ``plan`` in ``state``."""
        from hydromodpy.simulation.execution.runner import ensure_process_context

        del store
        executed: list[tuple[ProcessRun, RunExecutionResult]] = []
        current: str | None = None
        for run in plan.runs:
            if run.process_type != current:
                if current is not None:
                    _fire(callbacks, "after_process", current)
                ensure_process_context(state, run.process_type)
                _fire(callbacks, "before_process", run.process_type)
                current = run.process_type
            result = self.kept.results.get(str(run.id))
            if result is None:
                raise CalibrationError(
                    f"Trial {self.kept.trial_id} kept no solve for run {run.id!r}; the "
                    "promotion cannot read what was never solved."
                )
            if result.primary_model is not None:
                state.execution.models_by_run_id[run.id] = result.primary_model
            if result.solver_output_dir is not None:
                state.execution.output_dirs_by_run_id[run.id] = Path(result.solver_output_dir)
            _fire(callbacks, "after_run", run, result, state)
            executed.append((run, result))
        if current is not None:
            _fire(callbacks, "after_process", current)
        return tuple(executed)


def _fire(callbacks: Any | None, name: str, *args: Any) -> None:
    hook: Callable[..., None] | None = getattr(callbacks, name, None)
    if hook is not None:
        hook(*args)


class TrialSolveRetention:
    """Which trial solves of one session stay on disk, and for how long.

    ``capacity`` is how many solves may still be promoted: ``None`` keeps every
    completed trial, a count keeps that many of the cheapest, ties going to the
    earlier trial. A solve pushed out by a cheaper one is deleted at once. A
    promoted solve belongs to its run from then on: the export step of that run
    removes its folder, or keeps it under ``keep_solver_files``, as it does for
    a replay. :meth:`release` deletes what is left, and the session calls it on
    every exit path.

    Trials run side by side, so every method is safe to call from several
    threads. Folders are deleted outside the lock.
    """

    def __init__(self, capacity: int | None, *, keep_everything: bool | None = None) -> None:
        self._capacity = None if capacity is None else max(0, int(capacity))
        self._keep_everything = keep_trial_scratch() if keep_everything is None else keep_everything
        self._lock = threading.Lock()
        self._kept: dict[int, KeptSolve] = {}
        self._dropped: dict[int, str] = {}
        self._left_on_disk: set[Path] = set()
        self._released = False

    @property
    def keeps_any(self) -> bool:
        """Whether this session keeps any solve at all."""
        return self._capacity is None or self._capacity > 0

    def offer(
        self,
        trial_id: int,
        cost: float,
        folders: Iterable[Path],
        results: Mapping[str, RunExecutionResult],
    ) -> bool:
        """Keep the solve of a completed trial if it may still be promoted.

        Returns whether it was kept. A trial that is not kept stays with its
        sandbox, which deletes its folders on exit, as before. So does a trial
        that finishes after :meth:`release`, when an interrupted session is
        still draining its thread pool.
        """
        if not self.keeps_any or not results:
            return False
        candidate = KeptSolve(
            trial_id=int(trial_id),
            cost=float(cost),
            folders=tuple(Path(folder) for folder in folders),
            results=dict(results),
        )
        with self._lock:
            if self._released:
                return False
            self._kept[candidate.trial_id] = candidate
            dropped = self._trim()
            kept = candidate.trial_id in self._kept
        self._delete(solve for solve in dropped if solve.trial_id != candidate.trial_id)
        return kept

    def _trim(self) -> list[KeptSolve]:
        """Drop the solves past the capacity, the most expensive first."""
        if self._capacity is None or len(self._kept) <= self._capacity:
            return []
        ranked = sorted(self._kept.values(), key=lambda solve: (solve.cost, solve.trial_id))
        dropped = ranked[self._capacity :]
        for solve in dropped:
            del self._kept[solve.trial_id]
            self._dropped[solve.trial_id] = (
                f"retention kept the {self._capacity} cheapest trial(s) and this one "
                "was not among them"
            )
        return dropped

    def take(self, trial_id: int) -> tuple[KeptSolve | None, str | None]:
        """Return the solve a promotion may read, or ``None`` and the reason why not."""
        with self._lock:
            kept = self._kept.get(int(trial_id))
            reason = self._dropped.get(int(trial_id))
        if kept is None:
            return None, reason or (
                "no solve of it was kept in this session (a cache hit, a failed trial, "
                "or a trial of an earlier process)"
            )
        gone = kept.missing_output()
        if gone is not None:
            return None, f"its solver folder {gone} is gone"
        return kept, None

    def promoted(self, trial_id: int) -> None:
        """Hand the solve of a promoted trial over to its run."""
        with self._lock:
            self._kept.pop(int(trial_id), None)

    def spared_folders(self, trial_id: int | None = None) -> tuple[Path, ...]:
        """Return the folders the export step of a promotion must leave in place.

        Every kept solve but the one of ``trial_id``, which that promotion
        consumes. Under ``HMP_KEEP_TRIAL_SCRATCH`` the solves retention dropped
        are spared too, since it left them on disk.
        """
        with self._lock:
            folders = {
                folder
                for solve in self._kept.values()
                if solve.trial_id != trial_id
                for folder in solve.folders
            }
            folders.update(self._left_on_disk)
        return tuple(sorted(folders))

    def release(self) -> None:
        """Delete every solve still kept, and keep nothing from now on. Never raises."""
        with self._lock:
            self._released = True
            remaining = list(self._kept.values())
            self._kept.clear()
        self._delete(remaining)

    def _delete(self, solves: Iterable[KeptSolve]) -> None:
        for solve in solves:
            if self._keep_everything:
                with self._lock:
                    self._left_on_disk.update(solve.folders)
                continue
            for folder in solve.folders:
                shutil.rmtree(folder, ignore_errors=True)


__all__ = [
    "KeptSolve",
    "KeptSolveLauncher",
    "RecordingLauncher",
    "TrialSolveRetention",
    "retention_capacity",
]
