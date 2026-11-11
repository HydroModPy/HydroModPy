"""The cases of a plan as the launcher sees them, and the processes it starts.

Why
---
A case is launched as an ordinary ``hmp run plan/<hash>/<case>.toml`` in a
process of its own; the launcher holds no thread and shares no memory with
it. This module reads what the launcher needs from each case file (its
workflow and how many solves it runs side by side), starts the child with
the environment of a launched case and its own log file, and closes what
the child left behind: the outcome of a child that died without writing
one (and the descriptor of its session, for a calibration).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hydromodpy.core.state.host import host_name
from hydromodpy.project.launch.env import LAUNCHED_ENV, child_environment
from hydromodpy.project.launch.journal import CASE_LOGS_DIRNAME
from hydromodpy.project.launch.status import CaseState, case_state
from hydromodpy.results.outcome import Outcome, OutcomeError, WrittenBy, read_outcome, write_outcome
from hydromodpy.results.plan_store import StoredPlan
from hydromodpy.results.session.descriptor import (
    read_session,
    session_descriptor_path,
    write_session,
)
from hydromodpy.results.storage.json_io import readable
from hydromodpy.workflow.dispatch import WorkflowName, workflow_of_sections

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


def calibration_width(section: Mapping[str, Any]) -> int:
    """Return the trials a ``[calibration]`` section solves side by side at its widest.

    A phase that writes its own ``parallel`` uses it; the others use the
    section's. A calibration without phases uses the section's.
    """
    own = int(section.get("parallel") or 1)
    phases = section.get("phases") or []
    widths = [int(phase.get("parallel") or own) for phase in phases if isinstance(phase, Mapping)]
    return max(1, own if not widths else max(widths))


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
            solves = calibration_width(document.get("calibration") or {})
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


def worker_command(
    case: PlannedCase,
    flags: Sequence[str] = (),
    environment_flags: Sequence[str] = (),
) -> list[str]:
    """Return the command line of the worker of *case*.

    ``environment_flags`` are the three options of an Environment for one
    launched case: the worker is ``hmp run`` again and builds the same
    Environment from them, so the launcher passes both the flags and the
    environment it runs its cases under.
    """
    return [sys.executable, "-m", "hydromodpy", "run", str(case.path), *flags, *environment_flags]


def prepare_command(
    case: PlannedCase,
    environment_flags: Sequence[str] = (),
) -> list[str]:
    """Return the command line of the prepare phase of *case*: geography and data only.

    A calibration case is prepared as a simulation of the same file: the
    window stops before the model, so no run directory and no session are
    claimed, and the data its trials read lands in the cache. The flags of
    the environment ride the line like they ride the worker's, so the prepare
    fills the cache under the same bounds as the solve.
    """
    flags = ["--until", "load_data"]
    if case.workflow == "calibration":
        flags += ["--set", "workflow.mode=simulation"]
    return worker_command(case, flags, environment_flags=environment_flags)


@dataclass
class Child:
    """A case process the launcher started and has not reaped yet."""

    case: PlannedCase
    phase: str
    process: subprocess.Popen[bytes]
    log_path: Path


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
    env = child_environment(
        os.environ if base_env is None else base_env,
        threads_per_case=threads_per_case,
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
    return Child(case=case, phase=phase, process=process, log_path=log_path)


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


def dead_worker_message(exit_code: int | None, signal: int | None) -> str:
    """Return the error of a worker that ended without writing its outcome."""
    return f"the worker ended without writing its outcome (exit code {exit_code}, signal {signal})"


def close_dead_session(
    directory: Path,
    previous: Outcome,
    exit_code: int | None,
    signal: int | None,
    message: str,
    log_tail: list[str],
    *,
    written_by: WrittenBy,
) -> Outcome:
    """Write ``failed`` in the descriptor and the outcome of a session whose worker died."""
    now = datetime.now(UTC)
    descriptor = readable(read_session, directory)
    if descriptor is not None and descriptor.status == "running":
        write_session(
            directory,
            descriptor.model_copy(
                update={"status": "failed", "ended_at": now, "error_message": message}
            ),
        )
    outcome = previous.model_copy(
        update={
            "status": "failed",
            "ended_at": now,
            "exit_code": exit_code,
            "signal": signal,
            "written_by": written_by,
            "error": OutcomeError(type="RuntimeError", message=message),
            "log_tail": log_tail,
        }
    )
    write_outcome(directory, outcome)
    return outcome


def close_dead_child(project_root: Path, child: Child, exit_code: int, signal: int | None) -> None:
    """Write ``failed`` for the attempt of a child that died without writing its outcome.

    Only the outcome that names the child itself is closed: a case another
    worker holds is left as it is. A calibration case is its session: its
    descriptor is closed too, so the case reads ``failed`` and is started
    again.
    """
    from hydromodpy.results.storage.attempt import finish_dead_attempt
    from hydromodpy.results.storage.run_log import read_log_tail

    state = case_state(project_root, child.case.case_id)
    if state.rel_dir is None:
        return
    directory = Path(project_root) / state.rel_dir
    tail = read_log_tail(directory) or log_tail(child.log_path)
    host = host_name()
    if session_descriptor_path(directory).is_file():
        previous = readable(read_outcome, directory)
        if (
            previous is not None
            and previous.status == "running"
            and previous.host == host
            and previous.pid == child.process.pid
        ):
            close_dead_session(
                directory,
                previous,
                exit_code,
                signal,
                dead_worker_message(exit_code, signal),
                tail,
                written_by="launcher",
            )
        return
    finish_dead_attempt(
        directory,
        host=host,
        pid=child.process.pid,
        exit_code=exit_code,
        signal=signal,
        log_tail=tail,
        written_by="launcher",
    )


def state_of(project_root: Path, case: PlannedCase) -> CaseState:
    """Return what the directories of *case* say now."""
    return case_state(project_root, case.case_id)


__all__ = [
    "Child",
    "PlannedCase",
    "calibration_width",
    "close_dead_child",
    "close_dead_session",
    "dead_worker_message",
    "exit_of",
    "log_tail",
    "planned_cases",
    "prepare_command",
    "start_child",
    "state_of",
    "worker_command",
]
