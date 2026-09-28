"""Canonical workspace path registry shared by runtime components."""

from __future__ import annotations

import functools
import os
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, cast

from filelock import FileLock, Timeout

from hydromodpy.core.io.filesystem import native_io_path
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import (
    INTERNAL_DIRNAME,
    REPORTS_DIRNAME,
    scratch_dir_for,
    share_dir_for,
)
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

# flock exists on POSIX only; on Windows the shared use of the preprocessing
# tree is not tracked and the project run lock alone keeps runs apart.
if sys.platform == "win32":
    fcntl = None
else:
    import fcntl

logger = get_logger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])

#: Preprocessing intermediates go under .hmp/scratch/_preprocessing/.
#: These files are needed on disk by whitebox/rasterio during the pipeline,
#: then ingested into the project store and cleaned up.
PREPROCESSING_DIRNAME = "_preprocessing"
PREPROCESSING_DIR = f"{INTERNAL_DIRNAME}/scratch/{PREPROCESSING_DIRNAME}"

#: Inter-process lock guarding the whole preprocessing tree, one per project.
PREPROCESSING_LOCK_FILENAME = "preprocessing.lock"
PREPROCESSING_LOCK_TIMEOUT_SECONDS = 900.0


def preprocessing_lock(project_root: Path) -> FileLock:
    """Return the (unacquired) inter-process lock for ``PREPROCESSING_DIR``.

    ``.hmp/scratch/_preprocessing/`` is per *project*, not per run: two
    ``hmp run`` invocations on the same project both write and read it while
    they build the geographic and mesh preprocessing, so racing through it
    interleaves one run's writes with the other's reads (a Whitebox panic, a
    missing ``dem_fill.tif``, a missing ``outlet.shp``). Holding this lock for
    the whole of that phase serializes it across concurrent runs of the same
    project, without changing where anything lives on disk.

    The lock file itself sits in ``.hmp/locks/``, beside the project's other
    inter-process locks (the Zarr write locks, ``index.duckdb.lock``).
    """
    lock_dir = Path(project_root) / INTERNAL_DIRNAME / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / PREPROCESSING_LOCK_FILENAME
    return FileLock(native_io_path(lock_path), timeout=PREPROCESSING_LOCK_TIMEOUT_SECONDS)


#: File whose shared locks mark the processes still reading the preprocessing tree.
PREPROCESSING_USERS_FILENAME = "preprocessing.users"

_HELD_USES: dict[str, int] = {}
"""The descriptor holding this process's shared lock, per project root."""


def _users_path(project_root: Path) -> Path:
    lock_dir = Path(project_root) / INTERNAL_DIRNAME / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / PREPROCESSING_USERS_FILENAME


def hold_preprocessing_use(project_root: Path) -> None:
    """Mark this process as a reader of the project's preprocessing tree.

    A run reads ``.hmp/scratch/_preprocessing/`` well after it built it: the
    data load, the network criterion and the store ingestion all go back to
    it. The run that ends first must not drop the tree under another one, so
    each run holds a shared lock from its geographic build until its own
    cleanup (:func:`release_preprocessing_use`), and a cleanup drops the tree
    only when it can take the lock exclusively (:func:`preprocessing_unused`).
    The last run out drops it.

    Idempotent within a process. A no-op where ``fcntl`` is missing (Windows):
    the tree is then dropped by whichever run ends, as before.
    """
    if fcntl is None:
        return
    key = str(Path(project_root).resolve())
    if key in _HELD_USES:
        return
    fd = os.open(native_io_path(_users_path(project_root)), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
    except OSError:
        os.close(fd)
        raise
    _HELD_USES[key] = fd


def release_preprocessing_use(project_root: Path) -> None:
    """Drop the shared lock :func:`hold_preprocessing_use` took, if any."""
    fd = _HELD_USES.pop(str(Path(project_root).resolve()), None)
    if fd is not None:
        os.close(fd)


@contextmanager
def preprocessing_unused(project_root: Path) -> Iterator[bool]:
    """Yield whether no other process still reads the preprocessing tree.

    Holds the build lock throughout, so no run starts building meanwhile, and,
    when it yields ``True``, the exclusive lock of the users file too, so no
    run starts reading. A caller drops the tree only on ``True``. Release this
    process's own use first, or it counts as another reader.
    """
    with preprocessing_lock(project_root):
        if fcntl is None:
            yield True
            return
        fd = os.open(native_io_path(_users_path(project_root)), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


#: Inter-process lock a run of the project holds from its start to its end.
PROJECT_RUN_LOCK_FILENAME = "project-run.lock"

_RUN_LOCKS: dict[str, list[Any]] = {}
"""The held run lock and its depth, per project root, for this process."""

_RUN_LOCKS_GUARD = threading.Lock()


@contextmanager
def project_run_lock(project_root: Path) -> Iterator[None]:
    """Hold the project's run lock for the duration of the block.

    The runs of one project share ``.hmp/scratch/``: the preprocessing tree,
    the recharge the trials of a calibration share and the solver folders a
    finished run sweeps. Two runs of one project at once corrupt each other
    there: one run's trials read the network or the recharge another run
    wrote, and a run that ends removes the solver folders another still
    reads. So a run, or a whole calibration session, holds this lock, and the
    runs of one project take turns. Runs of different projects stay parallel.

    Reentrant within a process, from any thread: a calibration session holds
    it and every trial, promotion and phase it runs goes through. A run that
    has to wait says so once and waits for the other one to end.
    """
    key = str(Path(project_root).resolve())
    with _RUN_LOCKS_GUARD:
        held = _RUN_LOCKS.get(key)
        if held is not None:
            held[1] += 1
    if held is None:
        lock_dir = Path(project_root) / INTERNAL_DIRNAME / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock = FileLock(native_io_path(lock_dir / PROJECT_RUN_LOCK_FILENAME), timeout=-1)
        try:
            lock.acquire(timeout=0)
        except Timeout:
            logger.warning(
                "Another run of this project is in progress; this one waits for it to end, "
                "because the runs of one project share %s/scratch.",
                INTERNAL_DIRNAME,
            )
            lock.acquire()
        with _RUN_LOCKS_GUARD:
            _RUN_LOCKS[key] = [lock, 1]
    try:
        yield
    finally:
        with _RUN_LOCKS_GUARD:
            entry = _RUN_LOCKS[key]
            entry[1] -= 1
            last = entry[1] == 0
            if last:
                del _RUN_LOCKS[key]
        if last:
            entry[0].release()


def holds_project_run_lock(
    root_of: Callable[..., Path],
    *,
    check: Callable[..., None] | None = None,
) -> Callable[[_F], _F]:
    """Run the decorated function under :func:`project_run_lock`.

    ``root_of`` receives the call's arguments and returns the project root.
    ``check``, when given, receives them first and raises to refuse the call
    before the lock is taken, so a refused call leaves nothing on disk.
    """

    def decorate(fn: _F) -> _F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if check is not None:
                check(*args, **kwargs)
            with project_run_lock(root_of(*args, **kwargs)):
                return fn(*args, **kwargs)

        return cast(_F, wrapper)

    return decorate


def project_root_of_config(config_path: Path, workspace: Path | str | None = None) -> Path:
    """Return the project root a TOML config runs in.

    ``workspace`` wins when given, then ``HMP_PROJECT_ROOT``, then the
    ``[workspace] project_root`` of the config and its ``base_config`` chain,
    relative to the config's folder, then that folder.
    """
    if workspace is not None:
        return Path(workspace).expanduser().resolve()
    env_root = os.environ.get("HMP_PROJECT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    config_path = Path(config_path).expanduser().resolve()
    try:
        raw = load_toml_with_base_config(config_path)
    except (OSError, ValueError, TypeError):
        raw = {}
    declared = (raw.get("workspace") or {}).get("project_root")
    if declared:
        candidate = Path(str(declared)).expanduser()
        if not candidate.is_absolute():
            candidate = config_path.parent / candidate
        return candidate.resolve()
    return config_path.parent


def project_root_of_internal_path(path: Path) -> Path | None:
    """Return the project root above a path under its ``.hmp/`` folder, or None."""
    resolved = Path(path).resolve()
    for parent in resolved.parents:
        if parent.name == INTERNAL_DIRNAME:
            return parent.parent
    return None


if TYPE_CHECKING:
    from hydromodpy.core.workspace.config import WorkspaceConfig


@dataclass(frozen=True)
class WorkspacePathRegistry:
    """Centralize shared data and project-local result paths."""

    project_root: Path
    root: Path
    catalog_path: Path
    data_dir: Path
    runs_dir: Path
    output_root: Path | None = None

    @classmethod
    def from_config(cls, config: WorkspaceConfig) -> WorkspacePathRegistry:
        """Build a registry from a fully resolved workspace config."""
        return cls(
            project_root=Path(config.project_root),
            root=Path(config.root),
            catalog_path=Path(config.catalog_path),
            data_dir=Path(config.data_dir),
            runs_dir=Path(config.runs_dir),
            output_root=Path(config.output_root) if config.output_root else None,
        )

    # -- Derived convenience names -----------------------------------------

    @property
    def _effective_output_root(self) -> Path:
        """Root for result directories: output_root if set, else project_root."""
        if self.output_root is not None:
            return self.output_root
        return self.project_root

    @property
    def catch_name(self) -> str:
        return self.project_root.name

    @property
    def solver_scratch_folder(self) -> Path:
        return scratch_dir_for(self._effective_output_root)

    def solver_scratch_run_folder(self, sim_id: str) -> Path:
        """Return the scratch folder for a specific solver run."""
        return self.solver_scratch_folder / sim_id

    @property
    def share_folder(self) -> Path:
        return share_dir_for(self._effective_output_root)

    @property
    def reports_folder(self) -> Path:
        return self.share_folder / REPORTS_DIRNAME

    @property
    def figures_folder(self) -> Path:
        """Figures that belong to the project, not to one run."""
        return self.share_folder / "figures"

    @property
    def data_path(self) -> Path:
        return self.data_dir

    def figures_subdir(self, *parts: str) -> Path:
        return self.figures_folder.joinpath(*parts)

    def manager_figure_folder(self, manager_type: str) -> Path:
        """Return canonical figure folder for one data-manager type."""
        token = str(manager_type).strip().lower()
        if not token:
            raise ValueError("manager_type cannot be empty")
        return self.figures_subdir(token)
