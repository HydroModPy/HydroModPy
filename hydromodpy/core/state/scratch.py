"""The scratch folder of a live run: where it works, and the sweep of the dead ones.

Each run of a project works in its own folder under ``<project>/.hmp/scratch/``,
or under ``$HMP_SCRATCH_ROOT`` on a machine scratch. A run that was killed leaves
its folder, and the next run removes the folders named after a dead process.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path, PurePosixPath

from hydromodpy.core.state.layout import INTERNAL_DIRNAME, internal_dir

SCRATCH_ROOT_ENV = "HMP_SCRATCH_ROOT"
"""Machine scratch root that replaces the scratch inside the project (``$SLURM_TMPDIR``).

Under it the solver of a run works in ``<project>/<case>.a<attempt>/`` (in
place of ``runs/<case>/.hmp/scratch/``) and its preprocessing in
``<project>/<case>.p<pid>/`` (in place of ``<project>/.hmp/scratch/``). It is
read from the environment only: it is never an author key and never enters
the config hash.
"""

RUN_SCRATCH: ContextVar[str | None] = ContextVar("hmp_run_scratch", default=None)
"""Name of the scratch folder of the run the current context is inside.

A context variable and not an environment variable, so two runs in two threads
of one process each keep their own folder and a run writes nothing into the
environment. A thread takes it from the thread that starts it through
``contextvars.copy_context()``, and a worker process takes it in its payload
(:func:`inherit_run_scratch`). A child ``hmp run`` claims a scratch of its own.
"""

#: Folder of the geographic, data and mesh preprocessing, inside a run's scratch.
PREPROCESSING_DIRNAME = "_preprocessing"

_RUN_SCRATCH_SUFFIX = re.compile(r"\.p(\d+)$")
_RUN_SCRATCH_KEY = re.compile(r"[A-Za-z0-9_-]+\.p\d+")
#: Beside a run folder a resume took over, names the process now working in it.
_RUN_SCRATCH_HOLDER_SUFFIX = ".holder"
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5
_STILL_ACTIVE = 259


def scratch_root_for(project_root: Path) -> Path:
    """Return the folder that holds the scratch folder of every run of a project.

    ``<root>/.hmp/scratch`` by default. Under :data:`SCRATCH_ROOT_ENV` it is
    ``$HMP_SCRATCH_ROOT/<project>``, beside the solver folders of the attempts,
    so the preprocessing of a run lands on the machine scratch too.
    """
    machine = os.environ.get(SCRATCH_ROOT_ENV, "").strip()
    if machine:
        return Path(machine).expanduser() / Path(project_root).resolve().name
    return internal_dir(project_root) / "scratch"


def active_run_scratch() -> str | None:
    """Return the scratch folder name of the run this context is inside, or None."""
    return RUN_SCRATCH.get()


def scratch_dir_for(project_root: Path) -> Path:
    """Return the solver working directory of the current run.

    Inside a run (:func:`run_scratch`) it is ``<root>/.hmp/scratch/<run>``, one
    folder per run, so two runs of one project work side by side: neither reads
    the preprocessing, the shared recharge or the solver files of the other, and
    a run that ends sweeps only its own. Outside any run it is the bare
    ``<root>/.hmp/scratch``.
    """
    key = active_run_scratch()
    root = scratch_root_for(project_root)
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


if sys.platform == "win32":

    def process_is_alive(pid: int) -> bool:
        """Return whether a process of this host still runs.

        Windows is probed by handle, since ``os.kill(pid, 0)`` sends a Ctrl+C event.
        """
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # Denied means the process exists under another account.
            return bool(ctypes.get_last_error() == _ERROR_ACCESS_DENIED)
        try:
            # A handle someone still holds keeps an ended process openable:
            # only the exit code tells whether it still runs.
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

else:

    def process_is_alive(pid: int) -> bool:
        """Return whether a process of this host still runs."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


def _holder_path(root: Path, key: str) -> Path:
    return root / f"{key}{_RUN_SCRATCH_HOLDER_SUFFIX}"


def run_scratch_stem(name: str) -> str | None:
    """Return the run name of a run scratch folder ``<name>.p<pid>``, or ``None``."""
    match = _RUN_SCRATCH_SUFFIX.search(name)
    return None if match is None else name[: match.start()]


def run_scratch_pids(root: Path, key: str) -> set[int]:
    """Return the process named by a run folder and the one that took it over, if any."""
    pids: set[int] = set()
    match = _RUN_SCRATCH_SUFFIX.search(key)
    if match is not None:
        pids.add(int(match.group(1)))
    try:
        text = _holder_path(root, key).read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return pids
    if text.isdigit():
        pids.add(int(text))
    return pids


def _held_by_another_process(root: Path, key: str) -> bool:
    return any(pid != os.getpid() and process_is_alive(pid) for pid in run_scratch_pids(root, key))


def sweep_dead_run_scratch(project_root: Path) -> list[Path]:
    """Remove the scratch folders of runs whose process no longer runs.

    A run sweeps its own folder when it ends. One that was killed cannot, so the
    next run of the project removes the folders named after a dead process,
    unless a live resume took the folder over (:func:`run_scratch`). Return the
    folders that are gone.
    """
    import shutil

    root = scratch_root_for(project_root)
    if not root.is_dir():
        return []
    removed: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or _RUN_SCRATCH_SUFFIX.search(child.name) is None:
            continue
        if any(process_is_alive(pid) for pid in run_scratch_pids(root, child.name)):
            continue
        shutil.rmtree(child, ignore_errors=True)
        if not child.exists():
            _holder_path(root, child.name).unlink(missing_ok=True)
            removed.append(child)
    for holder in root.glob(f"*{_RUN_SCRATCH_HOLDER_SUFFIX}"):
        key = holder.name[: -len(_RUN_SCRATCH_HOLDER_SUFFIX)]
        if not (root / key).exists() and not _held_by_another_process(root, key):
            holder.unlink(missing_ok=True)
    return removed


def run_scratch_of(paths: Iterable[str]) -> str | None:
    """Return the run folder that project-relative POSIX paths live in, or None.

    The artifacts a run journals under its scratch name the folder it worked in,
    which is how a resume finds the folder of the run it continues.
    """
    for path in paths:
        parts = PurePosixPath(path).parts
        if (
            len(parts) > 2
            and parts[:2] == (INTERNAL_DIRNAME, "scratch")
            and _RUN_SCRATCH_KEY.fullmatch(parts[2])
        ):
            return parts[2]
    return None


def _can_take_over(project_root: Path, key: str | None) -> bool:
    if key is None or _RUN_SCRATCH_KEY.fullmatch(key) is None:
        return False
    root = scratch_root_for(project_root)
    return (root / key).is_dir() and not _held_by_another_process(root, key)


@contextmanager
def inherit_run_scratch(key: str) -> Iterator[str]:
    """Work in the scratch folder *key* that another context or process opened.

    A worker process that a run starts reads the key in its payload and enters
    here, so ``scratch_dir_for`` answers in it as it does in the parent. The
    folder is neither created nor swept: its owner does both.
    """
    token = RUN_SCRATCH.set(key)
    try:
        yield key
    finally:
        RUN_SCRATCH.reset(token)


@contextmanager
def run_scratch(project_root: Path, label: str, *, resumes: str | None = None) -> Iterator[str]:
    """Give the run this context starts its own folder under ``.hmp/scratch/``.

    The outermost call names the folder after ``label`` and this process and
    sets it in :data:`RUN_SCRATCH`. Nested calls (the trials, phases and
    promotions of a calibration session) read it and work in the same folder.
    On entry the outermost call also removes the folders of runs that were
    killed. On exit it removes the run's folder when nothing is left in it.

    A resume passes the folder of the run it continues as ``resumes``
    (:func:`run_scratch_of`). The outermost call then works in that folder and
    records this process as its holder, so the sweep of this run and of any
    other keeps what the killed run left for the resume to reuse. A folder
    that is gone, or that a live process still works in, is not taken over.
    """
    inherited = active_run_scratch()
    owner = inherited is None
    takes_over = owner and _can_take_over(project_root, resumes)
    if inherited is not None:
        key = inherited
    elif takes_over and resumes is not None:
        key = resumes
    else:
        key = _run_scratch_name(label)
    token = RUN_SCRATCH.set(key) if owner else None
    root = scratch_root_for(project_root)
    try:
        if takes_over:
            _holder_path(root, key).write_text(str(os.getpid()), encoding="ascii")
        if owner:
            sweep_dead_run_scratch(project_root)
        yield key
    finally:
        if token is not None:
            RUN_SCRATCH.reset(token)
        if takes_over:
            _holder_path(root, key).unlink(missing_ok=True)
        if owner:
            for folder in (root / key, root):
                try:
                    folder.rmdir()
                except OSError:
                    break


__all__ = (
    "PREPROCESSING_DIRNAME",
    "RUN_SCRATCH",
    "SCRATCH_ROOT_ENV",
    "active_run_scratch",
    "inherit_run_scratch",
    "kept_preprocessing_dir",
    "preprocessing_dir",
    "process_is_alive",
    "run_scratch",
    "run_scratch_of",
    "run_scratch_pids",
    "run_scratch_stem",
    "scratch_dir_for",
    "scratch_root_for",
    "sweep_dead_run_scratch",
)
