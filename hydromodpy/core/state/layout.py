"""The layout of a project: the names of its folders and the paths built from them.

The layout constants live here so every layer (result storage, catalog readers,
CLI) shares a single source of truth without depending on a higher layer. A
project root is::

    project.toml            configuration, and the marker of the root
    configs/                config variants (user-managed, never created)
    runs/<case>[.vN]/       one directory per run; every artifact of a run lives in it
    sessions/<case>[.vN]/   one directory per calibration session
        trials/<nnnn>/      a kept trial of the session, itself a run directory
    summary/                derived tables, figures and report of a project of N cases
    plan/<hash>/            the immutable plan of a [sites] project; plan/current names it
    jobs/<stamp>/           the journal of each launch, array scripts, frozen case list
    trash/                  runs and sessions deleted by a move; tombstones.txt
    site_overrides/         <site>.toml, the per-site overlays of a [sites] project
    .hmp/                   strictly rebuildable: index, launcher lease, mesh cache, logs

Inside a run, ``.hmp/`` holds the state of the attempt in progress (scratch,
locks, checkpoints, private data cache) and is removed when a completed run is
sealed. The names of the files *inside* one run directory belong to the
result-storage contract (:mod:`hydromodpy.results.storage.contract`).

A *project* root holds ``project.toml`` and the index database at
``.hmp/index.duckdb``. A *workspace* root holds the shared ``data/`` tree,
``workspace.toml`` and a ``projects/`` directory. The other modules of this
folder read a result directory (``result_dirs.py``), keep the scratch of a live
run (``scratch.py``) and spell paths portably (``portable.py``).
"""

from __future__ import annotations

from pathlib import Path

# Project layout -----------------------------------------------------------
#
# The tree is drawn in the module docstring. Every directory name of that
# layout is declared here so no layer has to hard-code a literal.

PROJECT_MARKER_FILENAME = "project.toml"
"""The project configuration file, and the marker of a project root.

One file plays both roles: ``<project>/project.toml`` holds the shared
settings of the project and anchors :func:`resolve_project_root`. Creating a
project writes it, so a scaffolded project is anchored from its first day.
"""

CONFIGS_DIRNAME = "configs"
"""Reserved sub-directory holding the config variants of a project."""

RUNS_DIRNAME = "runs"
"""Directory holding one sub-directory per run at ``<project>/runs/<name>``."""

SESSIONS_DIRNAME = "sessions"
"""Directory holding calibration and spin-up sessions."""

TRIALS_DIRNAME = "trials"
"""Sub-directory of a session holding its kept trials, ``sessions/<name>/trials/<nnnn>``."""

TRIAL_DIRNAME_WIDTH = 4
"""Zero-padded width of a trial directory name: trial 4 is ``0004``."""

SUMMARY_DIRNAME = "summary"
"""Derived tables, figures and report of a project of N cases (``hmp campaign collect``)."""

PLAN_DIRNAME = "plan"
"""Immutable plans of a ``[sites]`` project, one ``plan/<hash>/`` per content."""

PLAN_CURRENT_FILENAME = "current"
"""File ``plan/current`` holding the hash of the plan in force."""

JOBS_DIRNAME = "jobs"
"""Journal of each launch, ``jobs/<stamp>-<scheduler>/``: journal, scripts, case list."""

TRASH_DIRNAME = "trash"
"""Runs and sessions deleted by a move, ``trash/<rel_dir>@<timestamp>/``."""

TOMBSTONES_FILENAME = "tombstones.txt"
"""File ``trash/tombstones.txt``: one line per emptied entry, so a name is never reused."""

SITE_OVERRIDES_DIRNAME = "site_overrides"
"""Per-site overlays of a ``[sites]`` project, ``site_overrides/<site>.toml``."""

INTERNAL_DIRNAME = ".hmp"
"""Rebuildable internals of a project, and the attempt state inside a run directory."""

LAUNCHER_LEASE_FILENAME = "launcher.lease"
"""Lease ``<project>/.hmp/launcher.lease`` held by the one launcher of a project."""

MESH_CACHE_DIRNAME = "mesh_cache"
"""Cache ``<project>/.hmp/mesh_cache/``; a run copies the entry it consumes into its own folder."""

RUN_INTERNAL_SCRATCH_DIRNAME = "scratch"
"""Solver scratch of the attempt in progress, ``runs/<case>/.hmp/scratch/``."""

RUN_INTERNAL_LOCKS_DIRNAME = "locks"
"""File locks of the attempt in progress, ``runs/<case>/.hmp/locks/``."""

RUN_INTERNAL_CHECKPOINTS_DIRNAME = "checkpoints"
"""Step checkpoints of the attempt in progress, ``runs/<case>/.hmp/checkpoints/``."""

RUN_DATA_CACHE_FILENAME = "data-cache.duckdb"
"""Private data cache of a launched case, merged by the launcher.

``jobs/<stamp>-local/caches/<case>.<phase>/data-cache.duckdb``.
"""

CATALOG_FILENAME = "index.duckdb"
"""Project index database living at ``<project>/.hmp/index.duckdb``."""

WORKSPACE_TOML_FILENAME = "workspace.toml"
"""Workspace-wide metadata file living at ``<workspace>/workspace.toml``."""

PROJECTS_DIRNAME = "projects"
"""Workspace sub-directory holding one directory per project."""

WORKSPACE_DATA_DIRNAME = "data"
"""Workspace sub-directory holding the shared input data, ``<workspace>/data/``."""

DATA_CACHE_FILENAME = "cache.duckdb"
"""Shared input-data cache database, ``<workspace>/data/cache.duckdb``."""


def internal_dir(project_root: Path) -> Path:
    """Return ``<project>/.hmp``, the disposable internals directory."""
    return Path(project_root) / INTERNAL_DIRNAME


def catalog_path_for(project_root: Path) -> Path:
    """Return the project index database ``<project>/.hmp/index.duckdb``."""
    return internal_dir(project_root) / CATALOG_FILENAME


def data_cache_path_for(data_dir: Path) -> Path:
    """Return the shared input-data cache ``<data_dir>/cache.duckdb``."""
    return Path(data_dir) / DATA_CACHE_FILENAME


def runs_dir_for(project_root: Path) -> Path:
    """Return ``<project>/runs``, the parent of every run directory."""
    return Path(project_root) / RUNS_DIRNAME


def sessions_dir_for(project_root: Path) -> Path:
    """Return ``<project>/sessions``, the parent of every session directory."""
    return Path(project_root) / SESSIONS_DIRNAME


def summary_dir_for(project_root: Path) -> Path:
    """Return ``<project>/summary``, the derived outputs of a project of N cases."""
    return Path(project_root) / SUMMARY_DIRNAME


def plan_dir_for(project_root: Path) -> Path:
    """Return ``<project>/plan``, the parent of every immutable plan."""
    return Path(project_root) / PLAN_DIRNAME


def jobs_dir_for(project_root: Path) -> Path:
    """Return ``<project>/jobs``, the journals of the launches."""
    return Path(project_root) / JOBS_DIRNAME


def trash_dir_for(project_root: Path) -> Path:
    """Return ``<project>/trash``, where deleted runs and sessions are moved."""
    return Path(project_root) / TRASH_DIRNAME


#: Members of a resolved configuration that differ between two launches of one
#: run and never change what it computes: the project root (where the project
#: folder sits on this machine). No run identity or checkpoint reads them.
PER_RUN_CONFIG_KEYS: tuple[tuple[str, str], ...] = (("workspace", "project_root"),)


# Root granularity ----------------------------------------------------------
#
# Two kinds of directory carry a HydroModPy layout and they are not
# interchangeable. A *project* root holds ``project.toml`` and the index
# database at ``.hmp/index.duckdb``. A *workspace* root holds the shared
# ``data/`` tree, ``workspace.toml`` and a ``projects/`` directory; it owns no
# index database. Anything that federates index databases therefore counts in
# project roots, and turns a workspace root into the project roots it holds.


def is_project_root(path: Path) -> bool:
    """Return True when ``path`` carries a project marker or an index database."""
    root = Path(path)
    return (root / PROJECT_MARKER_FILENAME).is_file() or catalog_path_for(root).is_file()


def is_workspace_root(path: Path) -> bool:
    """Return True when ``path`` carries ``workspace.toml`` or a ``projects/`` directory."""
    root = Path(path)
    return (root / WORKSPACE_TOML_FILENAME).is_file() or (root / PROJECTS_DIRNAME).is_dir()


def project_roots_under(root: Path) -> list[Path]:
    """Return the resolved project roots ``root`` stands for.

    A workspace root expands to the project roots it holds: itself when it is
    also one, then every ``projects/<name>`` that is. Any other directory is
    taken as a single project root, whether or not its index database exists
    yet, so a project can be registered before its first run.

    Every returned path is resolved, expanded entries included, so a project
    reached through a symlinked ``projects/<name>`` yields the same string as
    the same project named directly. Duplicates are dropped in first-seen
    order.
    """
    resolved = Path(root).expanduser().resolve()
    if not is_workspace_root(resolved):
        return [resolved]
    candidates: list[Path] = []
    if is_project_root(resolved):
        candidates.append(resolved)
    projects_dir = resolved / PROJECTS_DIRNAME
    if projects_dir.is_dir():
        candidates.extend(
            entry.resolve()
            for entry in sorted(projects_dir.iterdir())
            if entry.is_dir() and is_project_root(entry)
        )
    roots: list[Path] = []
    for candidate in candidates:
        if candidate not in roots:
            roots.append(candidate)
    return roots


__all__ = (
    "CATALOG_FILENAME",
    "CONFIGS_DIRNAME",
    "DATA_CACHE_FILENAME",
    "INTERNAL_DIRNAME",
    "JOBS_DIRNAME",
    "LAUNCHER_LEASE_FILENAME",
    "MESH_CACHE_DIRNAME",
    "PER_RUN_CONFIG_KEYS",
    "PLAN_CURRENT_FILENAME",
    "PLAN_DIRNAME",
    "PROJECTS_DIRNAME",
    "PROJECT_MARKER_FILENAME",
    "RUNS_DIRNAME",
    "RUN_DATA_CACHE_FILENAME",
    "RUN_INTERNAL_CHECKPOINTS_DIRNAME",
    "RUN_INTERNAL_LOCKS_DIRNAME",
    "RUN_INTERNAL_SCRATCH_DIRNAME",
    "SESSIONS_DIRNAME",
    "SITE_OVERRIDES_DIRNAME",
    "SUMMARY_DIRNAME",
    "TOMBSTONES_FILENAME",
    "TRASH_DIRNAME",
    "TRIALS_DIRNAME",
    "TRIAL_DIRNAME_WIDTH",
    "WORKSPACE_DATA_DIRNAME",
    "WORKSPACE_TOML_FILENAME",
    "catalog_path_for",
    "data_cache_path_for",
    "internal_dir",
    "is_project_root",
    "is_workspace_root",
    "jobs_dir_for",
    "plan_dir_for",
    "project_roots_under",
    "runs_dir_for",
    "sessions_dir_for",
    "summary_dir_for",
    "trash_dir_for",
)
