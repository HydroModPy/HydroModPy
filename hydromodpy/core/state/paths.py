"""XDG-compliant path helpers and workspace path utilities.

Cache directory: binaries (solver downloads, http_cache).
State directory: index.duckdb, locks, audit.log.
Override env vars: HMP_CACHE_HOME, HMP_STATE_HOME, HMP_BIN.

Workspace layout constants and portable-path helpers also live here so
every layer (catalog writes, global index, CLI) shares a single source
of truth without depending on a higher layer.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from urllib.request import url2pathname

import platformdirs
from upath import UPath

from hydromodpy.core.exceptions import ConfigError

if TYPE_CHECKING:
    from collections.abc import Iterable

_APP_NAME = "hydromodpy"

# Project layout -----------------------------------------------------------
#
# A project root is::
#
#     project.toml            configuration, and the marker of the root
#     configs/                config variants (user-managed, never created)
#     runs/<name>/            one directory per run, named after the run
#     sessions/<name>/        calibration and spin-up sessions
#     share/                  on-demand exports, reports and portable packages
#     .hmp/                   disposable internals (index, trash, scratch, ...)
#
# Every directory name of that layout is declared here so no layer has to
# hard-code a literal. The names of the files *inside* one run directory
# belong to the result-storage contract
# (:mod:`hydromodpy.results.storage.contract`).

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

SHARE_DIRNAME = "share"
"""Directory holding on-demand exports and portable packages."""

REPORTS_DIRNAME = "reports"
"""Report sub-directory of :data:`SHARE_DIRNAME`."""

INTERNAL_DIRNAME = ".hmp"
"""Disposable internals: index database, trash, scratch, logs, cache."""

CATALOG_FILENAME = "index.duckdb"
"""Project index database living at ``<project>/.hmp/index.duckdb``."""

WORKSPACE_TOML_FILENAME = "workspace.toml"
"""Workspace-wide metadata file living at ``<workspace>/workspace.toml``."""

PROJECTS_DIRNAME = "projects"
"""Workspace sub-directory holding one directory per project."""

INDEX_FILENAME = "index.duckdb"
"""Machine-wide global index file living under ``state_dir()``."""


def display_path(path: Path | str) -> str:
    """Return *path* as the shortest spelling a reader can still follow.

    Console lines carry absolute paths that are mostly the same prefix
    repeated. Relative to the current directory when the path sits under
    it, absolute otherwise.
    """
    resolved = Path(path)
    try:
        return str(resolved.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(resolved)


def internal_dir(project_root: Path) -> Path:
    """Return ``<project>/.hmp``, the disposable internals directory."""
    return Path(project_root) / INTERNAL_DIRNAME


def catalog_path_for(project_root: Path) -> Path:
    """Return the project index database ``<project>/.hmp/index.duckdb``."""
    return internal_dir(project_root) / CATALOG_FILENAME


def runs_dir_for(project_root: Path) -> Path:
    """Return ``<project>/runs``, the parent of every run directory."""
    return Path(project_root) / RUNS_DIRNAME


def share_dir_for(project_root: Path) -> Path:
    """Return ``<project>/share``, where on-demand outputs are published."""
    return Path(project_root) / SHARE_DIRNAME


def reports_dir_for(project_root: Path) -> Path:
    """Return ``<project>/share/reports``."""
    return share_dir_for(project_root) / REPORTS_DIRNAME


#: Environment variable naming the scratch folder of the run this process is inside.
#: A subprocess inherits it, so a child run launched by a run works in its folder.
RUN_SCRATCH_ENV = "HMP_RUN_SCRATCH"

#: Folder of the geographic, data and mesh preprocessing, inside a run's scratch.
PREPROCESSING_DIRNAME = "_preprocessing"

_RUN_SCRATCH_SUFFIX = re.compile(r"\.p(\d+)$")
_RUN_SCRATCH_GUARD = threading.Lock()
_run_scratch_depth = 0


def scratch_root_for(output_root: Path) -> Path:
    """Return ``<root>/.hmp/scratch``, which holds the scratch folder of every run."""
    return internal_dir(output_root) / "scratch"


def active_run_scratch() -> str | None:
    """Return the scratch folder name of the run this process is inside, or None."""
    return os.environ.get(RUN_SCRATCH_ENV, "").strip() or None


def scratch_dir_for(output_root: Path) -> Path:
    """Return the solver working directory of the current run.

    Inside a run (:func:`run_scratch`) it is ``<root>/.hmp/scratch/<run>``, one
    folder per run, so two runs of one project work side by side: neither reads
    the preprocessing, the shared recharge or the solver files of the other, and
    a run that ends sweeps only its own. Outside any run it is the bare
    ``<root>/.hmp/scratch``.
    """
    key = active_run_scratch()
    root = scratch_root_for(output_root)
    return root / key if key else root


def preprocessing_dir(project_root: Path) -> Path:
    """Return the preprocessing folder of the current run, under its scratch."""
    return scratch_dir_for(project_root) / PREPROCESSING_DIRNAME


def kept_preprocessing_dir(project_root: Path) -> Path | None:
    """Return the preprocessing folder a finished run kept on disk, or None.

    A run keeps its tree only when asked to (``[geographic] write_intermediates``).
    A reader after the run is inside no run, so it looks for the bare folder,
    then for the most recent one a run left in its own scratch folder.
    """
    root = scratch_root_for(project_root)
    bare = root / PREPROCESSING_DIRNAME
    if bare.is_dir():
        return bare
    kept = [path for path in root.glob(f"*/{PREPROCESSING_DIRNAME}") if path.is_dir()]
    return max(kept, key=lambda path: path.stat().st_mtime) if kept else None


def _run_scratch_name(label: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", label).strip("_")[:24] or "run"
    return f"{stem}.p{os.getpid()}"


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def sweep_dead_run_scratch(project_root: Path) -> list[Path]:
    """Remove the scratch folders of runs whose process no longer runs.

    A run sweeps its own folder when it ends. One that was killed cannot, so the
    next run of the project removes the folders named after a dead process.
    POSIX only: elsewhere a process cannot be probed and nothing is removed.
    """
    import shutil

    if os.name != "posix":
        return []
    root = scratch_root_for(project_root)
    if not root.is_dir():
        return []
    removed: list[Path] = []
    for child in root.iterdir():
        match = _RUN_SCRATCH_SUFFIX.search(child.name)
        if not child.is_dir() or match is None:
            continue
        pid = int(match.group(1))
        if pid == os.getpid() or _process_is_alive(pid):
            continue
        shutil.rmtree(child, ignore_errors=True)
        removed.append(child)
    return removed


@contextmanager
def run_scratch(project_root: Path, label: str) -> Iterator[str]:
    """Give the run this process starts its own folder under ``.hmp/scratch/``.

    The outermost call names the folder after ``label`` and this process, and
    exports it through :data:`RUN_SCRATCH_ENV`; nested calls (the trials, phases
    and promotions of a calibration session) and child processes work in the
    same folder. On entry it also removes the folders of runs that were killed.
    On exit it removes the run's folder when nothing is left in it.
    """
    global _run_scratch_depth
    with _RUN_SCRATCH_GUARD:
        inherited = active_run_scratch()
        owner = inherited is None and _run_scratch_depth == 0
        key = inherited or _run_scratch_name(label)
        if owner:
            os.environ[RUN_SCRATCH_ENV] = key
        _run_scratch_depth += 1
    if owner:
        sweep_dead_run_scratch(project_root)
    try:
        yield key
    finally:
        with _RUN_SCRATCH_GUARD:
            _run_scratch_depth -= 1
            if owner:
                os.environ.pop(RUN_SCRATCH_ENV, None)
        if owner:
            for folder in (scratch_root_for(project_root) / key, scratch_root_for(project_root)):
                try:
                    folder.rmdir()
                except OSError:
                    break


def running_sidecar_dir(workspace: Path) -> Path:
    """Directory of live-run heartbeat sidecars under a project root.

    A solving run keeps ``<workspace>/.hmp/running/<id8>.json`` fresh so
    ``hmp catalog watch`` and ``hmp catalog gc`` read liveness from a file, never the DuckDB
    catalog (which a live solve holds locked).
    """
    return internal_dir(workspace) / "running"


def running_sidecar_path(workspace: Path, sim_id: str) -> Path:
    """Heartbeat sidecar path for a run, keyed by its first 8 hex digits."""
    id8 = str(sim_id).replace("-", "")[:8]
    return running_sidecar_dir(workspace) / f"{id8}.json"


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


# Portable URI schemes ------------------------------------------------------

_LOCAL_SCHEMES: tuple[str, ...] = ("file",)


def cache_dir() -> Path | UPath:
    """Return platform cache dir (HMP_CACHE_HOME override)."""
    override = os.environ.get("HMP_CACHE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path(platformdirs.user_cache_dir(_APP_NAME))


def state_dir() -> Path | UPath:
    """Return platform state dir (HMP_STATE_HOME override)."""
    override = os.environ.get("HMP_STATE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path(platformdirs.user_state_dir(_APP_NAME))


# Workspace-relative path helpers ------------------------------------------


def resolve_project_root(start: Path) -> Path:
    """Walk up from ``start`` to the directory holding ``project.toml``.

    The anchor is the project config file, never a database file: the catalog
    is a rebuildable index and may be absent. Without a marker the starting
    directory is the root, so a flat project directory still resolves. A
    ``configs/`` directory is the exception: anchoring there would scatter the
    project outputs under the sub-directory, so it raises instead.
    """
    base = Path(start)
    for parent in [base, *base.parents]:
        if (parent / PROJECT_MARKER_FILENAME).is_file():
            return parent
    if base.name == CONFIGS_DIRNAME:
        raise ConfigError(
            f"No {PROJECT_MARKER_FILENAME} found above {base}. A config stored in "
            f"{CONFIGS_DIRNAME}/ cannot anchor a project root: add "
            f"{PROJECT_MARKER_FILENAME} to {base.parent}."
        )
    return base


def to_workspace_relative(workspace: Path | UPath, target: Path | UPath) -> str:
    """Return ``target`` expressed as a POSIX path relative to ``workspace``.

    Both paths are resolved before comparison. Raises ``ValueError`` when
    ``target`` is not under ``workspace`` so callers never silently store
    an absolute path in a portable column.
    """
    ws = Path(workspace).expanduser().resolve()
    tgt = Path(target).expanduser().resolve()
    try:
        rel = tgt.relative_to(ws)
    except ValueError as exc:
        raise ValueError(f"{tgt} is not under workspace {ws}") from exc
    return rel.as_posix()


def from_workspace_relative(workspace: Path | UPath, rel: str) -> Path:
    """Return the absolute path of a workspace-relative POSIX string."""
    ws = Path(workspace).expanduser().resolve()
    return ws / rel


def is_under_workspace(workspace: Path | UPath, target: Path | UPath) -> bool:
    """Return True when ``target`` resolves under ``workspace``."""
    ws = Path(workspace).expanduser().resolve()
    tgt = Path(target).expanduser().resolve()
    try:
        tgt.relative_to(ws)
    except ValueError:
        return False
    return True


def encode_workspace_path(workspace: Path | UPath, target: Path | UPath) -> str:
    """Encode ``target`` as a portable string anchored at the workspace.

    Returns a workspace-relative POSIX path when ``target`` lives under
    ``workspace``. Otherwise tries ``cache://`` (under ``cache_dir()``) then
    ``state://`` (under ``state_dir()``). Raises ``ValueError`` when the
    target lies outside every supported anchor.
    """
    ws = Path(workspace).expanduser().resolve()
    tgt = Path(target).expanduser().resolve()
    try:
        return tgt.relative_to(ws).as_posix()
    except ValueError:
        pass
    cache_root = cache_dir().expanduser().resolve()
    try:
        return "cache://" + tgt.relative_to(cache_root).as_posix()
    except ValueError:
        pass
    state_root = state_dir().expanduser().resolve()
    try:
        return "state://" + tgt.relative_to(state_root).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"Cannot encode {tgt} as a workspace-relative path. "
            f"Expected target under workspace={ws}, cache={cache_root} "
            f"or state={state_root}."
        ) from exc


def decode_workspace_path(workspace: Path | UPath, encoded: str) -> Path:
    """Decode an encoded portable path back to an absolute :class:`Path`."""
    ws = Path(workspace).expanduser().resolve()
    text = str(encoded)
    if text.startswith("cache://"):
        return cache_dir().expanduser().resolve() / text[len("cache://") :]
    if text.startswith("state://"):
        return state_dir().expanduser().resolve() / text[len("state://") :]
    candidate = Path(text)
    if candidate.is_absolute():
        return candidate.resolve()
    return ws / candidate


# Portable workspace URI ----------------------------------------------------


def to_workspace_uri(path: Path | UPath) -> str:
    """Return the ``file://`` URI for a local workspace path."""
    resolved = Path(path).expanduser().resolve()
    return resolved.as_uri()


def resolve_workspace(uri: str | Path | UPath) -> Path:
    """Resolve a portable root URI to a local :class:`Path`.

    The URI may point at a workspace root or a project root: this helper only
    turns a portable string into a filesystem path and says nothing about the
    granularity of what it points at. Use :func:`project_roots_under` for that.

    The argument is widened to ``str | Path | UPath`` so callers can
    pass either a raw URI, a :class:`pathlib.Path`, or a
    :class:`upath.UPath` instance. Non-local URIs are accepted at the
    type level but rejected at runtime: this release only resolves
    workspaces on the local filesystem.

    Supported schemes:
    - bare path (no scheme): treated as a local path.
    - ``file://``: parsed and returned as a :class:`Path`.
    - any other scheme: raises :class:`NotImplementedError` with the
      offending URI.
    """
    text = str(uri)
    candidate = Path(text).expanduser()
    if os.name == "nt" and candidate.drive:
        return candidate
    parsed = urlparse(text)
    scheme = parsed.scheme.lower()
    if not scheme:
        return candidate
    if scheme in _LOCAL_SCHEMES:
        path_text = parsed.path
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            path_text = f"//{parsed.netloc}{path_text}"
        return Path(url2pathname(path_text)).expanduser()
    raise NotImplementedError(
        f"root URI {text!r} uses scheme {scheme!r} which is not supported "
        "in this release. Use a local path or a file:// URI."
    )


__all__: Iterable[str] = (
    "CATALOG_FILENAME",
    "CONFIGS_DIRNAME",
    "INDEX_FILENAME",
    "INTERNAL_DIRNAME",
    "PROJECTS_DIRNAME",
    "PREPROCESSING_DIRNAME",
    "PROJECT_MARKER_FILENAME",
    "REPORTS_DIRNAME",
    "RUNS_DIRNAME",
    "RUN_SCRATCH_ENV",
    "SESSIONS_DIRNAME",
    "SHARE_DIRNAME",
    "WORKSPACE_TOML_FILENAME",
    "active_run_scratch",
    "cache_dir",
    "catalog_path_for",
    "decode_workspace_path",
    "display_path",
    "encode_workspace_path",
    "from_workspace_relative",
    "internal_dir",
    "kept_preprocessing_dir",
    "is_project_root",
    "is_under_workspace",
    "is_workspace_root",
    "preprocessing_dir",
    "project_roots_under",
    "reports_dir_for",
    "resolve_project_root",
    "resolve_workspace",
    "running_sidecar_dir",
    "running_sidecar_path",
    "run_scratch",
    "runs_dir_for",
    "scratch_dir_for",
    "scratch_root_for",
    "share_dir_for",
    "state_dir",
    "sweep_dead_run_scratch",
    "to_workspace_relative",
    "to_workspace_uri",
)
