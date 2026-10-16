"""The prepare phase: fetch the inputs of every case before any case solves.

Why
---
The plan cannot know the inputs of a case: the extent is the catchment the
case delineates itself, and a miss downloads and registers the file in the
workspace cache. So each case first runs ``hmp run <case>.toml --until
load_data`` (geography then data, no mesh, no solve, no run directory), in a
pool of ``[sites.run] prepare_parallel`` processes. Two cases of one site
are never prepared side by side: they ask for the same data, and two
children would write the same files of ``data/`` at once (the sidecar, the
cache entry and the lockfile would then name the bytes of the first writer
while the disk holds the second's). The second case of a site starts once
the first has ended and its cache is merged, so it finds the files in the
cache, or fetches only what its own recipe asks for. A prepare child never
writes the shared ``cache.duckdb``: it reads it one query at a time and
registers what it fetched in a private cache, which the launcher merges as
soon as the child has ended. The launcher is therefore the one writer of
the shared cache, and only between children. When every case is prepared
the launcher writes ``hydromodpy.lock`` once, from the shared cache, and
the workers then run ``--frozen`` against it. The scratch folder a prepare
child leaves behind (``.hmp/scratch/<case>.p<pid>/``, its preprocessing
tree) is removed once the child is reaped.
"""

from __future__ import annotations

import shutil
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import scratch_root_for
from hydromodpy.project.launch.children import (
    Child,
    PlannedCase,
    exit_of,
    log_tail,
    merge_child_cache,
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
    merged_entries: int


def workspace_data_dir(case_path: Path) -> Path:
    """Return the workspace ``data/`` folder the case file resolves to."""
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig

    return Path(HydroModPyConfig.from_toml(case_path).workspace.data_dir)


def data_request_key(case: PlannedCase) -> str:
    """Return the key of the data a case asks for: its site, else the case itself."""
    return case.site if case.site is not None else case.case_id


def _next_free(pending: deque[PlannedCase], busy: set[str]) -> PlannedCase | None:
    """Pop the first pending case whose data no running child is fetching."""
    for case in pending:
        if data_request_key(case) not in busy:
            pending.remove(case)
            return case
    return None


def prepare_cases(
    project_root: Path,
    job_dir: Path,
    cases: Sequence[PlannedCase],
    *,
    journal: Journal,
    shared_cache: Path | None,
    parallel: int,
    threads_per_case: int,
) -> list[PreparedCase]:
    """Run the prepare phase of *cases*, *parallel* at a time; merge each private cache.

    One case per site at a time: cases of the same site share their files of
    ``data/``, so the next one waits until the first has ended and merged.
    """
    pending = deque(cases)
    running: list[Child] = []
    done: list[PreparedCase] = []
    try:
        while pending or running:
            while len(running) < max(1, parallel):
                busy = {data_request_key(child.case) for child in running}
                case = _next_free(pending, busy)
                if case is None:
                    break
                journal.append("prepare_start", case_id=case.case_id)
                running.append(
                    start_child(
                        job_dir,
                        case,
                        prepare_command(case),
                        phase="prepare",
                        threads_per_case=threads_per_case,
                    )
                )
            reaped = [child for child in running if child.process.poll() is not None]
            for child in reaped:
                running.remove(child)
                done.append(_close(project_root, child, journal=journal, shared_cache=shared_cache))
            if not reaped:
                time.sleep(POLL_INTERVAL_S)
    except BaseException:
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


def _close(
    project_root: Path, child: Child, *, journal: Journal, shared_cache: Path | None
) -> PreparedCase:
    returncode = child.process.returncode
    assert returncode is not None
    exit_code, signal = exit_of(returncode)
    merged = merge_child_cache(shared_cache, child, journal=journal)
    _drop_child_scratch(project_root, child)
    ok = exit_code == 0 and merged is not None
    journal.append(
        "prepare_end",
        case_id=child.case.case_id,
        status="completed" if ok else "failed",
        exit_code=exit_code,
        signal=signal,
        merged_entries=merged or 0,
        log=str(child.log_path),
        log_tail=[] if ok else log_tail(child.log_path),
    )
    return PreparedCase(
        case_id=child.case.case_id,
        ok=ok,
        exit_code=exit_code,
        signal=signal,
        merged_entries=merged or 0,
    )


def write_lockfile_once(project_root: Path, data_dir: Path, journal: Journal) -> Path | None:
    """Write ``hydromodpy.lock`` from the shared cache and journal it."""
    from hydromodpy.project.lockfile import write_project_lockfile

    path = write_project_lockfile(project_root, data_dir)
    journal.append("lockfile", path=None if path is None else str(path))
    return path


__all__ = [
    "POLL_INTERVAL_S",
    "PreparedCase",
    "data_request_key",
    "prepare_cases",
    "workspace_data_dir",
    "write_lockfile_once",
]
