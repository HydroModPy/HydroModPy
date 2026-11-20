"""Lanes of a calibration: the last solved trial of each lane is the parent of the next.

A trial that moves only K or Sy can be solved by ``rerun`` of a solved run
instead of a build: the backend copies the input files of that run and rewrites
the packages the change reaches. The run it starts from is its parent. A rerun
changes the solver object of its parent in place, so a parent serves one trial
at a time and never two.

A lane holds one parent. :class:`TrialParents` keeps one lane per trial that
runs at the same time: :meth:`TrialParents.take` hands a free lane to a trial,
:meth:`TrialParents.give` takes it back with the runs of that trial when it
completed, and with nothing when it failed, so the next trial of the lane
builds. Giving a run adopts it: its input files are copied from the trial
folder into the folder of the lane, ``<scratch>/<model>_lane<key>/<run>``, the
solver object is pointed at that copy, and the lane keeps the run with that
folder as its output folder. The trial folder stays with the sandbox and the
retention of solves, so no folder has two owners and no process deletes a file
another one is about to copy. On the island of 961 cells the copy is twelve
small files; on example 04 it is 16 MB in 2 to 3 ms, against 2.25 s of build
saved per trial.

A run is adopted only when its solver object can move, which today is the
MODFLOW 6 simulation of FloPy (``sim.set_sim_path``). Any other backend leaves
its lane empty, and its trials build as before.

The lane folders go at the end of the search, before the promotion, unless
``HMP_KEEP_TRIAL_SCRATCH`` is set. A worker process of a parallel search keeps
its own lanes, of width one, whose keys carry its process id.
"""

from __future__ import annotations

import os
import shutil
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from hydromodpy.calibration.runners.sandbox import keep_trial_scratch, lane_dir, lane_dirs
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.base.plan import SolverRun

logger = get_logger(__name__)


@dataclass
class Lane:
    """One lane: its folder and the runs of its last solved trial, by run id.

    ``runs`` is empty until a trial of the lane completes, and again after a
    trial of the lane fails. It is what a trial hands the runner as its
    previous runs.
    """

    key: str
    directory: Path
    runs: dict[str, SolverRun] = field(default_factory=dict)
    busy: bool = False


def _movable(run: SolverRun) -> bool:
    """Whether the solver object of ``run`` can move to the folder of a lane."""
    sim = getattr(run.solver_model, "sim", None)
    return (
        run.solved
        and run.written
        and run.output_dir is not None
        and bool(run.input_files)
        and callable(getattr(sim, "set_sim_path", None))
    )


def _safe(name: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "-" for char in name) or "run"


class TrialParents:
    """The lanes of one search in one process, safe to call from several threads.

    ``directory_of(key)`` is the folder of the lane ``key``, ``None`` when the
    session has no scratch, which leaves every lane empty. ``width`` bounds how
    many lanes exist at once, ``None`` for no bound. ``owner`` starts the key of
    every lane, so that two processes never name the same folder.
    """

    def __init__(
        self,
        directory_of: Any,
        *,
        width: int | None = None,
        owner: str = "",
        keep_everything: bool | None = None,
    ) -> None:
        self._directory_of = directory_of
        self._width = None if width is None else max(1, int(width))
        self._owner = str(owner)
        self._keep_everything = keep_trial_scratch() if keep_everything is None else keep_everything
        self._lock = threading.Lock()
        self._lanes: list[Lane] = []
        self._released = False

    @classmethod
    def of(cls, trial_ctx: Any, *, width: int | None = None, owner: str = "") -> TrialParents:
        """Return the lanes of a prepared trial context, in the folders of its scratch."""
        return cls(lambda key: lane_dir(trial_ctx, key), width=width, owner=owner)

    def take(self) -> Lane | None:
        """Return a free lane, one with a parent first, or ``None`` when every lane is busy.

        A new lane, without a parent, opens while the width allows. A lane taken
        is given back by :meth:`give` before another trial can take it.
        """
        with self._lock:
            if self._released:
                return None
            free = [lane for lane in self._lanes if not lane.busy]
            if free:
                lane = next((lane for lane in free if lane.runs), free[0])
            elif self._width is None or len(self._lanes) < self._width:
                key = f"{self._owner}{len(self._lanes) + 1}"
                directory = self._directory_of(key)
                if directory is None:
                    return None
                lane = Lane(key=key, directory=Path(directory))
                self._lanes.append(lane)
            else:
                return None
            lane.busy = True
            return lane

    def give(self, lane: Lane | None, results: Mapping[str, SolverRun] | None) -> None:
        """Take ``lane`` back, adopting ``results`` as its parent; ``None`` leaves it empty.

        ``results`` are the runs of a completed trial, by run id. A run whose
        solver object cannot move, or whose files cannot be copied, is left out.
        The lane is free again whatever happens. Never raises.
        """
        if lane is None:
            return
        adopted: dict[str, SolverRun] = {}
        if results is not None and not self._released:
            for run_id, run in results.items():
                kept = self._adopt(lane, str(run_id), run)
                if kept is not None:
                    adopted[str(run_id)] = kept
        with self._lock:
            lane.runs = adopted
            lane.busy = False

    def _adopt(self, lane: Lane, run_id: str, run: SolverRun) -> SolverRun | None:
        """Copy the input files of ``run`` into the lane and point its solver object there."""
        if not _movable(run):
            return None
        source = Path(run.output_dir)  # type: ignore[arg-type]
        target = lane.directory / _safe(run_id)
        try:
            for name in run.input_files:
                destination = target / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, destination)
            run.solver_model.sim.set_sim_path(os.fspath(target))  # type: ignore[union-attr]
        except OSError as exc:
            logger.debug("Lane %s keeps no parent: %s", lane.key, exc)
            return None
        return replace(run, output_dir=target)

    def release(self) -> None:
        """Forget every parent and delete the lane folders, unless kept. Never raises."""
        with self._lock:
            self._released = True
            lanes, self._lanes = self._lanes, []
        for lane in lanes:
            lane.runs = {}
            if not self._keep_everything:
                shutil.rmtree(lane.directory, ignore_errors=True)


def open_trial_lanes(trial_ctx: Any) -> None:
    """Give a prepared context its lanes when its trials derive their ``Model``.

    Only a trial that moves property profiles alone keeps the members of the
    prepared ``Model``, which is what lets the runner rerun it; any other trial
    builds, and a lane would only copy files for nothing.
    """
    if trial_ctx is None or not getattr(trial_ctx, "model_from_profiles", False):
        return
    if getattr(trial_ctx, "parents", None) is None:
        trial_ctx.parents = TrialParents.of(trial_ctx)


def release_trial_lanes(trial_ctx: Any) -> None:
    """Detach the lanes of a prepared context and delete every lane folder of the session.

    The folders a worker process left are deleted too, which only this process
    can do once the pool is closed. Runs at the end of each search, before the
    promotion, and on every exit path. Never raises.
    """
    if trial_ctx is None:
        return
    parents = getattr(trial_ctx, "parents", None)
    trial_ctx.parents = None
    if parents is not None:
        parents.release()
    if keep_trial_scratch():
        return
    for folder in lane_dirs(trial_ctx):
        shutil.rmtree(folder, ignore_errors=True)


__all__ = [
    "Lane",
    "TrialParents",
    "open_trial_lanes",
    "release_trial_lanes",
]
