"""The attempt protocol: who may work in a run directory, and how it ends.

Why
---
A case is a directory, and a directory can be claimed by one worker at a
time. The first act of a worker is to claim ``runs/<case>/`` and write
``outcome.json`` as ``running``; its last act is to rewrite the outcome with
what happened. A second worker on the same case, a worker re-issued by a
scheduler, a retry after a crash: each one reads the directory and either
continues in it as the next attempt or stops with a sentence. A failed
attempt never consumes a version: the next attempt works in the same
directory and files the previous outcome under ``attempts/<k>/``.

Rules
-----
- No directory: the claim is ``os.mkdir(runs/<case>)`` itself. The loser
  of that ``mkdir`` stops with "another worker claimed this case".
- The latest version is completed: a new version is reserved
  (:func:`~hydromodpy.results.catalog.registration.reserve_version_dirname`).
- The latest version is ``running`` with a fresh pulse: refused, the case is
  alive elsewhere.
- The latest version is ``stale``: claimable when the death is proven, same
  host and process gone, or when the operator says so with ``force``.
- The latest version is ``failed``, ``aborted`` or ``partial``: claimable.
- The claim of attempt ``k + 1`` is ``os.mkdir(attempts/<k>)``; the loser gets
  ``EEXIST`` and stops with "another worker claimed this case". The outcome
  of attempt ``k`` stays in place until the new one replaces it, so no reader
  ever sees the directory without an outcome.
- A directory without outcome and without seal, younger than the stale
  threshold, is a claim in flight: refused as claimed elsewhere. Older, it is
  a directory nobody made this way, and the worker says what to do with it.
- By default the attempt resumes in place: ``outcome.json`` and ``logs/`` of
  attempt ``k`` go under ``attempts/<k>/``, the checkpoints, the partial
  field store and the scratch stay. ``fresh``, or a configuration hash that
  differs from the one the previous attempt recorded, moves everything.

How an attempt ends
-------------------
:func:`finish_attempt` rewrites the outcome with the status, the step, the
error, the signal and the end of the run log. It never touches the attempt
state under ``<run>/.hmp/``. :func:`close_sealed_attempt` is the last act of
a sealed run: ``manifest.json`` is on disk, the outcome flips to
``completed`` and ``<run>/.hmp/`` is removed. Solver folders kept under
``keep_solver_files`` left the scratch for ``<run>/solver/`` at the export
step, so they outlive it. A window that stops before the seal ends as
``completed`` without a manifest, which reads as ``partial``, and keeps its
attempt state for the resume.
"""

from __future__ import annotations

import os
import shutil
import signal as signals
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from hydromodpy.core.interrupts import TerminationRequested
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import (
    INTERNAL_DIRNAME,
    PREPROCESSING_DIRNAME,
    RUN_INTERNAL_SCRATCH_DIRNAME,
    SCRATCH_ROOT_ENV,
    process_is_alive,
    run_dir_rel,
    runs_dir_for,
    scratch_root_for,
)
from hydromodpy.results.catalog.registration import (
    check_name_free,
    live_version_dir,
    next_version_dirname,
    reserve_version_dirname,
    split_stem_version,
)
from hydromodpy.results.manifest import is_sealed
from hydromodpy.results.outcome import (
    DEFAULT_STALE_AFTER_S,
    Outcome,
    OutcomeError,
    OutcomeStatus,
    WrittenBy,
    effective_status,
    read_outcome,
    write_outcome,
)
from hydromodpy.results.readme import render_unsealed_run_readme, write_readme
from hydromodpy.results.storage.contract import (
    RUN_ATTEMPTS_DIRNAME,
    RUN_LOGS_DIRNAME,
    RUN_MANIFEST_FILENAME,
    RUN_OUTCOME_FILENAME,
)
from hydromodpy.results.storage.json_io import readable
from hydromodpy.results.storage.run_facts import read_facts

logger = get_logger(__name__)

CLAIMED_ELSEWHERE = "another worker claimed this case"
"""The sentence a worker that lost a claim ends with."""


class AttemptClaimedError(RuntimeError):
    """Another worker claimed the same attempt of this case first."""


class CaseAliveError(RuntimeError):
    """The case is running elsewhere and its death is not proven."""


class DirectoryWithoutOutcomeError(RuntimeError):
    """The latest directory of the case carries no outcome and no seal."""


@dataclass(frozen=True, slots=True)
class RunClaim:
    """The directory and the attempt a worker holds."""

    run_dir: Path
    name: str
    sim_id: str
    attempt: int
    attempt_id: str
    resumed: bool
    started_at: datetime
    host: str
    pid: int

    @property
    def rel_dir(self) -> str:
        """``runs/<name>``."""
        return run_dir_rel(self.name)


def signal_of(error: BaseException | None) -> int | None:
    """Return the signal an exception stands for, or None for an ordinary error.

    SIGTERM unwinds as :class:`~hydromodpy.core.interrupts.TerminationRequested`
    and SIGINT as ``KeyboardInterrupt``; nothing else is a signal.
    """
    if isinstance(error, TerminationRequested):
        return int(signals.SIGTERM)
    if isinstance(error, KeyboardInterrupt):
        return int(signals.SIGINT)
    return None


def latest_version_dir(project_root: Path, name: str) -> Path | None:
    """Return the live directory of the highest version of *name* under ``runs/``."""
    runs = runs_dir_for(project_root)
    if not runs.is_dir():
        return None
    best: tuple[int, Path] | None = None
    for entry in runs.iterdir():
        if not entry.is_dir():
            continue
        stem, version = split_stem_version(entry.name)
        if stem != name:
            continue
        number = 1 if version is None else version
        if best is None or number > best[0]:
            best = (number, entry)
    return None if best is None else best[1]


def run_dir_for_name(project_root: Path, name: str) -> Path | None:
    """Return the directory a run name refers to, or None.

    A name that carries its version (``nancon.v2``) is that directory and no
    other; a bare name is its latest version. This is the one reading of a
    run name on the command line and in a configuration.
    """
    stem, version = split_stem_version(name)
    if version is not None:
        exact = runs_dir_for(project_root) / name
        return exact if exact.is_dir() else None
    return latest_version_dir(project_root, stem)


def claim_run_directory(
    project_root: Path,
    name: str,
    *,
    case_id: str,
    project: str,
    site: str | None = None,
    fresh: bool = False,
    force: bool = False,
    config_hash: str | None = None,
    if_exists: Literal["version", "fail"] = "version",
    now: datetime | None = None,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
) -> RunClaim:
    """Claim the directory of case *name* for a new attempt and write its outcome.

    Returns the claim. Raises :class:`CaseAliveError` when the case runs
    elsewhere, :class:`AttemptClaimedError` when another worker took the
    directory or the attempt first, :class:`DirectoryWithoutOutcomeError`
    when the latest directory says nothing about itself and is old enough
    not to be a claim in flight.

    A claim that needs a new directory never takes a name the trash or a
    tombstone holds: it takes the next version. A name that carries its
    version (``nancon.v2``) reaches only that live directory: a version is
    given by the disk, so one the trash, a tombstone or nobody holds is
    refused with
    :class:`~hydromodpy.results.catalog.registration.NameTakenError`, and a
    completed one gives the next version of the bare name. With ``if_exists = "fail"``
    it takes none and raises
    :class:`~hydromodpy.results.catalog.registration.NameTakenError` when any
    version of *name* is held. A retry of an unfinished attempt reuses its
    directory and gives out no name.

    *config_hash* is the identity hash of the configuration this attempt
    runs. A retry whose hash differs from the one the previous attempt
    recorded in its facts starts fresh, as if ``fresh`` had been passed.
    """
    root = Path(project_root)
    when = now if now is not None else datetime.now(UTC)
    host = socket.gethostname()
    pid = os.getpid()
    stem, version = split_stem_version(name)
    latest = live_version_dir(root, name) if version is not None else latest_version_dir(root, name)
    if latest is None:
        if if_exists == "fail":
            check_name_free(root, name)
        if next_version_dirname(root, name) != name:
            target = reserve_version_dirname(root, "run", name)
            return _first_attempt(target, target.name, case_id, project, site, when, host, pid)
        runs = runs_dir_for(root)
        runs.mkdir(parents=True, exist_ok=True)
        target = runs / name
        try:
            os.mkdir(target)
        except FileExistsError as exc:
            raise AttemptClaimedError(f"{CLAIMED_ELSEWHERE}: {name}") from exc
        return _first_attempt(target, name, case_id, project, site, when, host, pid)
    status = effective_status(latest, now=when, stale_after_s=stale_after_s)
    # A directory this code cannot read is left as it is: the case takes a new version.
    if status in ("completed", "unreadable"):
        if if_exists == "fail":
            check_name_free(root, stem)
        target = reserve_version_dirname(root, "run", stem)
        return _first_attempt(target, target.name, case_id, project, site, when, host, pid)
    if status == "unknown":
        _refuse_directory_without_outcome(latest, when, stale_after_s)
    previous = read_outcome(latest)
    if previous is None:
        # The outcome was there a moment ago: another worker is rewriting it.
        raise AttemptClaimedError(f"{CLAIMED_ELSEWHERE}: {latest.name}")
    same_host = previous.host == host
    if status == "running" and (not same_host or process_is_alive(previous.pid)):
        # A fresh pulse of a process of this host that no longer exists is a
        # death without a word (SIGKILL, OOM killer): the pulse is the last
        # one it wrote, and the attempt is over.
        raise CaseAliveError(
            f"{latest.name} is running on {previous.host} (pid {previous.pid}), "
            f"attempt {previous.attempt}; its pulse is fresh."
        )
    if status == "stale" and not force:
        if not same_host or process_is_alive(previous.pid):
            raise CaseAliveError(
                f"{latest.name} may still be running on {previous.host} (pid "
                f"{previous.pid}): its pulse is stale but its death is not proven. "
                "Pass --force once the process is known to be dead."
            )
    starts_over = fresh or _config_changed(latest, config_hash)
    return _next_attempt(latest, previous, fresh=starts_over, when=when, host=host, pid=pid)


def _refuse_directory_without_outcome(directory: Path, when: datetime, grace_s: float) -> None:
    """Say what a directory without outcome and without seal is.

    A worker creates the directory and writes its first outcome a moment
    later; a newcomer that reads in between sees a claim in flight and is
    refused as such. A directory older than *grace_s* in that state was not
    made by a worker, and the operator has to move it out of the way.
    """
    age_s = (when - datetime.fromtimestamp(directory.stat().st_mtime, tz=UTC)).total_seconds()
    if age_s <= grace_s:
        raise AttemptClaimedError(f"{CLAIMED_ELSEWHERE}: {directory.name}")
    raise DirectoryWithoutOutcomeError(
        f"{directory} carries neither {RUN_OUTCOME_FILENAME} nor {RUN_MANIFEST_FILENAME}: "
        "trash it, or rename it, before running this case again."
    )


def _config_changed(run_dir: Path, config_hash: str | None) -> bool:
    """Return whether the previous attempt ran another configuration than *config_hash*."""
    if config_hash is None:
        return False
    facts = read_facts(run_dir)
    if facts is None or facts.config_hash is None:
        return False
    changed = facts.config_hash != config_hash
    if changed:
        logger.info(
            "The configuration of %s changed since its last attempt: starting over.",
            run_dir.name,
        )
    return changed


def claim_reserved_directory(
    run_dir: Path,
    *,
    case_id: str,
    project: str,
    site: str | None = None,
    sim_id: str | None = None,
    now: datetime | None = None,
) -> RunClaim:
    """Write the first outcome of a directory someone reserved by its ``mkdir``.

    A calibration promotion reserves the run directory paired with its
    session and hands it to the pipeline; the pipeline claims it here as
    attempt 1, with the ``sim_id`` the promotion minted when it gave one. A
    directory that already carries an outcome is refused: it is a case in
    flight or a case to retry, and :func:`claim_run_directory` is the way in.
    """
    directory = Path(run_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"{directory} is not a directory to claim")
    if read_outcome(directory) is not None:
        raise AttemptClaimedError(f"{directory} already carries an outcome")
    when = now if now is not None else datetime.now(UTC)
    claim = RunClaim(
        run_dir=directory,
        name=directory.name,
        sim_id=str(sim_id) if sim_id else str(uuid.uuid4()),
        attempt=1,
        attempt_id=uuid.uuid4().hex,
        resumed=False,
        started_at=when,
        host=socket.gethostname(),
        pid=os.getpid(),
    )
    write_outcome(directory, _running_outcome(claim, case_id=case_id, project=project, site=site))
    return claim


def _first_attempt(
    run_dir: Path,
    name: str,
    case_id: str,
    project: str,
    site: str | None,
    when: datetime,
    host: str,
    pid: int,
) -> RunClaim:
    claim = RunClaim(
        run_dir=run_dir,
        name=name,
        sim_id=str(uuid.uuid4()),
        attempt=1,
        attempt_id=uuid.uuid4().hex,
        resumed=False,
        started_at=when,
        host=host,
        pid=pid,
    )
    write_outcome(run_dir, _running_outcome(claim, case_id=case_id, project=project, site=site))
    return claim


def _next_attempt(
    run_dir: Path,
    previous: Outcome,
    *,
    fresh: bool,
    when: datetime,
    host: str,
    pid: int,
) -> RunClaim:
    attempts = run_dir / RUN_ATTEMPTS_DIRNAME
    attempts.mkdir(exist_ok=True)
    archive = attempts / str(previous.attempt)
    try:
        os.mkdir(archive)
    except FileExistsError as exc:
        raise AttemptClaimedError(
            f"{CLAIMED_ELSEWHERE}: {run_dir.name}, attempt {previous.attempt + 1}"
        ) from exc
    _file_previous_attempt(run_dir, archive, fresh=fresh)
    claim = RunClaim(
        run_dir=run_dir,
        name=run_dir.name,
        sim_id=str(uuid.uuid4()) if fresh or previous.sim_id is None else previous.sim_id,
        attempt=previous.attempt + 1,
        attempt_id=uuid.uuid4().hex,
        resumed=not fresh,
        started_at=when,
        host=host,
        pid=pid,
    )
    write_outcome(
        run_dir,
        _running_outcome(
            claim, case_id=previous.case_id, project=previous.project, site=previous.site
        ),
    )
    return claim


def _file_previous_attempt(run_dir: Path, archive: Path, *, fresh: bool) -> None:
    """File what attempt ``k`` left under ``attempts/<k>/``.

    The outcome is copied, not moved: it stays in place until the outcome of
    the new attempt replaces it, so the directory never reads as unknown.
    """
    outcome = run_dir / RUN_OUTCOME_FILENAME
    if outcome.is_file():
        shutil.copy2(outcome, archive / RUN_OUTCOME_FILENAME)
    logs = run_dir / RUN_LOGS_DIRNAME
    if logs.exists():
        shutil.move(str(logs), str(archive / RUN_LOGS_DIRNAME))
    if not fresh:
        return
    for entry in list(run_dir.iterdir()):
        if entry.name in (RUN_ATTEMPTS_DIRNAME, RUN_OUTCOME_FILENAME):
            continue
        shutil.move(str(entry), str(archive / entry.name))


def _running_outcome(
    claim: RunClaim, *, case_id: str, project: str | None, site: str | None
) -> Outcome:
    return Outcome(
        case_id=case_id,
        site=site,
        project=project,
        attempt=claim.attempt,
        attempt_id=claim.attempt_id,
        sim_id=claim.sim_id,
        status="running",
        written_by="worker",
        started_at=claim.started_at,
        host=claim.host,
        pid=claim.pid,
        scheduler_job_id=scheduler_job_id_from_env(),
    )


def scheduler_job_id_from_env() -> str | None:
    """Return <array job>_<task> of a SLURM task, the SLURM job id, or None off a cluster."""
    array_job = os.environ.get("SLURM_ARRAY_JOB_ID")
    task = os.environ.get("SLURM_ARRAY_TASK_ID")
    if array_job and task:
        return f"{array_job}_{task}"
    return os.environ.get("SLURM_JOB_ID") or None


def finish_attempt(
    run_dir: Path,
    *,
    status: OutcomeStatus,
    step: str | None = None,
    error: BaseException | None = None,
    exit_code: int | None = None,
    signal: int | None = None,
    log_tail: list[str] | None = None,
    written_by: WrittenBy = "worker",
    ended_at: datetime | None = None,
) -> Outcome:
    """Rewrite the outcome of the attempt in *run_dir* with how it ended.

    A failed or aborted attempt also gets the README of an unsealed run, so
    the directory explains itself. The attempt state under ``<run>/.hmp/`` is
    left exactly as it was: only :func:`close_sealed_attempt` removes it.
    """
    previous = read_outcome(run_dir)
    if previous is None:
        raise FileNotFoundError(f"{run_dir} carries no {RUN_OUTCOME_FILENAME} to finish")
    when = ended_at if ended_at is not None else datetime.now(UTC)
    outcome = previous.model_copy(
        update={
            "status": status,
            "ended_at": when,
            "step": step if step is not None else previous.step,
            "exit_code": exit_code,
            "signal": signal,
            "written_by": written_by,
            "error": None
            if error is None or status == "completed"
            else OutcomeError(
                type=type(error).__name__, message=str(error) or type(error).__name__
            ),
            "log_tail": list(log_tail or []),
        }
    )
    write_outcome(run_dir, outcome)
    if status in ("failed", "aborted"):
        write_readme(run_dir, render_unsealed_run_readme(outcome))
    return outcome


def close_sealed_attempt(run_dir: Path, *, ended_at: datetime | None = None) -> Outcome:
    """Flip the outcome of a sealed run to ``completed`` and drop its attempt state.

    The last act of a run: ``manifest.json`` is already on disk, every
    journal row and checkpoint has been written, so ``<run>/.hmp/`` has
    nothing left to say. A directory without a seal is refused: a window
    that stopped early ends through :func:`finish_attempt` and keeps its
    state for the resume.
    """
    directory = Path(run_dir)
    if not is_sealed(directory):
        raise FileNotFoundError(
            f"{directory} carries no {RUN_MANIFEST_FILENAME}: an unsealed attempt is not closed "
            "as completed"
        )
    outcome = finish_attempt(directory, status="completed", exit_code=0, ended_at=ended_at)
    _drop_attempt_state(directory)
    return outcome


def finish_dead_attempt(
    run_dir: Path,
    *,
    host: str,
    pid: int,
    exit_code: int | None,
    signal: int | None = None,
    log_tail: list[str] | None = None,
    written_by: WrittenBy = "launcher",
) -> Outcome | None:
    """Write ``failed`` for an attempt whose worker died without writing.

    *host* and *pid* name the worker the caller launched. An outcome that
    names another process belongs to another worker, alive or not, and is
    left alone: a newcomer refused by the claim never touches the run of
    the worker that holds it. Returns the outcome written, or ``None`` when
    the worker had already written its own exit or is not the one named.
    """
    previous = readable(read_outcome, run_dir)
    if previous is None or previous.status != "running":
        return None
    if previous.host != host or previous.pid != pid:
        return None
    return finish_attempt(
        run_dir,
        status="failed",
        error=RuntimeError(
            f"the worker ended without writing its outcome (exit code {exit_code}, signal {signal})"
        ),
        exit_code=exit_code,
        signal=signal,
        log_tail=log_tail,
        written_by=written_by,
    )


def scratch_dir_for_attempt(project_root: Path, run_dir: Path, attempt: int) -> Path:
    """Return the solver scratch of an attempt.

    ``runs/<case>/.hmp/scratch/`` by default; under ``$HMP_SCRATCH_ROOT`` the
    attempt works in ``<root>/<project>/<case>.a<attempt>/`` instead, so a
    node-local disk takes the solver files and the project tree only
    receives the results.
    """
    root = os.environ.get(SCRATCH_ROOT_ENV, "").strip()
    if root:
        project = Path(project_root).resolve().name
        return Path(root).expanduser() / project / f"{run_dir.name}.a{attempt}"
    return Path(run_dir) / INTERNAL_DIRNAME / RUN_INTERNAL_SCRATCH_DIRNAME


def is_run_product(path: str | Path | None, project_root: Path | str | None) -> bool:
    """Whether ``path`` is a file a run wrote for itself, never an input of the run.

    The preprocessing writes its products (the rasterised stream network, a
    clipped DEM) under the scratch of the run, which the seal removes, and the
    solver works under a ``.hmp/`` folder, which is disposable. A path under
    the scratch root of the project, under a ``.hmp/`` folder or under a
    preprocessing folder is such a product. The inputs of a run are the files
    the configuration declares and the files a provider delivered; a replay
    derives the products from them again.
    """
    if path is None or not str(path):
        return False
    target = Path(path).expanduser()
    if INTERNAL_DIRNAME in target.parts or PREPROCESSING_DIRNAME in target.parts:
        return True
    if project_root is None or not target.is_absolute():
        return False
    return target.resolve().is_relative_to(scratch_root_for(Path(project_root)).resolve())


def _drop_attempt_state(run_dir: Path) -> None:
    """Remove ``<run>/.hmp/`` once a completed run is sealed."""
    state = run_dir / INTERNAL_DIRNAME
    if state.is_dir():
        shutil.rmtree(state, ignore_errors=True)


__all__ = [
    "CLAIMED_ELSEWHERE",
    "AttemptClaimedError",
    "CaseAliveError",
    "DirectoryWithoutOutcomeError",
    "RunClaim",
    "claim_reserved_directory",
    "claim_run_directory",
    "close_sealed_attempt",
    "finish_attempt",
    "finish_dead_attempt",
    "is_run_product",
    "latest_version_dir",
    "run_dir_for_name",
    "scheduler_job_id_from_env",
    "scratch_dir_for_attempt",
    "signal_of",
]
