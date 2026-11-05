"""What ``sacct`` says of the tasks of the SLURM array jobs of a project.

Why
---
A SIGKILL of a whole job leaves no trap (:func:`hydromodpy.project.launch.slurm.finish_task`):
only the scheduler knows the task ended. :func:`scheduler_states` reads
``sacct`` for each array job under ``jobs/`` and gives the latest task that
ran each case. A ``finished`` state is the scheduler's proof that the task no
longer runs, which a stale pulse alone never is. Without ``sacct`` on the
PATH it says nothing.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Final

from hydromodpy.core.logging import get_logger
from hydromodpy.project.launch.journal import job_dirs, read_case_list
from hydromodpy.project.launch.slurm import ARRAY_SCRIPT, SCHEDULER, parse_stamp

logger = get_logger(__name__)

SACCT_TIMEOUT_S: Final[float] = 30.0

TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {
        "BOOT_FAIL",
        "CANCELLED",
        "COMPLETED",
        "DEADLINE",
        "FAILED",
        "NODE_FAIL",
        "OUT_OF_MEMORY",
        "PREEMPTED",
        "REVOKED",
        "TIMEOUT",
    }
)
"""``sacct`` states of a task that no longer runs: the scheduler proves its end."""

_SACCT_JOB_ID = re.compile(r"^(\d+)_(\d+|\[[^\]]+\])$")


@dataclass(frozen=True, slots=True)
class SchedulerState:
    """What ``sacct`` says of the latest task that ran one case."""

    case_id: str
    job_id: str
    state: str
    exit_code: str

    @property
    def finished(self) -> bool:
        """Whether the scheduler says the task no longer runs."""
        return self.state in TERMINAL_STATES


def scheduler_states(project_root: str | Path) -> dict[str, SchedulerState]:
    """Return what ``sacct`` says of each case run by an array job of the project.

    Empty when ``sacct`` is not on the PATH. A case run by several jobs takes
    the latest job directory, and within one job the highest job id (a task
    submitted again). A ``finished`` state is the scheduler's proof that the
    task no longer runs, which a stale pulse alone never is.
    """
    if shutil.which("sacct") is None:
        return {}
    states: dict[str, SchedulerState] = {}
    for job_dir in job_dirs(Path(project_root)):
        stamp = job_dir.name.removesuffix(f"-{SCHEDULER}")
        if stamp == job_dir.name or not (job_dir / ARRAY_SCRIPT).is_file():
            continue
        job_name = _directive(job_dir / ARRAY_SCRIPT, "job-name")
        if job_name is None:
            continue
        cases = read_case_list(job_dir)
        # sacct reads local time and the stamp is UTC: a day earlier covers both.
        start = (parse_stamp(stamp) - timedelta(days=1)).strftime("%Y-%m-%d")
        latest: dict[int, tuple[int, SchedulerState]] = {}
        for base, task, state, exit_code in _sacct_rows(job_name, start):
            if not 1 <= task <= len(cases):
                continue
            row = SchedulerState(Path(cases[task - 1]).stem, f"{base}_{task}", state, exit_code)
            if task not in latest or base >= latest[task][0]:
                latest[task] = (base, row)
        for _, row in latest.values():
            states[row.case_id] = row
    return states


def _directive(script: Path, key: str) -> str | None:
    prefix = f"#SBATCH --{key}="
    for line in script.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def _sacct_rows(job_name: str, start: str) -> list[tuple[int, int, str, str]]:
    """Return ``(job id, task, state, exit code)`` for each task ``sacct`` knows."""
    command = [
        "sacct",
        f"--name={job_name}",
        f"--starttime={start}",
        "--allocations",
        "--parsable2",
        "--noheader",
        "--format=JobID,JobName,State,ExitCode",
    ]
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, timeout=SACCT_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("sacct could not be read for %s: %s", job_name, exc)
        return []
    if done.returncode != 0:
        logger.warning("sacct failed for %s: %s", job_name, done.stderr.strip())
        return []
    rows: list[tuple[int, int, str, str]] = []
    for line in done.stdout.splitlines():
        fields = line.strip().split("|")
        if len(fields) < 4:
            continue
        match = _SACCT_JOB_ID.match(fields[0])
        if match is None:
            continue
        state = fields[2].split()[0] if fields[2].strip() else "UNKNOWN"
        base = int(match.group(1))
        for task in _tasks(match.group(2)):
            rows.append((base, task, state, fields[3]))
    return rows


def _tasks(text: str) -> list[int]:
    """Return the task ids of ``7`` or of a pending range ``[3-5,9%2]``."""
    if not text.startswith("["):
        return [int(text)]
    tasks: list[int] = []
    for part in text.strip("[]").split("%")[0].split(","):
        low, _, high = part.partition("-")
        if not low.isdigit() or (high and not high.isdigit()):
            continue
        tasks.extend(range(int(low), int(high or low) + 1))
    return tasks


__all__ = ["SchedulerState", "TERMINAL_STATES", "scheduler_states"]
