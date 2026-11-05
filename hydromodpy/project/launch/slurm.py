"""SLURM array jobs for the plan of a ``[sites]`` project.

Why
---
On a cluster the plan is enough. ``hmp campaign array . --scheduler slurm``
writes ``jobs/<stamp>-slurm/{prepare.sh, array.sh, cases.txt}`` once, and
never rewrites them. Task N of either array reads line N of the
``cases.txt`` of its own job through ``hmp campaign case <job> N``
(:mod:`hydromodpy.project.launch.journal` owns that list), so a plan
written again while the job waits in the queue changes nothing it runs.

- ``prepare.sh`` runs the prepare command of each case, ``prepare_parallel``
  side by side (``%N`` throttle): the geography and the data, the only phase
  that writes the shared data cache. The task that completes the phase
  writes ``hydromodpy.lock``.
- ``array.sh`` runs the worker of each case, submitted with
  ``--dependency=afterok`` on the prepare job. ``--cpus-per-task`` is
  ``threads_per_case`` times the solves of the largest case (a calibration
  solves ``[calibration] parallel`` trials side by side).
  ``HMP_SCRATCH_ROOT`` is ``$SLURM_TMPDIR`` when the node has one.

The flags of ``hmp run`` are the local launcher's, chosen by the task when it
starts (:func:`task_flags`): ``--until load_data`` for the prepare phase, plus
``--set workflow.mode=simulation`` on a calibration case; ``--frozen`` for the
solve, plus ``--resume <case>`` on a simulation an earlier attempt left
unfinished. Each task also carries the environment of a launched case:
``HMP_THREADS_PER_CASE`` and ``HMP_LAUNCHED_CASE``, so no task writes the
project index (``hmp catalog reindex`` rebuilds it from the run directories).

How a task ends
---------------
The scheduler signals the batch shell 600 s before the walltime
(``--signal=B:TERM@600``); the shell forwards SIGTERM to the worker and
waits for it. Then the trap step, :func:`finish_task`, copies the task log
to ``runs/<case>/logs/job-<id>.out`` and writes ``failed`` (exit code,
signal, log tail, ``written_by = "trap"``) when the worker left ``running``
behind and its death is proven: same host, process gone. A calibration case
gets the same in its session directory. A SIGKILL of the whole job leaves no
trap; :func:`hydromodpy.project.launch.sacct.scheduler_states` then reads ``sacct``.

Not handled (CIBLE §14)
-----------------------
The prepare tasks do not get ``HMP_DATA_CACHE_PRIVATE``: a private cache
needs a merge, and no launcher sits between the tasks to do it, so up to
``prepare_parallel`` tasks write the shared ``cache.duckdb`` themselves,
behind the DuckDB lock (unsafe on NFS). The local launcher never prepares two
cases of one site side by side; an array cannot hold a task back, so two
cases of one site may be prepared at once and write the same files of
``data/``. Keep ``prepare_parallel = 1``, or one recipe per site, until both
are handled.

Not verified on a cluster. The tests check the scripts with ``bash -n`` and
run them under a stand-in ``hmp`` and a stand-in ``sacct``, never under a
real scheduler.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import socket
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from hydromodpy.core.exceptions import ConfigError, JobUsageError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import jobs_dir_for
from hydromodpy.core.state.scratch import process_is_alive
from hydromodpy.data.provenance.lockfile import project_lockfile_path
from hydromodpy.project.launch.children import (
    PlannedCase,
    close_dead_session,
    dead_worker_message,
    planned_cases,
    prepare_command,
    state_of,
    worker_command,
)
from hydromodpy.project.launch.env import LAUNCHED_ENV, THREADS_ENV
from hydromodpy.project.launch.journal import (
    CASES_FILENAME,
    STAMP_FORMAT,
    write_case_list,
)
from hydromodpy.project.launch.prepare import workspace_data_dir
from hydromodpy.project.launch.selection import (
    effective_prepare_parallel,
    sites_run_config,
    worker_flags,
)
from hydromodpy.project.launch.slurm_script import (
    TERM_GRACE_S,
    render,
    worker_block,
)
from hydromodpy.project.launch.slurm_script import (
    directives as sbatch_directives,
)
from hydromodpy.project.launch.status import plan_is_stale
from hydromodpy.results.outcome import Outcome, read_outcome, write_outcome
from hydromodpy.results.plan_store import read_plan
from hydromodpy.results.session.descriptor import (
    latest_session_dir,
    session_descriptor_path,
)
from hydromodpy.results.storage.attempt import finish_attempt, latest_version_dir
from hydromodpy.results.storage.contract import RUN_LOGS_DIRNAME
from hydromodpy.results.storage.json_io import readable

logger = get_logger(__name__)

SCHEDULER: Final[str] = "slurm"
"""Suffix of a SLURM job directory: ``jobs/<stamp>-slurm``."""

PREPARE_SCRIPT: Final[str] = "prepare.sh"
ARRAY_SCRIPT: Final[str] = "array.sh"
JOB_LOGS_DIRNAME: Final[str] = "logs"
"""Task logs of the job, before the case directory is known."""

PREPARED_DIRNAME: Final[str] = "prepared"
"""One empty file per prepared task; the last one writes ``hydromodpy.lock``."""

LOG_TAIL_LINES: Final[int] = 40
"""Lines of the task log kept in a ``failed`` outcome written by the trap."""


PHASES: Final[tuple[str, ...]] = ("prepare", "solve")
"""Phases of a task: ``prepare.sh`` runs the first, ``array.sh`` the second."""

LAUNCHED_BY: Final[str] = "slurm"
"""Value of ``HMP_LAUNCHED_CASE`` in a task."""


_SAFE_PATH = re.compile(r"^[\w./+@,-]+$")


@dataclass(frozen=True, slots=True)
class SlurmJob:
    """What ``hmp campaign array`` wrote under ``jobs/<stamp>-slurm/``."""

    directory: Path
    prepare_sh: Path
    array_sh: Path
    cases_txt: Path
    plan_hash: str
    n_cases: int
    threads_per_case: int
    cpus_per_task: int
    max_solves: int
    prepare_parallel: int
    job_name: str


def write_slurm_array(
    project_root: str | Path,
    *,
    stamp: str,
    partition: str | None = None,
    walltime: str | None = None,
    threads_per_case: int | None = None,
    prepare_parallel: int | None = None,
) -> SlurmJob:
    """Write ``jobs/<stamp>-slurm/`` for the current plan and return what it holds.

    *threads_per_case* and *prepare_parallel* default to ``[sites.run]`` of
    the project. The plan must be current: a project file or a table changed
    since ``hmp project plan`` is refused, so the job runs what the project
    says. A job directory is written once; the same stamp twice is refused.
    """
    root = Path(project_root).resolve()
    parse_stamp(stamp)
    _refuse_unsafe_path(root)
    stored = read_plan(root)
    if not stored.cases:
        raise ConfigError(f"plan {stored.plan.plan_hash} has no case; nothing to submit")
    if plan_is_stale(root, stored):
        raise ConfigError(
            f"plan {stored.plan.plan_hash} was made from files that changed since; run "
            "`hmp project plan .` before writing an array job"
        )
    run = sites_run_config(root)
    threads = _positive("threads_per_case", threads_per_case, run.threads_per_case)
    prepare = effective_prepare_parallel(
        _positive("prepare_parallel", prepare_parallel, run.prepare_parallel), force=False
    )
    max_solves = max(case.solves for case in planned_cases(stored))

    jobs = jobs_dir_for(root)
    name = f"{stamp}-{SCHEDULER}"
    final = jobs / name
    if final.exists():
        raise JobUsageError(f"{final} exists; a job directory is written once")
    project = re.sub(r"[^A-Za-z0-9_.-]", "_", root.name)
    common = {
        "DIRECTIVES": sbatch_directives(partition, walltime),
        "JOB": shlex.quote(name),
        "JOB_DIR": str(final),
        "LAUNCHED_BY": LAUNCHED_BY,
        "LAUNCHED_ENV": LAUNCHED_ENV,
        "N_CASES": str(len(stored.cases)),
        "PLAN_HASH": stored.plan.plan_hash,
        "PROJECT_ROOT": str(root),
        "PYTHON": shlex.quote(sys.executable),
        "STAMP": stamp,
        "TERM_GRACE_S": str(TERM_GRACE_S),
        "THREADS_ENV": THREADS_ENV,
        "THREADS_PER_CASE": str(threads),
    }
    job_name = f"hmp-{project}-{stamp}"
    scripts = {
        PREPARE_SCRIPT: {
            "JOB_NAME": f"hmp-prepare-{project}-{stamp}",
            "PREPARE_PARALLEL": str(prepare),
            "WORKER": worker_block("prepare"),
        },
        ARRAY_SCRIPT: {
            "CPUS_PER_TASK": str(threads * max_solves),
            "JOB_NAME": job_name,
            "MAX_SOLVES": str(max_solves),
            "WORKER": worker_block("solve"),
        },
    }
    texts = {script: render(script, {**common, **fields}) for script, fields in scripts.items()}
    plan_rel = stored.directory.relative_to(root).as_posix()
    case_files = [f"{plan_rel}/{case.config_path}" for case in stored.cases]
    _write_job_dir(jobs, final, case_files, texts)
    return SlurmJob(
        directory=final,
        prepare_sh=final / PREPARE_SCRIPT,
        array_sh=final / ARRAY_SCRIPT,
        cases_txt=final / CASES_FILENAME,
        plan_hash=stored.plan.plan_hash,
        n_cases=len(stored.cases),
        threads_per_case=threads,
        cpus_per_task=threads * max_solves,
        max_solves=max_solves,
        prepare_parallel=prepare,
        job_name=job_name,
    )


def _write_job_dir(jobs: Path, final: Path, case_files: list[str], texts: dict[str, str]) -> None:
    """Write the job directory beside its destination, then rename it into place in one step."""
    jobs.mkdir(parents=True, exist_ok=True)
    staging = jobs / f".staging-{final.name}-{uuid.uuid4().hex[:8]}"
    staging.mkdir()
    try:
        (staging / JOB_LOGS_DIRNAME).mkdir()
        (staging / PREPARED_DIRNAME).mkdir()
        write_case_list(staging, case_files)
        for script, text in texts.items():
            path = staging / script
            path.write_text(text, encoding="utf-8")
            path.chmod(0o755)
        if final.exists():
            raise JobUsageError(f"{final} exists; a job directory is written once")
        os.rename(staging, final)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def task_flags(project_root: str | Path, case_toml: str | Path, *, phase: str) -> list[str]:
    """Return the flags of ``hmp run <case_toml>`` for one task, as the local launcher picks them.

    ``prepare``: the prepare command of the case (geography and data, a
    calibration case run as a simulation). ``solve``: ``--frozen`` when
    ``hydromodpy.lock`` exists, plus ``--resume <case>`` when an earlier
    attempt of a simulation is unfinished, or a bare ``--resume`` when the
    session of a calibration is. The state is read when the task starts, so
    a task submitted again resumes its case.
    """
    root = Path(project_root).resolve()
    case = _planned_case(root, Path(case_toml))
    if phase == "prepare":
        return prepare_command(case)[len(worker_command(case)) :]
    if phase == "solve":
        frozen = project_lockfile_path(root).is_file()
        return worker_flags(case, state_of(root, case), frozen=frozen, fresh=False, force=False)
    raise JobUsageError(f"phase {phase!r} is not one of {', '.join(PHASES)}")


def write_lock(project_root: str | Path, case_toml: str | Path) -> Path | None:
    """Write ``hydromodpy.lock`` from the workspace cache the case resolves to.

    The workspace is the case's ``workspace.data_dir``, as the local
    launcher reads it, not the one around the project folder.
    """
    from hydromodpy.project.launch.lockfile import write_project_lockfile

    root = Path(project_root).resolve()
    case_path = Path(case_toml)
    if not case_path.is_absolute():
        case_path = root / case_path
    return write_project_lockfile(root, workspace_data_dir(case_path))


def _planned_case(root: Path, case_toml: Path) -> PlannedCase:
    """Return the case of *case_toml* as the plan that wrote it describes it."""
    path = case_toml if case_toml.is_absolute() else root / case_toml
    stored = read_plan(root, path.parent.name)
    for case in planned_cases(stored):
        if case.path.resolve() == path.resolve():
            return case
    raise JobUsageError(f"{path} is not a case of plan {stored.plan.plan_hash}")


def finish_task(
    project_root: str | Path,
    case_toml: str | Path,
    *,
    exit_code: int,
    log_path: str | Path | None = None,
    job_id: str | None = None,
) -> Outcome | None:
    """Close the directories of one task after its worker exited: the trap step.

    The task log is copied to ``logs/job-<job_id>.out`` of each directory of
    the case: its run, and its session for a calibration. A directory whose
    outcome still says ``running`` on this host, with its process gone, was
    left by a worker that died without a word: its outcome becomes ``failed``
    with the exit code, the signal (``exit_code - 128`` above 128), the log
    tail and ``written_by = "trap"``; a session also gets ``failed`` in its
    ``session.json``. Returns the last outcome written, or ``None`` when the
    worker wrote its own exit, never claimed a directory, or may still live.
    The death rule is the claim's: same host, process gone. The pid in the
    outcome is not compared with the child of the shell, since ``hmp`` may
    run behind a wrapper.
    """
    root = Path(project_root).resolve()
    case_id = Path(case_toml).stem
    log = Path(log_path) if log_path is not None else None
    signal = exit_code - 128 if exit_code > 128 else None
    message = dead_worker_message(exit_code, signal)
    closed: Outcome | None = None
    for directory in (latest_session_dir(root, case_id), latest_version_dir(root, case_id)):
        if directory is None:
            continue
        if log is not None and log.is_file() and job_id:
            logs = directory / RUN_LOGS_DIRNAME
            logs.mkdir(exist_ok=True)
            shutil.copyfile(log, logs / f"job-{job_id}.out")
        dead = _dead_outcome(directory)
        if dead is None:
            continue
        if session_descriptor_path(directory).is_file():
            outcome = close_dead_session(
                directory, dead, exit_code, signal, message, _tail(log), written_by="trap"
            )
        else:
            outcome = finish_attempt(
                directory,
                status="failed",
                error=RuntimeError(message),
                exit_code=exit_code,
                signal=signal,
                log_tail=_tail(log),
                written_by="trap",
            )
        if job_id and outcome.scheduler_job_id is None:
            outcome = outcome.model_copy(update={"scheduler_job_id": job_id})
            write_outcome(directory, outcome)
        closed = outcome
    return closed


def parse_stamp(stamp: str) -> datetime:
    try:
        return datetime.strptime(stamp, STAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError as exc:
        raise JobUsageError(f"stamp {stamp!r} is not {STAMP_FORMAT}") from exc


def _dead_outcome(directory: Path) -> Outcome | None:
    """Return the outcome when it says ``running`` for a process of this host that is gone."""
    outcome = readable(read_outcome, directory)
    if outcome is None or outcome.status != "running":
        return None
    if outcome.host != socket.gethostname() or process_is_alive(outcome.pid):
        return None
    return outcome


def _refuse_unsafe_path(root: Path) -> None:
    """Refuse a project path an ``#SBATCH`` line or a shell word cannot carry unquoted."""
    if not _SAFE_PATH.match(str(root)):
        raise ConfigError(
            f"{root}: an #SBATCH directive takes the project path unquoted; move the project "
            "to a path of letters, digits and . _ - + @ , only"
        )


def _positive(name: str, value: int | None, default: int) -> int:
    chosen = default if value is None else value
    if chosen < 1:
        raise ConfigError(f"{name} is {chosen}; it counts at least 1")
    return chosen


def _tail(log: Path | None) -> list[str]:
    if log is None or not log.is_file():
        return []
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-LOG_TAIL_LINES:]


def main(argv: list[str] | None = None) -> int:
    """Entry of ``python -m hydromodpy.project.launch.slurm``, called by the job scripts."""
    parser = argparse.ArgumentParser(
        prog="python -m hydromodpy.project.launch.slurm",
        description="Steps the SLURM job scripts of `hmp campaign array` run on a node.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    finish = sub.add_parser("finish-task", help="Close the run directory of one task")
    finish.add_argument("--project", required=True, help="Project root")
    finish.add_argument("--case-toml", required=True, help="Case TOML the task ran")
    finish.add_argument("--exit-code", type=int, required=True, help="Exit code of the worker")
    finish.add_argument("--log", default=None, help="Log of the task")
    finish.add_argument("--job-id", default=None, help="<array job>_<task>")
    flags = sub.add_parser("task-flags", help="Print the flags of `hmp run` for one task")
    flags.add_argument("--project", required=True, help="Project root")
    flags.add_argument("--case-toml", required=True, help="Case TOML the task runs")
    flags.add_argument("--phase", required=True, choices=PHASES, help="Phase of the task")
    lock = sub.add_parser("write-lock", help="Write hydromodpy.lock after the prepare phase")
    lock.add_argument("--project", required=True, help="Project root")
    lock.add_argument("--case-toml", required=True, help="A case TOML of the plan")
    args = parser.parse_args(argv)
    if args.command == "task-flags":
        for flag in task_flags(args.project, args.case_toml, phase=args.phase):
            print(flag)
        return 0
    if args.command == "write-lock":
        if write_lock(args.project, args.case_toml) is None:
            # As the local launcher: the solves then run without --frozen.
            print("hydromodpy.lock not written: the workspace has no data cache", file=sys.stderr)
        return 0
    outcome = finish_task(
        args.project,
        args.case_toml,
        exit_code=args.exit_code,
        log_path=args.log,
        job_id=args.job_id,
    )
    if outcome is not None:
        print(
            f"trap: {Path(args.case_toml).stem} failed (exit code {outcome.exit_code}, "
            f"signal {outcome.signal}); the worker wrote no outcome",
            file=sys.stderr,
        )
    return 0


__all__ = [
    "ARRAY_SCRIPT",
    "PHASES",
    "PREPARE_SCRIPT",
    "SCHEDULER",
    "SlurmJob",
    "finish_task",
    "parse_stamp",
    "task_flags",
    "write_lock",
    "write_slurm_array",
]


if __name__ == "__main__":
    raise SystemExit(main())
