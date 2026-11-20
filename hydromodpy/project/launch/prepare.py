"""The prepare phase: fetch the inputs of every case before any case solves.

Why
---
The plan cannot know the inputs of a case: the extent is the catchment the
case delineates itself, and a miss downloads and registers the file in the
workspace cache. So each case first runs ``hmp run <case>.toml --until
load_data`` (geography then data, no mesh, no solve, no run directory), in a
pool of ``[sites.run] prepare_parallel`` processes. Two cases of one site
are never prepared side by side: they ask for the same data, and two
children would write the same grids and files of ``data/`` at once. A
prepare child writes its files and their sidecars straight into the shared
``data/`` folder, a file by ``.part`` and ``os.replace`` and its sidecar
after it, and a station chronicle under its file lock, so no merge follows.
A child that fetches a large grid removes the smaller grids it contains,
but never one another child wrote after it started, since a child of a
nested site may still be reading it. A grid written by a sibling just
before this child started can still be removed while that sibling reads
it. Moving that cleanup to ``hmp data prune`` would close the gap, and it
is left open.
The second case of a site starts once the first has ended, so it finds the
files in the cache, or fetches only what its own recipe asks for. When
every case is prepared the launcher writes ``hydromodpy.lock`` once, from
the sidecars of ``data/``, and the workers then run ``--frozen`` against it.
The scratch folder a prepare child leaves behind
(``.hmp/scratch/<case>.p<pid>/``, its preprocessing tree) is removed once
the child is reaped.
"""

from __future__ import annotations

import shutil
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.scratch import scratch_root_for
from hydromodpy.project.launch.children import (
    Child,
    PlannedCase,
    exit_of,
    log_tail,
    prepare_command,
    start_child,
)
from hydromodpy.project.launch.journal import Journal

logger = get_logger(__name__)

POLL_INTERVAL_S = 0.2
"""How often the launcher looks at its children."""


@dataclass(frozen=True, slots=True)
class PreparedCase:
    """How the prepare phase of one case ended."""

    case_id: str
    ok: bool
    exit_code: int
    signal: int | None


def workspace_data_dir(case_path: Path) -> Path:
    """Return the workspace ``data/`` folder the case file resolves to."""
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig

    return Path(HydroModPyConfig.from_toml(case_path).workspace.data_dir)


def _data_request_key(case: PlannedCase) -> str:
    """Return the key of the data a case asks for: its site, else the case itself."""
    return case.site if case.site is not None else case.case_id


def _next_free(pending: deque[PlannedCase], busy: set[str]) -> PlannedCase | None:
    """Pop the first pending case whose data no running child is fetching."""
    for case in pending:
        if _data_request_key(case) not in busy:
            pending.remove(case)
            return case
    return None


def prepare_cases(
    project_root: Path,
    job_dir: Path,
    cases: Sequence[PlannedCase],
    *,
    journal: Journal,
    parallel: int,
    threads_per_case: int,
    environment_flags: Sequence[str] = (),
) -> list[PreparedCase]:
    """Run the prepare phase of *cases*, *parallel* at a time.

    One case per site at a time: cases of the same site share their files of
    ``data/``, so the next one waits until the first has ended.
    ``environment_flags`` are the three Environment options the launcher
    received, carried on the command line of the prepare child too, so the
    prepare and the solve of one case play under the same Environment.
    """
    pending = deque(cases)
    running: list[Child] = []
    done: list[PreparedCase] = []
    try:
        while pending or running:
            while len(running) < max(1, parallel):
                busy = {_data_request_key(child.case) for child in running}
                case = _next_free(pending, busy)
                if case is None:
                    break
                journal.append("prepare_start", case_id=case.case_id)
                running.append(
                    start_child(
                        job_dir,
                        case,
                        prepare_command(case, environment_flags=environment_flags),
                        phase="prepare",
                        threads_per_case=threads_per_case,
                    )
                )
            reaped = [child for child in running if child.process.poll() is not None]
            for child in reaped:
                running.remove(child)
                done.append(_close(project_root, child, journal=journal))
            if not reaped:
                time.sleep(POLL_INTERVAL_S)
    except BaseException:
        # Also SIGINT of the launcher: stop the children before the error goes on.
        for child in running:
            child.process.terminate()
        for child in running:
            child.process.wait()
        raise
    return done


def _drop_child_scratch(project_root: Path, child: Child) -> None:
    """Remove the scratch folders a reaped prepare child named after its pid."""
    root = scratch_root_for(project_root)
    if not root.is_dir():
        return
    for folder in root.glob(f"*.p{child.process.pid}"):
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)


def _close(project_root: Path, child: Child, *, journal: Journal) -> PreparedCase:
    returncode = child.process.returncode
    assert returncode is not None
    exit_code, signal = exit_of(returncode)
    _drop_child_scratch(project_root, child)
    ok = exit_code == 0
    journal.append(
        "prepare_end",
        case_id=child.case.case_id,
        status="completed" if ok else "failed",
        exit_code=exit_code,
        signal=signal,
        log=str(child.log_path),
        log_tail=[] if ok else log_tail(child.log_path),
    )
    return PreparedCase(
        case_id=child.case.case_id,
        ok=ok,
        exit_code=exit_code,
        signal=signal,
    )


def write_lockfile_once(project_root: Path, data_dir: Path, journal: Journal) -> Path | None:
    """Write ``hydromodpy.lock`` from the sidecars of ``data_dir`` and journal it."""
    from hydromodpy.project.launch.lockfile import write_project_lockfile

    path = write_project_lockfile(project_root, data_dir)
    journal.append("lockfile", path=None if path is None else str(path))
    return path


__all__ = [
    "POLL_INTERVAL_S",
    "PreparedCase",
    "prepare_cases",
    "workspace_data_dir",
    "write_lockfile_once",
]
