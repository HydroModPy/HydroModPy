"""Read the sealed runs of several projects without any index.

Why
---
A workspace holds many projects, each with its own index, and a machine may
hold many workspaces. Nothing federates them: the one-row
``tables.parquet/simulation.parquet`` every sealed run carries is the row of
the index on disk, with its schema in the file. Reading those files is
enough to list, filter and rank the runs of any set of projects, and it works
on a project whose index was never built.

What the row does not carry
---------------------------
The ``label`` is computed at indexing time, from the rules of the build
that indexes, so the federated frame has no ``label`` column: a reader that
wants the calibrated runs of a workspace filters on ``calibrated_by_session_id``
and ``converged``, or opens each project index. The run name is the one the
seal was written with: a directory renamed since keeps its old name here.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd
import pyarrow as pa

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import (
    TRIALS_DIRNAME,
    project_roots_under,
    runs_dir_for,
    sessions_dir_for,
)
from hydromodpy.results.storage.contract import (
    PARQUET_FILE_SUFFIX,
    RUN_MANIFEST_FILENAME,
    SIMULATION_TABLE_NAME,
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.json_io import readable
from hydromodpy.results.storage.parquet_io import read_checked_table

logger = get_logger(__name__)

PROJECT_ROOT_COLUMN = "project_root"
"""Column added to the federated frame: the project the row was read from."""


def sealed_run_dirs(project_root: Path | str) -> list[Path]:
    """Return the sealed run directories of a project: runs and kept trials."""
    root = Path(project_root)
    found: list[Path] = []
    runs_dir = runs_dir_for(root)
    if runs_dir.is_dir():
        found.extend(p for p in sorted(runs_dir.iterdir()) if _is_sealed(p))
    sessions_dir = sessions_dir_for(root)
    if sessions_dir.is_dir():
        for session in sorted(sessions_dir.iterdir()):
            trials = session / TRIALS_DIRNAME
            if trials.is_dir():
                found.extend(p for p in sorted(trials.iterdir()) if _is_sealed(p))
    return found


def _is_sealed(path: Path) -> bool:
    return (
        path.is_dir() and not path.name.startswith(".") and (path / RUN_MANIFEST_FILENAME).is_file()
    )


def _snapshot_of(run_dir: Path) -> Path:
    return run_dir / TABLES_DIRNAME / f"{SIMULATION_TABLE_NAME}{PARQUET_FILE_SUFFIX}"


def read_project_runs(project_root: Path | str) -> pd.DataFrame:
    """Return the sealed runs of one project, one row each, from their Parquet rows.

    A sealed run without its ``simulation.parquet`` is reported and skipped.
    """
    root = Path(project_root).expanduser().resolve()
    tables: list[pa.Table] = []
    for run_dir in sealed_run_dirs(root):
        snapshot = _snapshot_of(run_dir)
        if not snapshot.is_file():
            logger.warning("%s is sealed but carries no %s; skipped", run_dir, snapshot.name)
            continue
        table = readable(read_checked_table, snapshot)
        if table is None:
            continue
        tables.append(
            table.append_column(PROJECT_ROOT_COLUMN, pa.array([str(root)] * table.num_rows))
        )
    if not tables:
        return pd.DataFrame()
    return pa.concat_tables(tables, promote_options="default").to_pandas()


def read_workspace_runs(roots: Path | str | Iterable[Path | str]) -> pd.DataFrame:
    """Return the sealed runs of every project under ``roots``, one row each.

    ``roots`` is a workspace root, a project root or several of them. A
    workspace root expands to the projects it holds
    (:func:`hydromodpy.core.state.paths.project_roots_under`). The frame
    carries the columns of ``simulation.parquet`` plus ``project_root``.
    """
    if isinstance(roots, (str, Path)):
        roots = [roots]
    frames: list[pd.DataFrame] = []
    seen: set[Path] = set()
    for root in roots:
        for project in project_roots_under(Path(root)):
            if project in seen:
                continue
            seen.add(project)
            frame = read_project_runs(project)
            if not frame.empty:
                frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


__all__ = ["PROJECT_ROOT_COLUMN", "read_project_runs", "read_workspace_runs", "sealed_run_dirs"]
