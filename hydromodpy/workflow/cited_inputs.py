"""The cached files a run or a lockfile of a workspace cites, which no cleanup may remove.

A file of ``data/`` is cited by the ``inputs.json`` of a sealed run or a kept
trial, by its sha256, and by the ``hydromodpy.lock`` of a project. ``data``
cannot read the runs, so the two sets are computed here and handed to it: to
``hmp data prune``, and to the cache of a run, which never removes a cited grid
when a larger one arrives.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.core.exceptions import DataCacheError
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME, PROJECTS_DIRNAME
from hydromodpy.data.provenance.lockfile import (
    LockedInput,
    project_lockfile_path,
    read_lockfile_inputs,
)
from hydromodpy.results.catalog.federation import sealed_run_dirs
from hydromodpy.results.record.record import read_inputs


def _projects_of(workspace_root: Path) -> list[Path]:
    """Return the projects whose runs read the data folder of *workspace_root*."""
    root = Path(workspace_root).expanduser().resolve()
    projects: list[Path] = []
    if (root / PROJECT_MARKER_FILENAME).is_file():
        projects.append(root)
    projects_dir = root / PROJECTS_DIRNAME
    if projects_dir.is_dir():
        projects.extend(
            path
            for path in sorted(projects_dir.iterdir())
            if path.is_dir() and (path / PROJECT_MARKER_FILENAME).is_file()
        )
    return projects


def _locked_inputs(project_root: Path) -> list[LockedInput]:
    """Return the records of the lockfile of *project_root*, none without one.

    A lockfile that cannot be read is refused by name: a cleanup never guesses
    what a lockfile pins.
    """
    lockfile = project_lockfile_path(project_root)
    if not lockfile.is_file():
        return []
    try:
        return read_lockfile_inputs(lockfile)
    except Exception as exc:  # noqa: BLE001 - every reading fault refuses the same way
        raise DataCacheError(
            f"The lockfile {lockfile} cannot be read ({exc}), so the files it pins are "
            "unknown. Nothing was removed. Write it again with hmp data lock."
        ) from exc


def cited_input_digests(workspace_root: Path) -> frozenset[str]:
    """Return every sha256 a sealed run, a kept trial or a lockfile of the workspace cites.

    A workspace that is a project itself counts as one. A run whose
    ``inputs.json`` cannot be read, or a lockfile that cannot be read, is
    refused by name: a cleanup never guesses what a run read.
    """
    cited: set[str] = set()
    for project_root in _projects_of(workspace_root):
        for run_dir in sealed_run_dirs(project_root):
            try:
                inputs = read_inputs(run_dir).inputs
            except Exception as exc:  # noqa: BLE001 - every reading fault refuses the same way
                raise DataCacheError(
                    f"The inputs of the run {run_dir} cannot be read ({exc}), so the files it "
                    "cites are unknown. Nothing was removed."
                ) from exc
            cited.update(entry.sha256 for entry in inputs if entry.sha256)
        cited.update(item.sha256 for item in _locked_inputs(project_root) if item.sha256)
    return frozenset(cited)


def pinned_empty_paths(workspace_root: Path) -> frozenset[str]:
    """Return the path of every empty answer a lockfile of the workspace pins.

    An empty answer has no file and no sha256, so no digest names it. Each
    path is relative to the data folder, as the lockfile writes it. A
    ``--frozen`` run looks the answer up by that path, so a prune keeps it.
    """
    return frozenset(
        item.path
        for project_root in _projects_of(workspace_root)
        for item in _locked_inputs(project_root)
        if item.empty
    )


__all__ = ["cited_input_digests", "pinned_empty_paths"]
