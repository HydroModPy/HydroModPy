"""One attempt of a run, from the claim of its directory to its outcome.

Why
---
The first act of a run is to claim ``runs/<case>/`` and write its outcome as
``running``; its last act is to rewrite the outcome with how it ended. In
between the pulse of the attempt is written by a thread, the package log is
written into ``logs/run.log`` of the run, and the steps of the pipeline run.
:func:`run_attempt` is that bracket: it claims, pulses, logs, hands the claim
to the caller, and closes the outcome whatever happens, a SIGTERM turned into
``KeyboardInterrupt`` included.

How the bracket closes
----------------------
A run that reached its seal (``manifest.json`` on disk) is closed by
:func:`~hydromodpy.results.storage.attempt.close_sealed_attempt`: outcome
``completed`` and ``<run>/.hmp/`` removed, after the pipeline wrote its last
journal row. A window that stopped before the seal ends ``completed``
without a manifest, which reads as ``partial``, and keeps its attempt state
for a later resume. An exception ends the attempt ``failed``, a signal
``aborted``, both with the signal number and the end of the run log.

The scratch of the attempt is under the run, ``runs/<case>/.hmp/scratch/``,
or under ``$HMP_SCRATCH_ROOT/<project>/<case>.a<attempt>/`` when that root
is set (:func:`hydromodpy.results.storage.attempt.scratch_dir_for_attempt`).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from hydromodpy.core.logging import get_logger
from hydromodpy.results.heartbeat import HeartbeatThread
from hydromodpy.results.manifest import is_sealed
from hydromodpy.results.outcome import OutcomeStatus, effective_status, read_outcome
from hydromodpy.results.storage.attempt import (
    RunClaim,
    claim_run_directory,
    close_sealed_attempt,
    finish_attempt,
    signal_of,
)
from hydromodpy.results.storage.run_log import attach_run_log, detach_run_log, read_log_tail

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SealedRun:
    """What a finished attempt says about its run, read from its directory."""

    sim_id: str
    name: str
    run_dir: Path
    project_root: Path
    status: str


@dataclass(frozen=True, slots=True)
class AttemptHandle:
    """The claim of an attempt and the pulse that says it is alive."""

    claim: RunClaim
    heartbeat: HeartbeatThread

    @property
    def run_dir(self) -> Path:
        """The directory of the run."""
        return self.claim.run_dir

    @property
    def step(self) -> str | None:
        """The step the pulse names."""
        return self.heartbeat.step


def sealed_run_of(claim: RunClaim, project_root: Path) -> SealedRun:
    """Return what the directory of a finished attempt says."""
    outcome = read_outcome(claim.run_dir)
    sim_id = claim.sim_id if outcome is None or outcome.sim_id is None else outcome.sim_id
    return SealedRun(
        sim_id=sim_id,
        name=claim.name,
        run_dir=claim.run_dir,
        project_root=Path(project_root),
        status=effective_status(claim.run_dir),
    )


@contextmanager
def run_attempt(
    project_root: Path,
    name: str,
    *,
    case_id: str,
    project: str,
    site: str | None,
    fresh: bool = False,
    force: bool = False,
    config_hash: str | None = None,
    if_exists: Literal["version", "fail"] = "version",
    heartbeat_interval_s: float = 30.0,
) -> Iterator[AttemptHandle]:
    """Claim the directory of *name*, pulse, log, and close the outcome on exit.

    ``if_exists`` is ``[simulation] if_exists``: ``fail`` refuses a name any
    version of which is held, before anything is written.
    """
    claim = claim_run_directory(
        project_root,
        name,
        case_id=case_id,
        project=project,
        site=site,
        fresh=fresh,
        force=force,
        config_hash=config_hash,
        if_exists=if_exists,
    )
    log_handler = attach_run_log(claim.run_dir)
    heartbeat = HeartbeatThread(
        claim.run_dir,
        attempt_id=claim.attempt_id,
        interval_s=heartbeat_interval_s,
        host=claim.host,
        pid=claim.pid,
    )
    heartbeat.start()
    try:
        yield AttemptHandle(claim, heartbeat)
    except KeyboardInterrupt as exc:
        # SIGINT and SIGTERM both unwind as KeyboardInterrupt (core.runtime.interrupts).
        _close_if_running(claim.run_dir, status="aborted", step=heartbeat.step, error=exc)
        raise
    except BaseException as exc:
        # Any exit of the run, even an exit not meant as an error, seals the outcome as failed.
        _close_if_running(claim.run_dir, status="failed", step=heartbeat.step, error=exc)
        raise
    else:
        _close_if_running(claim.run_dir, status="completed", step=heartbeat.step, error=None)
    finally:
        heartbeat.stop()
        detach_run_log(log_handler)


def _close_if_running(
    run_dir: Path, *, status: OutcomeStatus, step: str | None, error: BaseException | None
) -> None:
    outcome = read_outcome(run_dir)
    if outcome is None or outcome.status != "running":
        return
    try:
        if status == "completed" and is_sealed(run_dir):
            close_sealed_attempt(run_dir)
            return
        finish_attempt(
            run_dir,
            status=status,
            step=step,
            error=error,
            signal=signal_of(error),
            log_tail=read_log_tail(run_dir) if status != "completed" else None,
        )
    except Exception:
        # The run's own error, still unwinding, must not be hidden by a failed outcome write.
        logger.exception("Could not write the outcome of %s", run_dir)


__all__ = [
    "AttemptHandle",
    "SealedRun",
    "run_attempt",
    "sealed_run_of",
]
