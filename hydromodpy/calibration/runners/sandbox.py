"""Per-trial solver sandbox for parallel calibration.

Each calibration trial runs an independent, single-threaded solver subprocess.
When the engine evaluates several trials at once (``calibration.parallel > 1``),
those subprocesses must not write to the same model folder or they overwrite
each other's input/output files.

:class:`TrialSandbox` gives one trial a private solver identity: a
:class:`~hydromodpy.core.state.run_state.SlotRequest` with a per-trial run name,
so the solver writes into its own ``<scratch>/<model>/`` folder (the shared,
read-only preprocessing under ``<scratch>/`` stays shared). The request also
names the folder of the recharge binaries the trial reads: one
``<scratch>/_shared_recharge`` folder for every trial of the session, or
``<scratch>/<model>/_recharge`` inside the trial folder when the phase samples a
recharge parameter.
It is a context manager (RAII): on exit it removes the trial's solver output
directories, unless the session retention took them over for a promotion
(:meth:`TrialSandbox.keep_outputs`). Set ``HMP_KEEP_TRIAL_SCRATCH=1`` to retain
them all for debugging.

:func:`lane_dir` names the folder of a lane, ``<scratch>/<model>_lane<key>``,
beside the trial folders: the input files of the last solved trial of the lane,
which the next trial of the lane reruns from
(:mod:`~hydromodpy.calibration.runners.lanes`).
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.run_state import SlotRequest

logger = get_logger(__name__)

KEEP_ENV_VAR = "HMP_KEEP_TRIAL_SCRATCH"

_SAFE_NAME = re.compile(r"[^0-9A-Za-z._-]+")

SHARED_RECHARGE_DIRNAME = "_shared_recharge"
"""Folder, beside the trial folders, that holds the recharge every trial shares."""

TRIAL_RECHARGE_DIRNAME = "_recharge"
"""Folder, inside the trial folder, that holds the recharge of a trial of its own."""


def keep_trial_scratch() -> bool:
    """Return True when the environment asks to retain calibration scratch dirs.

    Covers both the per-trial solver folders and the session-wide preprocessing
    tree: a debugging session that keeps one keeps the other.
    """
    value = os.environ.get(KEEP_ENV_VAR)
    return value is not None and value.strip().lower() not in ("", "0", "false", "no")


def _sanitize(name: str) -> str:
    """Return a filesystem-safe model-name stem."""
    cleaned = _SAFE_NAME.sub("-", str(name).strip()) or "trial"
    return cleaned


class TrialSandbox:
    """Isolated solver identity for one calibration trial.

    Parameters
    ----------
    base_model_name
        The session's base model name (usually ``setup.run_id``). The trial
        model name is derived from it so a retained folder is easy to locate.
    trial_id
        Unique trial identifier.
    keep
        Retain the trial's solver output on exit. Defaults to the
        ``HMP_KEEP_TRIAL_SCRATCH`` environment variable.
    scratch_root
        The solver scratch of the run, where the trial's model folder is
        written. Named so a crashed trial's folder is still swept on exit.
    """

    def __init__(
        self,
        base_model_name: str,
        trial_id: int,
        *,
        keep: bool | None = None,
        scratch_root: Path | str | None = None,
    ) -> None:
        self.model_name = f"{_sanitize(base_model_name)}_trial{int(trial_id):06d}"
        self._keep = keep_trial_scratch() if keep is None else bool(keep)
        self._handed_over = False
        self._execution: Any | None = None
        self._scratch_root: Path | None = Path(scratch_root) if scratch_root else None
        # Eager output dir: the trial writes into <scratch>/<model_name>/, so a
        # diverged / timed-out / crashed trial (which never records a success in
        # the run registry) is still cleaned up on exit.
        self._eager_dir: Path | None = (
            self._scratch_root / self.model_name if self._scratch_root is not None else None
        )

    def slot_request(
        self, *, owns_recharge: bool = False, stop_before_solve: bool = False
    ) -> SlotRequest:
        """Return the request that pins this trial to its own model folder.

        ``owns_recharge`` says the phase samples a value the recharge is
        computed from, so the trial writes its recharge inside its own folder,
        removed with it. Otherwise the trial reads the recharge every trial
        shares. Without a scratch root the recharge stays beside the model.
        """
        forcing_dir: Path | None = None
        if self._scratch_root is not None:
            forcing_dir = (
                self._scratch_root / self.model_name / TRIAL_RECHARGE_DIRNAME
                if owns_recharge
                else self._scratch_root / SHARED_RECHARGE_DIRNAME
            )
        return SlotRequest(
            name=self.model_name,
            stop_before_solve=stop_before_solve,
            shared_forcing_dir=forcing_dir,
        )

    def track(self, execution: Any) -> None:
        """Record the forked execution registry whose outputs to clean up."""
        self._execution = execution

    def keep_outputs(self) -> None:
        """Leave the solver outputs in place on exit: the session retention owns them now."""
        self._handed_over = True

    def output_dirs(self) -> list[Path]:
        """Return every folder this trial's solver wrote into, once each."""
        solver_runs = getattr(self._execution, "solver_runs", None) or {}
        candidates = [
            Path(run.output_dir)
            for run in solver_runs.values()
            if getattr(run, "output_dir", None) is not None
        ]
        if self._eager_dir is not None:
            candidates.append(self._eager_dir)
        seen: set[str] = set()
        unique: list[Path] = []
        for path in candidates:
            key = str(path)
            if key not in seen:
                seen.add(key)
                unique.append(path)
        return unique

    def __enter__(self) -> TrialSandbox:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        if self._handed_over:
            return False
        if self._keep:
            for path in self.output_dirs():
                logger.debug("Kept trial output %s (%s set)", path, KEEP_ENV_VAR)
            return False
        for path in self.output_dirs():
            shutil.rmtree(path, ignore_errors=True)
        return False


def _scratch_of(trial_ctx: Any) -> tuple[str, Path | None]:
    """Return the base model name and the solver scratch of a prepared context."""
    setup = getattr(getattr(trial_ctx, "ctx", None), "setup", None)
    base_model_name = str(getattr(setup, "run_id", "") or "trial")
    scratch_root = getattr(getattr(setup, "workspace", None), "solver_scratch_folder", None)
    return base_model_name, None if scratch_root is None else Path(scratch_root)


def sandbox_of(trial_ctx: Any, trial_id: int) -> TrialSandbox:
    """Return the sandbox of one trial of a prepared context, whichever process asks."""
    base_model_name, scratch_root = _scratch_of(trial_ctx)
    return TrialSandbox(base_model_name, trial_id, scratch_root=scratch_root)


LANE_INFIX = "_lane"
"""What sets the folder of a lane apart from the folder of a trial, after the model name."""


def lane_dir(trial_ctx: Any, key: str) -> Path | None:
    """Return the folder of the lane ``key`` of a prepared context, ``None`` without a scratch.

    ``key`` is unique among the lanes of every process of the session: a worker
    process puts its own id in it, so two workers never share a folder.
    """
    base_model_name, scratch_root = _scratch_of(trial_ctx)
    if scratch_root is None:
        return None
    return scratch_root / f"{_sanitize(base_model_name)}{LANE_INFIX}{_sanitize(key)}"


def lane_dirs(trial_ctx: Any) -> list[Path]:
    """Return the lane folders of a prepared context on disk, those of every process."""
    base_model_name, scratch_root = _scratch_of(trial_ctx)
    if scratch_root is None or not scratch_root.is_dir():
        return []
    stem = f"{_sanitize(base_model_name)}{LANE_INFIX}"
    return sorted(path for path in scratch_root.glob(f"{stem}*") if path.is_dir())


__all__ = [
    "KEEP_ENV_VAR",
    "LANE_INFIX",
    "SHARED_RECHARGE_DIRNAME",
    "TRIAL_RECHARGE_DIRNAME",
    "TrialSandbox",
    "keep_trial_scratch",
    "lane_dir",
    "lane_dirs",
    "sandbox_of",
]
