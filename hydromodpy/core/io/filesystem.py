"""Filesystem utilities: folders, sizes, and the paths Windows bounds.

This module is the one place that knows the Windows path limit, the long path
prefix, the hard link with its copy fallback, the rename onto a reserved
folder, and the removal that waits for a reader to let go.

The budget of a project tree. :data:`PROJECT_TREE_DEPTH` is the longest path a
project writes below its root folder, measured on the six reference runs with
names of 40 characters (``MAX_NAME_LENGTH`` of ``core/state/names.py``), the
window suffix ``_w01`` and a version suffix ``.v9999``.

- A kept calibration trial reaches 158 characters, the deepest path.
- A run reaches 146 characters.
- A product being written reaches 140 characters with a host name of
  15 characters. Each extra character of the host name adds one, so the
  product path reaches 160 with a host name of 35 characters.
- The preprocessing of a project reaches 125 characters.
- The working copy of the project index reaches 38 characters.

The window suffix is as wide as the count of windows (``project/windows.py``),
so ``_w01`` holds up to 99 windows. A kept trial reaches 159 characters with
100 windows and 160 with 1000, hence a budget of 160.

``native_io_path`` is the one place that adds the long path prefix, and
``check_project_root`` refuses a project folder over 99 characters on Windows with a
``ConfigError``. ``link_or_copy`` hard-links a file and copies it when the system
refuses the link, and it never overwrites the target. ``unlink_when_free`` and
``replace_when_free`` try again six times on a ``PermissionError``, because Windows
refuses to remove or move a file a reader holds open. They try again on Windows only,
and elsewhere the error is permanent and raised at once. ``LockFile`` uses
``replace_when_free`` to move a lock aside before it removes it.
"""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Final

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    import pandas as pd

logger = get_logger(__name__)

WINDOWS_PATH_LIMIT: Final = 259
"""Longest path MODFLOW 6 and DuckDB open on Windows: MAX_PATH, 260 with the NUL."""

PROJECT_TREE_DEPTH: Final = 160
"""Longest path a project writes below its root folder (see the module docstring)."""

_FIRST_RETRY_S: Final = 0.01
"""First wait of a removal or a rename refused by Windows; it doubles at each try."""


def create_folder(path) -> None:
    """Create directory tree if it does not already exist."""
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def load_csv(file_path: str) -> pd.DataFrame:
    """Load a CSV file into a DataFrame."""
    # Lazy: native_io_path puts this module on the migration boot path, and a
    # top-level pandas import would cost every command half a second there.
    import pandas as pandas_module

    try:
        return pandas_module.read_csv(file_path)
    except Exception:
        logger.exception("Failed to load CSV file %s", file_path)
        return pandas_module.DataFrame()


def native_io_path(path: Path | str) -> str:
    """Return a filesystem path string suitable for lower-level IO libraries."""
    value = str(Path(path).resolve())
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def check_project_root(root: Path | str, *, windows: bool | None = None) -> None:
    """Refuse a project folder too long for the paths a project writes on Windows.

    ``windows`` defaults to ``os.name == "nt"``, read at the call. Off Windows
    nothing is refused, because Linux and macOS have no such limit.
    """
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return
    absolute = os.path.abspath(root)
    length = len(absolute)
    if length + PROJECT_TREE_DEPTH <= WINDOWS_PATH_LIMIT:
        return
    raise ConfigError(
        f"The project folder {absolute} is {length} characters long. On Windows a project "
        f"writes paths up to {PROJECT_TREE_DEPTH} characters below its folder, and MODFLOW 6 "
        f"and DuckDB open no path longer than {WINDOWS_PATH_LIMIT}, so the folder may hold "
        f"{WINDOWS_PATH_LIMIT - PROJECT_TREE_DEPTH} characters at most. Move the project to a "
        "shorter folder, for example D:\\hmp\\<organisation>\\projects\\<name>."
    )


def link_or_copy(source: Path, target: Path) -> bool:
    """Hard link ``source`` at ``target``, or copy it when the link is refused.

    Return True for a link and False for a copy. Neither branch overwrites: a
    ``target`` already present raises ``FileExistsError``. The link is refused
    across volumes, on FAT, on some network shares, and by Windows with a
    ``PermissionError``; the copy then creates ``target`` with ``O_EXCL`` and
    keeps the mode and the dates of ``source``, as ``shutil.copy2`` does.
    """
    try:
        os.link(source, target)
    except FileExistsError:
        raise
    except OSError:
        pass  # No hard link here (other volume, FAT, share, Windows): copy below.
    else:
        return True
    with open(source, "rb") as reader:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
        fd = os.open(target, flags, 0o666)
        try:
            with os.fdopen(fd, "wb") as writer:
                shutil.copyfileobj(reader, writer)
            shutil.copystat(source, target)
        except BaseException:
            # The half copy is ours, created with O_EXCL: it holds nothing of another.
            Path(target).unlink(missing_ok=True)
            raise
    return False


def rename_onto_empty_dir(source: Path, reserved: Path, *, attempts: int = 6) -> None:
    """Move the folder ``source`` onto ``reserved``, an empty folder a ``mkdir`` took.

    POSIX renames a folder onto an empty one in one step, and any error is
    raised as is. Windows refuses it always, so there an empty ``reserved`` is
    removed and the rename is done again by ``os.rename``, which never
    replaces on Windows. A ``PermissionError`` of that second step (a reader
    or an antivirus holds the folder) is retried as :func:`unlink_when_free`
    does. When another process took the name in between, ``FileExistsError``
    is raised and ``reserved`` is that process's.
    """
    if os.name != "nt":
        os.replace(source, reserved)
        return
    try:
        os.replace(source, reserved)
        return
    except OSError:
        if not os.path.lexists(source) or not _is_empty_dir(reserved):
            raise
    try:
        os.rmdir(reserved)
    except FileNotFoundError:
        pass

    def second_step() -> None:
        if os.path.lexists(reserved):
            raise FileExistsError(f"{reserved} was taken by another process")
        os.rename(source, reserved)

    try:
        _retried_while_in_use(second_step, attempts)
    except FileExistsError:
        raise
    except OSError as error:
        if os.path.lexists(reserved) and os.path.lexists(source):
            raise FileExistsError(f"{reserved} was taken by another process") from error
        raise


def unlink_when_free(path: Path | str, *, attempts: int = 6) -> None:
    """Remove a file, absent included, retrying on Windows while it is in use.

    Windows refuses to remove a file a reader holds open without
    ``FILE_SHARE_DELETE``, which ``open()`` of Python does. There a
    ``PermissionError`` is retried up to ``attempts`` times, the wait doubling
    from 10 ms (310 ms in all for six tries), and the error of the last try is
    raised. Elsewhere such an error is permanent and raised at once.
    """

    def unlink() -> None:
        try:
            os.unlink(path)
        except FileNotFoundError:
            return

    if os.name != "nt":
        unlink()
        return
    _retried_while_in_use(unlink, attempts)


def replace_when_free(source: Path | str, target: Path | str, *, attempts: int = 6) -> None:
    """``os.replace`` a file, retrying on Windows while it is in use.

    Same schedule as :func:`unlink_when_free`, on Windows only. A
    ``FileNotFoundError`` is raised at once, and the error of the last try is
    raised.
    """
    if os.name != "nt":
        os.replace(source, target)
        return
    _retried_while_in_use(lambda: os.replace(source, target), attempts)


def _retried_while_in_use(action: Callable[[], None], attempts: int) -> None:
    """Call ``action``, retrying a ``PermissionError``; the wait doubles from 10 ms."""
    delay = _FIRST_RETRY_S
    for attempt in range(attempts):
        try:
            action()
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2


def path_size(path: Path) -> int:
    """Return the bytes of a file, or of every file under a directory; 0 when it is gone."""
    if path.is_file():
        return int(path.stat().st_size)
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += int(child.stat().st_size)
        except OSError:
            # A file removed while the tree is walked frees nothing more.
            continue
    return total


def _is_empty_dir(path: Path | str) -> bool:
    """Whether ``path`` is a folder with nothing in it."""
    try:
        with os.scandir(path) as entries:
            return next(entries, None) is None
    except OSError:
        return False


__all__ = [
    "PROJECT_TREE_DEPTH",
    "WINDOWS_PATH_LIMIT",
    "check_project_root",
    "create_folder",
    "link_or_copy",
    "load_csv",
    "native_io_path",
    "path_size",
    "rename_onto_empty_dir",
    "replace_when_free",
    "unlink_when_free",
]
