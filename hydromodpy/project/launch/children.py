"""The cases of a plan as the launcher sees them, and the processes it starts.

Why
---
A case is launched as an ordinary ``hmp run plan/<hash>/<case>.toml`` in a
process of its own; the launcher holds no thread and shares no memory with
it. This module reads what the launcher needs from each case file (its
workflow and how many solves it runs side by side), starts the child with
the environment of a launched case and its own log file, and closes what
the child left behind: the outcome of a child that died without writing
one, and its private data cache.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import RUN_DATA_CACHE_FILENAME
from hydromodpy.project.launch.env import LAUNCHED_ENV, child_environment
from hydromodpy.project.launch.journal import CASE_CACHES_DIRNAME, CASE_LOGS_DIRNAME, Journal
from hydromodpy.project.launch.status import CaseState, case_state
from hydromodpy.results.plan_store import StoredPlan
from hydromodpy.workflow.dispatch import WorkflowName, workflow_of_sections

logger = get_logger(__name__)


LOG_TAIL_LINES = 20
"""Lines of a child log kept in the journal when the run log says nothing."""


@dataclass(frozen=True, slots=True)
class PlannedCase:
    """One case of the plan, with what the launcher reads from its file."""

    case_id: str
    site: str | None
    recipe: str | None
    config_hash: str
    path: Path
    workflow: WorkflowName
    solves: int

    @property
    def rel_path(self) -> str:
        """The case file relative to the project root, as ``cases.txt`` lists it."""
        return f"{self.path.parent.parent.name}/{self.path.parent.name}/{self.path.name}"


def planned_cases(stored: StoredPlan) -> list[PlannedCase]:
    """Return the cases of *stored*, in the order of the plan."""
    out: list[PlannedCase] = []
    for case in stored.cases:
        path = stored.directory / case.config_path
        with path.open("rb") as handle:
            document = tomllib.load(handle)
        workflow = workflow_of_sections(document)
        solves = 1
        if workflow == "calibration":
            calibration = document.get("calibration") or {}
            solves = max(1, int(calibration.get("parallel", 1) or 1))
        out.append(
            PlannedCase(
                case_id=case.case_id,
                site=case.site,
                recipe=case.recipe,
                config_hash=case.config_hash,
                path=path,
                workflow=workflow,
                solves=solves,
            )
        )
    return out


def worker_command(case: PlannedCase, flags: Sequence[str] = ()) -> list[str]:
    """Return the command line of the worker of *case*."""
    return [sys.executable, "-m", "hydromodpy", "run", str(case.path), *flags]


def prepare_command(case: PlannedCase) -> list[str]:
    """Return the command line of the prepare phase of *case*: geography and data only.

    A calibration case is prepared as a simulation of the same file: the
    window stops before the model, so no run directory and no session are
    claimed, and the data its trials read lands in the cache.
    """
    flags = ["--until", "load_data"]
    if case.workflow == "calibration":
        flags += ["--set", "workflow.mode=simulation"]
    return worker_command(case, flags)


@dataclass
class Child:
    """A case process the launcher started and has not reaped yet."""

    case: PlannedCase
    phase: str
    process: subprocess.Popen[bytes]
    log_path: Path
    private_cache: Path


def private_cache_of(job_dir: Path, case: PlannedCase, phase: str) -> Path:
    """Return the private data cache of one child: ``caches/<case>.<phase>/data-cache.duckdb``."""
    return job_dir / CASE_CACHES_DIRNAME / f"{case.case_id}.{phase}" / RUN_DATA_CACHE_FILENAME


def start_child(
    job_dir: Path,
    case: PlannedCase,
    command: Sequence[str],
    *,
    phase: str,
    threads_per_case: int,
    base_env: Mapping[str, str] | None = None,
) -> Child:
    """Start *command* for *case* with the environment of a launched case."""
    logs = job_dir / CASE_LOGS_DIRNAME
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / f"{case.case_id}.{phase}.log"
    cache = private_cache_of(job_dir, case, phase)
    env = child_environment(
        os.environ if base_env is None else base_env,
        threads_per_case=threads_per_case,
        private_cache=cache,
    )
    env[LAUNCHED_ENV] = "local"
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            list(command),
            cwd=case.path.parent,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    return Child(case=case, phase=phase, process=process, log_path=log_path, private_cache=cache)


def exit_of(returncode: int) -> tuple[int, int | None]:
    """Return the exit code and the signal of a reaped child."""
    if returncode < 0:
        return 128 - returncode, -returncode
    return returncode, None


def log_tail(path: Path, lines: int = LOG_TAIL_LINES) -> list[str]:
    """Return the last lines of a child log."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    return text.splitlines()[-lines:]


def close_dead_child(project_root: Path, child: Child, exit_code: int, signal: int | None) -> None:
    """Write ``failed`` for the attempt of a child that died without writing its outcome.

    Only the outcome that names the child itself is closed: a case another
    worker holds is left as it is.
    """
    from hydromodpy.results.storage.attempt import finish_dead_attempt
    from hydromodpy.results.storage.run_log import read_log_tail

    state = case_state(project_root, child.case.case_id)
    if state.rel_dir is None:
        return
    directory = Path(project_root) / state.rel_dir
    tail = read_log_tail(directory) or log_tail(child.log_path)
    finish_dead_attempt(
        directory,
        host=socket.gethostname(),
        pid=child.process.pid,
        exit_code=exit_code,
        signal=signal,
        log_tail=tail,
        written_by="launcher",
    )


def merge_child_cache(shared_cache: Path | None, child: Child, *, journal: Journal) -> int | None:
    """Merge the private cache of a reaped child into the shared cache; remove it.

    Return the entries merged, or ``None`` when the merge failed. A failed
    merge fails this case only: it is journaled (``merge_failed``) and the
    private cache stays on disk for a later look, so the launch goes on with
    the other cases.
    """
    from hydromodpy.data.registry.catalog_duckdb import merge_private_cache

    private = child.private_cache
    merged = 0
    if shared_cache is not None and private.is_file():
        try:
            merged = merge_private_cache(shared_cache, private)
        except Exception as exc:  # noqa: BLE001 - one unreadable cache must not end the launch
            logger.warning("Private cache of %s not merged: %s", child.case.case_id, exc)
            journal.append(
                "merge_failed",
                case_id=child.case.case_id,
                phase=child.phase,
                private_cache=str(private),
                error=f"{type(exc).__name__}: {exc}",
            )
            return None
    # The folder holds the private file, its write-ahead log and its backups only.
    shutil.rmtree(private.parent, ignore_errors=True)
    return merged


def state_of(project_root: Path, case: PlannedCase) -> CaseState:
    """Return what the directories of *case* say now."""
    return case_state(project_root, case.case_id)


__all__ = [
    "Child",
    "PlannedCase",
    "close_dead_child",
    "exit_of",
    "log_tail",
    "merge_child_cache",
    "planned_cases",
    "prepare_command",
    "private_cache_of",
    "start_child",
    "state_of",
    "worker_command",
]
