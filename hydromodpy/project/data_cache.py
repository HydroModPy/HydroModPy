"""The data cache seen from a project: the lockfile, and what a prune must keep.

``data`` owns the cache, its sidecars, the lockfile format and the prune. What
needs more than ``data`` sits here: the runs of each project (``results``),
the user files the configurations declare (``config.user_files``) and the sha256 of the
config schema. ``project`` computes, ``data`` acts.

A project inside a workspace reads the ``data/`` folder of the workspace. A
project without a workspace keeps its cache in its own ``data/`` folder.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.config.user_files import user_file_inputs
from hydromodpy.core.exceptions import ConfigError, DataCacheError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME, PROJECTS_DIRNAME
from hydromodpy.core.workspace.resolve import find_data_workspace, find_workspace
from hydromodpy.data.provenance.lockfile import (
    LockedInput,
    project_lockfile_path,
    read_lockfile_inputs,
    read_lockfile_schema_sha256,
    resolve_lockfile_root,
    verify_lockfile,
    write_lockfile,
)
from hydromodpy.data.provenance.sidecars import PruneReport, prune

logger = get_logger(__name__)


@dataclass(frozen=True)
class DataLock:
    """What ``hmp data lock`` wrote."""

    path: Path
    inputs: int
    user_files: int
    refused_configs: tuple[tuple[Path, str], ...] = ()


def data_root_for(project_root: Path) -> Path:
    """Return the data folder a project reads: its workspace's, else its own ``data/``."""
    root = Path(project_root).expanduser().resolve()
    workspace = find_data_workspace(root)
    return (workspace if workspace is not None else root) / "data"


def _workspace_data_root(workspace: Any) -> Path:
    """Return ``data/`` of the workspace named by *workspace*, which must exist."""
    root = find_workspace(str(workspace) if workspace else None)
    if root is None:
        raise FileNotFoundError(
            "No HydroModPy workspace found. Name one with -w, or run hmp workspace init."
        )
    return root / "data"


def _targets(workspace: Any, project: Any, lockfile: Any) -> tuple[Path, Path, Path]:
    """Return the data folder, the lockfile address and the project it describes.

    An explicit lockfile path is itself the address: the project it describes
    is the one named, else the folder the file lives in. Only a derived address
    asks :func:`resolve_lockfile_root` for a root, and that call refuses to
    answer outside a project.
    """
    explicit = Path(lockfile).expanduser().resolve() if lockfile else None
    if project:
        named = resolve_lockfile_root(project)
    elif explicit is not None:
        named = explicit.parent
    else:
        named = resolve_lockfile_root(None)
    data_root = _workspace_data_root(workspace) if workspace else data_root_for(named)
    return data_root, explicit if explicit is not None else project_lockfile_path(named), named


def lock_data(workspace: Any = None, *, project: Any = None, output: Any = None) -> DataLock:
    """Write ``hydromodpy.lock`` of one project: the rows of its data cache and its user files.

    The file carries the sha256 of the config schema, which ``hmp data lock
    --check --strict`` compares, and the git commit of the project.
    """
    from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
    from hydromodpy.schema.config_schema import schema_sha256

    data_root, dest, project_root = _targets(workspace, project, output)
    user_files, refused = user_file_inputs(project_root)
    for path, reason in refused:
        logger.warning("%s is not locked: it does not load (%s).", path, reason)
    if not data_root.is_dir() and not user_files:
        raise FileNotFoundError(
            f"No data folder at {data_root} and no user file declared: nothing to lock. "
            "Name the workspace with -w, or the project with --project."
        )
    write_lockfile(
        dest,
        data_root,
        user_files=user_files,
        schema_sha256=schema_sha256(ROOT_CONFIG.model),
        project_root=project_root,
    )
    return DataLock(
        path=dest,
        inputs=len(read_lockfile_inputs(dest)),
        user_files=len(user_files),
        refused_configs=tuple(refused),
    )


def verify_data_lock(
    workspace: Any = None,
    *,
    project: Any = None,
    lockfile: Any = None,
    strict: bool = False,
) -> dict:
    """Compare the files on disk with the lockfile of one project.

    ``schema_diverged`` says the config schema changed since the lockfile was
    written; ``hmp data lock --check --strict`` refuses on it.
    """
    from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
    from hydromodpy.schema.config_schema import schema_sha256

    data_root, lockfile_path, project_root = _targets(workspace, project, lockfile)
    if not lockfile_path.is_file():
        raise FileNotFoundError(f"Lockfile not found: {lockfile_path}")
    locked_schema = read_lockfile_schema_sha256(lockfile_path)
    current_schema = schema_sha256(ROOT_CONFIG.model)
    mismatches = verify_lockfile(data_root, lockfile_path, project_root=project_root, strict=strict)
    return {
        "ok": not mismatches,
        "mismatches": mismatches,
        "schema_diverged": locked_schema is not None and locked_schema != current_schema,
        "locked_schema": locked_schema,
        "current_schema": current_schema,
    }


class FrozenVerificationError(ConfigError, RuntimeError):
    """Raised when ``--frozen`` finds a lockfile drift before running anything."""


def verify_frozen_inputs(
    project_root: Path, declared_workspace: Mapping[str, Any] | None = None
) -> None:
    """Verify the project lockfile before a ``--frozen`` run of a project TOML.

    The lockfile is the one :func:`lock_data` writes, at the project root. The
    data folder is the one :class:`~hydromodpy.core.workspace.config.WorkspaceConfig`
    resolves from the ``[workspace]`` table the file declares, if any
    (*declared_workspace*). The check is strict: any mismatch aborts the run
    with :class:`FrozenVerificationError`.
    """
    from hydromodpy.core.toml_io.paths import resolve_declared_path
    from hydromodpy.core.workspace.config import WorkspaceConfig

    lockfile_path = project_lockfile_path(project_root)
    if not lockfile_path.is_file():
        raise FrozenVerificationError(
            f"hydromodpy.lock not found at {lockfile_path}; --frozen on a project TOML reads "
            "that file: write it with `hmp data lock`, or play a sealed run again with "
            "`hmp replay REF`."
        )

    declared = {
        key: str(resolve_declared_path(declared_workspace[key], base_dir=project_root))
        for key in ("root", "data_dir")
        if isinstance(declared_workspace, Mapping) and declared_workspace.get(key)
    }
    try:
        data_dir = WorkspaceConfig.model_validate(
            {**declared, "project_root": str(project_root)}
        ).data_dir
        mismatches = verify_lockfile(
            data_dir, lockfile_path, project_root=project_root, strict=True
        )
    except Exception as exc:  # noqa: BLE001 - any lockfile or data folder error aborts the run
        raise FrozenVerificationError(f"Could not verify lockfile {lockfile_path}: {exc}") from exc
    if mismatches:
        first = mismatches[0]
        raise FrozenVerificationError(
            f"{len(mismatches)} lockfile mismatch(es); first: "
            f"{first.kind} on {first.path} (variable={first.variable})"
        )


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

    A lockfile that cannot be read is refused by name: a prune never guesses
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
            "unknown. Nothing was pruned. Write it again with hmp data lock."
        ) from exc


def cited_input_digests(workspace_root: Path) -> frozenset[str]:
    """Return every sha256 a sealed run, a kept trial or a lockfile of the workspace cites.

    A workspace that is a project itself counts as one. A run whose
    ``inputs.json`` cannot be read, or a lockfile that cannot be read, is
    refused by name: a prune never guesses what a run read.
    """
    from hydromodpy.results.catalog.federation import sealed_run_dirs
    from hydromodpy.results.record.record import read_inputs

    cited: set[str] = set()
    for project_root in _projects_of(workspace_root):
        for run_dir in sealed_run_dirs(project_root):
            try:
                inputs = read_inputs(run_dir).inputs
            except Exception as exc:  # noqa: BLE001 - every reading fault refuses the same way
                raise DataCacheError(
                    f"The inputs of the run {run_dir} cannot be read ({exc}), so the files it "
                    "cites are unknown. Nothing was pruned."
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


def prune_data(
    workspace_root: Path,
    *,
    older_than_days: float | None = None,
    delete_files: bool = False,
    dry_run: bool = False,
) -> PruneReport:
    """Prune ``data/`` of *workspace_root*, keeping every row a run or a lockfile cites."""
    root = Path(workspace_root).expanduser().resolve()
    return prune(
        root / "data",
        keep=cited_input_digests(root),
        keep_empty=pinned_empty_paths(root),
        older_than_days=older_than_days,
        delete_files=delete_files,
        dry_run=dry_run,
    )


__all__ = [
    "DataLock",
    "cited_input_digests",
    "data_root_for",
    "lock_data",
    "pinned_empty_paths",
    "prune_data",
    "verify_data_lock",
]
