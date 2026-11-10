"""``hydromodpy.lock``: write it from the sidecars, read it, verify it, freeze a run on it.

A lockfile pins every file a project reads before anything runs. It records:

- ``schema``: the id of the format, ``hydromodpy.lock.v2``.
- ``[hydromodpy]``: the package version, the git commit of HydroModPy and of
  the project, the Python version, the sha256 of the config schema and the
  instant of the snapshot.
- ``[[input]]``: one record per row of the data cache and per user file the
  project declares, with ``variable``, ``source``, ``station_id``,
  ``product``, ``path``, ``sha256``, ``bytes``, ``license`` and ``fetched_at``,
  the instant of the snapshot.

The ``path`` of a row of the cache is relative to the data folder
(``hydrometry/hydrometry_hubeau_X.csv``). The ``path`` of a user file
(``source = "file"``) is relative to the project root, in POSIX form, and may
climb out of it with ``..``. Both are read the same way on any machine.

The file has one address, ``<project root>/hydromodpy.lock``, built by
:func:`project_lockfile_path` and by nothing else. A command that is not handed
a project root asks :func:`resolve_lockfile_root` for one; a workspace root is
never an answer, because a workspace holds many projects and one shared cache.

Frozen mode is an argument. The runner reads the lockfile once with
:func:`read_locked_inputs` and hands the :class:`LockedInputs` down to the data
cache and the file source, so two runs of one process never share it. A
``reject_*`` function takes that object first, and ``None`` means the run is not
frozen. A frozen run refuses a cache miss, a row the lockfile does not pin, a
file of other bytes and any new write, and a user file the lockfile does not pin
by its bytes. Each refusal is a :class:`FrozenDataError`.

Every reader refuses a lockfile whose ``schema`` lies outside
:data:`LOCKFILE_VERSIONS`, by the rule of
:mod:`hydromodpy.core.io.document_version`, naming the version read and the
command that writes it again. A lockfile of HydroModPy 2.0.0
(``hydromodpy.lock.v1``) is refused that way.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import tomlkit

from hydromodpy.core.exceptions import ConfigError, FrozenDataError
from hydromodpy.core.io.document_version import VersionWindow, check_version
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.core.version import __version__ as _HMP_VERSION

LOCKFILE_NAME = "hydromodpy.lock"
LOCKFILE_SCHEMA = "hydromodpy.lock.v2"
LOCKFILE_VERSIONS = VersionWindow(oldest=LOCKFILE_SCHEMA, current=LOCKFILE_SCHEMA)
LOCKFILE_REMEDY = "Write it again with `hmp data lock`."

#: The ``source`` of a file the user declared, read where it lies.
USER_FILE_SOURCE = "file"

# The directory that holds the hydromodpy package, found from this module's
# dotted name so it stays right wherever the module sits. Its git commit is
# the HydroModPy commit a lockfile records.
_CHECKOUT_ROOT = Path(__file__).resolve().parents[__name__.count(".")]


def project_lockfile_path(project_root: Path | str) -> Path:
    """Return ``<project_root>/hydromodpy.lock``, the one address of the lockfile."""
    return Path(project_root).expanduser() / LOCKFILE_NAME


def resolve_lockfile_root(project: Path | str | None = None) -> Path:
    """Return the project root whose lockfile a command addresses.

    An explicit ``project`` is the root. Otherwise the walk up from the current
    directory is the one :func:`hydromodpy.core.state.result_dirs.resolve_project_root`
    owns, and only the miss differs: that helper answers with the starting
    directory so a flat project still resolves, while a lockfile command
    outside any project must not write ``hydromodpy.lock`` into whatever
    directory the shell happened to sit in.

    Every miss raises ``FileNotFoundError``, including the unanchored
    ``configs/`` directory that helper reports as a ``ConfigError``: one
    missing root, one exception type to catch.
    """
    from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME
    from hydromodpy.core.state.result_dirs import resolve_project_root

    if project is not None:
        return Path(project).expanduser().resolve()
    start = Path.cwd().resolve()
    try:
        root = resolve_project_root(start)
    except ConfigError as exc:
        raise FileNotFoundError(str(exc)) from exc
    if not (root / PROJECT_MARKER_FILENAME).is_file():
        raise FileNotFoundError(
            f"No {PROJECT_MARKER_FILENAME} at or above {start}: {LOCKFILE_NAME} lives at a "
            "project root, so run from inside a project or name one explicitly."
        )
    return root


@dataclass(frozen=True)
class LockedInput:
    """One ``[[input]]`` record: one row of the data cache, or one user file.

    An ``empty`` record pins a station that answered nothing. Its ``path`` is
    the name its sidecar describes, the sidecar is that path plus ``.json``,
    and it has no ``sha256`` and no ``bytes``.
    """

    variable: str
    source: str
    station_id: str | None
    product: str | None
    path: str
    sha256: str | None
    bytes: int | None
    license: str | None
    fetched_at: str
    empty: bool = False


@dataclass(frozen=True, slots=True)
class LockedInputs:
    """The lockfile of a frozen project, read once.

    ``project_root`` is the folder that holds the lockfile and the base of the
    ``path`` of every user file. The object is plain data, so it crosses a
    process by ``pickle`` and a forked trial shares it without a copy.
    """

    project_root: Path
    path: Path
    inputs: tuple[LockedInput, ...]

    def pinned(self, variable: str, source: str, station_id: str | None) -> list[LockedInput]:
        """Return the records held for one variable, source and station."""
        return [
            item
            for item in self.inputs
            if (item.variable, item.source, item.station_id) == (variable, source, station_id)
        ]

    def row(
        self, variable: str, source: str, station_id: str | None, path: str
    ) -> LockedInput | None:
        """Return the record of the file at *path* (relative to the data folder), or None."""
        wanted = PurePosixPath(path)
        for item in self.pinned(variable, source, station_id):
            if PurePosixPath(item.path) == wanted:
                return item
        return None


@dataclass(frozen=True)
class LockMismatch:
    """Discrepancy between the lockfile and the files on disk."""

    kind: str  # "missing", "sha256"
    variable: str
    source: str
    station_id: str | None
    expected: Any
    observed: Any
    path: str | None = None


# ---------------------------------------------------------------------- read


def _parse(path: Path | str) -> tomlkit.TOMLDocument:
    """Parse the lockfile at *path*; refuse it unless its ``schema`` lies in the window."""
    target = Path(path)
    doc = tomlkit.parse(target.read_text())
    raw = doc.get("schema")
    header = doc.get("hydromodpy")
    check_version(
        raw if isinstance(raw, str) else None,
        LOCKFILE_VERSIONS,
        document=target,
        key="schema",
        writer=header.get("hydromodpy_version") if isinstance(header, dict) else None,
        remedy=LOCKFILE_REMEDY,
    )
    return doc


def read_lockfile_inputs(path: Path | str) -> list[LockedInput]:
    """Load every ``[[input]]`` record of the lockfile.

    A record that is not ``empty`` must carry its ``sha256``.
    """
    doc = _parse(path)
    records: list[LockedInput] = []
    for item in doc.get("input", []):
        empty = bool(item.get("empty", False))
        records.append(
            LockedInput(
                variable=str(item["variable"]),
                source=str(item["source"]),
                station_id=(str(item["station_id"]) if "station_id" in item else None),
                product=(str(item["product"]) if "product" in item else None),
                path=str(item["path"]),
                sha256=None if empty else str(item["sha256"]),
                bytes=(int(item["bytes"]) if "bytes" in item and not empty else None),
                license=(str(item["license"]) if "license" in item else None),
                fetched_at=str(item.get("fetched_at", "")),
                empty=empty,
            )
        )
    return records


def read_lockfile_meta(path: Path | str) -> dict[str, Any]:
    """Return the ``[hydromodpy]`` header section as a plain dict."""
    doc = _parse(path)
    raw = doc.get("hydromodpy")
    if not isinstance(raw, dict):
        return {}
    return {str(k): (None if v is None else v) for k, v in raw.items()}


def read_lockfile_schema_sha256(path: Path | str) -> str | None:
    """Return the sha256 of the config schema recorded in the lockfile, when present."""
    value = read_lockfile_meta(path).get("config_schema_sha256")
    return str(value) if value is not None else None


# ---------------------------------------------------------------------- frozen mode


def read_locked_inputs(project_root: Path | str) -> LockedInputs:
    """Read the lockfile of *project_root* once, for a frozen run.

    Raises :class:`FrozenDataError` when the project has no lockfile, since a
    frozen run has nothing to compare its inputs to.
    """
    root = Path(project_root).expanduser().resolve()
    lockfile = project_lockfile_path(root)
    if not lockfile.is_file():
        raise FrozenDataError(f"Frozen data mode requires an existing lockfile at {lockfile}.")
    return LockedInputs(
        project_root=root, path=lockfile, inputs=tuple(read_lockfile_inputs(lockfile))
    )


def _key(variable: str, source: str, station_id: str | None) -> str:
    return f"{variable}/{source}/{station_id or '-'}"


def _reject_a_file_pinned_empty(
    locked: LockedInputs, variable: str, source: str, station_id: str | None
) -> None:
    if station_id is not None and any(
        item.empty for item in locked.pinned(variable, source, station_id)
    ):
        raise FrozenDataError(
            f"Frozen data mode found a file for {_key(variable, source, station_id)}, and "
            "hydromodpy.lock pins an empty answer for it."
        )


def reject_frozen_cache_miss(
    locked: LockedInputs | None,
    *,
    data_root: Path | None,
    variable: str,
    source: str,
    station_id: str | None,
) -> None:
    """Refuse a search the data cache cannot answer, in frozen mode."""
    if locked is None:
        return
    raise FrozenDataError(
        "Frozen data mode forbids cache misses: "
        f"{_key(variable, source, station_id)} is absent from the data cache at "
        f"{data_root or 'a store without a data folder'}."
    )


def reject_frozen_row(
    locked: LockedInputs | None,
    *,
    variable: str,
    source: str,
    station_id: str | None,
    path: str,
    sha256: str | None,
) -> None:
    """Refuse a row of the data cache the lockfile does not pin, or pins with other bytes."""
    if locked is None:
        return
    _reject_a_file_pinned_empty(locked, variable, source, station_id)
    pinned = locked.row(variable, source, station_id, path)
    if pinned is None:
        raise FrozenDataError(
            "Frozen data mode forbids data cache rows absent from hydromodpy.lock: "
            f"{_key(variable, source, station_id)}."
        )
    if sha256 != pinned.sha256:
        raise FrozenDataError(
            "Frozen data mode detected a SHA-256 mismatch for "
            f"{_key(variable, source, station_id)}."
        )


def reject_frozen_empty(
    locked: LockedInputs | None, *, variable: str, source: str, station_id: str | None
) -> None:
    """Refuse an empty answer the lockfile does not pin, or a station it pins a file for.

    The lockfile pins an empty row as a record with ``empty = true``, so a
    station that answered nothing replays frozen like any other row.
    """
    if locked is None:
        return
    pinned = locked.pinned(variable, source, station_id)
    for item in pinned:
        if not item.empty:
            raise FrozenDataError(
                f"Frozen data mode found an empty answer for {_key(variable, source, station_id)}, "
                f"and hydromodpy.lock pins the file {item.path} for it."
            )
    if not pinned:
        raise FrozenDataError(
            "Frozen data mode forbids data cache rows absent from hydromodpy.lock: "
            f"{_key(variable, source, station_id)} (an empty answer)."
        )


def reject_frozen_record(
    locked: LockedInputs | None,
    *,
    variable: str,
    source: str,
    station_id: str | None,
    path: str,
    sha256: str | None,
) -> None:
    """Refuse a new row of the data cache that the lockfile does not pin, in frozen mode."""
    if locked is None:
        return
    if sha256 is not None:
        _reject_a_file_pinned_empty(locked, variable, source, station_id)
    pinned = locked.row(variable, source, station_id, path)
    if pinned is None:
        raise FrozenDataError(
            "Frozen data mode forbids registering a downloaded artefact absent from "
            f"hydromodpy.lock: {_key(variable, source, station_id)}."
        )
    if sha256 != pinned.sha256:
        raise FrozenDataError(
            "Frozen data mode forbids registering an artefact whose SHA-256 does not match "
            f"hydromodpy.lock: {_key(variable, source, station_id)}."
        )


def reject_frozen_download(
    locked: LockedInputs | None,
    *,
    variable: str,
    source: str,
    station_id: str | None,
    detail: str,
) -> None:
    """Refuse a request that would reach the network, before it is made.

    A cached row that covers only part of the request passes the lookup.
    Without this guard the missing days were downloaded, merged into the row,
    and the file the lockfile pins was replaced before anything refused the
    new one.
    """
    if locked is None:
        return
    raise FrozenDataError(
        f"Frozen data mode forbids a download: {_key(variable, source, station_id)} {detail}."
    )


def reject_frozen_user_file(locked: LockedInputs | None, *, variable: str, path: Path) -> None:
    """Refuse a user file the lockfile does not pin, or pins with other bytes.

    The file is matched by its resolved path against the ``file`` records,
    whose paths are read under the project root of *locked*.
    """
    if locked is None:
        return
    resolved = Path(path).resolve()
    for item in locked.inputs:
        if (
            item.source == USER_FILE_SOURCE
            and item.variable == variable
            and (locked.project_root / item.path).resolve() == resolved
        ):
            if sha256_of(resolved) != item.sha256:
                raise FrozenDataError(
                    "Frozen data mode forbids a user file whose SHA-256 does not match "
                    f"hydromodpy.lock: {variable}/file/{resolved}."
                )
            return
    raise FrozenDataError(
        f"Frozen data mode forbids a user file absent from hydromodpy.lock: "
        f"{variable}/file/{resolved}."
    )


# ---------------------------------------------------------------------- write


def _git_head(cwd: Path) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return out.strip() or None


def _python_version() -> str:
    info = sys.version_info
    return f"{info.major}.{info.minor}.{info.micro}"


def _atomic_write_text(dest: Path, text: str) -> None:
    """Write *text* to *dest* atomically (tmp + fsync + replace)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}.tmp.{uuid.uuid4().hex[:8]}"
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            os.write(fd, text.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, dest)
        try:
            dir_fd = os.open(str(dest.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            # A directory fsync is not supported everywhere (Windows, tmpfs).
            pass
    finally:
        tmp.unlink(missing_ok=True)


def user_file_input(
    path: Path,
    *,
    variable: str,
    project_root: Path,
    sha256: str,
    license: str | None = None,
) -> LockedInput:
    """Return the record of one user file, its path relative to *project_root*."""
    resolved = Path(path).resolve()
    relative = Path(os.path.relpath(resolved, Path(project_root).resolve())).as_posix()
    return LockedInput(
        variable=variable,
        source=USER_FILE_SOURCE,
        station_id=None,
        product=None,
        path=relative,
        sha256=sha256,
        bytes=resolved.stat().st_size,
        license=license,
        fetched_at="",
    )


def cache_inputs(data_root: Path | None) -> list[LockedInput]:
    """Return one record per row of the data cache under *data_root*.

    An empty row is pinned too, with ``empty`` set and no digest, so a station
    that answered nothing replays frozen.
    """
    from hydromodpy.data.provenance.sidecars import CacheIndex

    if data_root is None:
        return []
    index = CacheIndex(data_root)
    return [
        LockedInput(
            variable=row.variable,
            source=row.source,
            station_id=row.station_id,
            product=row.product,
            path=index.relative(row.path),
            sha256=None if row.empty else str(row.sha256),
            bytes=None if row.empty else row.bytes,
            license=row.license,
            fetched_at="",
            empty=row.empty,
        )
        for row in index.rows()
    ]


def write_lockfile(
    dest: Path | str,
    data_root: Path | None,
    *,
    user_files: Sequence[LockedInput] = (),
    schema_sha256: str | None = None,
    project_root: Path | str | None = None,
) -> Path:
    """Write ``hydromodpy.lock`` at *dest* from the rows under *data_root* and *user_files*.

    The sha256 of the config schema is read by ``project``, which this layer
    cannot import, so the caller passes it in. The file is written atomically
    (tmp + ``fsync`` + ``os.replace``), and every record carries the one
    instant of the snapshot.
    """
    dest = Path(dest)
    stamped_at = datetime.now(UTC).isoformat(timespec="seconds")

    doc = tomlkit.document()
    doc.add("schema", LOCKFILE_SCHEMA)
    header = tomlkit.table()
    header.add("hydromodpy_version", _HMP_VERSION)
    git_commit = _git_head(_CHECKOUT_ROOT)
    if git_commit:
        header.add("git_commit", git_commit)
    project_commit = _git_head(Path(project_root)) if project_root else None
    if project_commit:
        header.add("project_git_commit", project_commit)
    header.add("python_version", _python_version())
    if schema_sha256 is not None:
        header.add("config_schema_sha256", schema_sha256)
    header.add("generated_at", stamped_at)
    doc.add("hydromodpy", header)

    records = tomlkit.aot()
    items = sorted(
        [*cache_inputs(data_root), *user_files],
        key=lambda item: (item.variable, item.source, item.station_id or "", item.path),
    )
    for item in items:
        table = tomlkit.table()
        table.add("variable", item.variable)
        table.add("source", item.source)
        if item.station_id is not None:
            table.add("station_id", item.station_id)
        if item.product is not None:
            table.add("product", item.product)
        table.add("path", item.path)
        if item.empty:
            table.add("empty", True)
        else:
            table.add("sha256", item.sha256)
            if item.bytes is not None:
                table.add("bytes", item.bytes)
        table.add("license", item.license or UNDETERMINED_LICENSE)
        table.add("fetched_at", stamped_at)
        records.append(table)
    doc["input"] = records

    _atomic_write_text(dest, tomlkit.dumps(doc))
    return dest


# ---------------------------------------------------------------------- verify


def _mismatch(
    item: LockedInput, kind: str, expected: Any, observed: Any, path: str
) -> LockMismatch:
    return LockMismatch(
        kind=kind,
        variable=item.variable,
        source=item.source,
        station_id=item.station_id,
        expected=expected,
        observed=observed,
        path=path,
    )


def _check_locked(item: LockedInput, path: Path) -> LockMismatch | None:
    if not path.is_file():
        return _mismatch(item, "missing", item.sha256, None, item.path)
    actual = sha256_of(path)
    if actual != item.sha256:
        return _mismatch(item, "sha256", item.sha256, actual, item.path)
    return None


def verify_lockfile(
    data_root: Path | None,
    lockfile: Path | str,
    *,
    project_root: Path | str | None = None,
    strict: bool = False,
) -> list[LockMismatch]:
    """Return what differs between *lockfile* and the files on disk.

    Each file the lockfile names is hashed again: a file gone is ``missing``,
    a file of other bytes is ``sha256``. A pinned empty row whose sidecar is
    gone is ``missing``. Without *strict*, a row of the data
    cache the lockfile does not name is ``missing`` too, with no expected
    digest. With *strict*, only the files the lockfile names are checked, the
    check ``hmp run --frozen`` makes, and a lockfile that names nothing is read
    without *strict*. User files are read under *project_root*, by default the
    folder of the lockfile.
    """
    from hydromodpy.data.provenance.sidecars import CacheIndex, sidecar_path_for

    lockfile = Path(lockfile)
    locked = read_lockfile_inputs(lockfile)
    if strict and not locked:
        strict = False
    anchor = Path(project_root) if project_root is not None else lockfile.parent
    index = CacheIndex(data_root)
    mismatches: list[LockMismatch] = []
    named: set[str] = set()
    for item in locked:
        if item.source == USER_FILE_SOURCE:
            path = anchor / item.path
        else:
            named.add(PurePosixPath(item.path).as_posix())
            path = index.resolve(item.path)
        if item.empty:
            gone = not sidecar_path_for(path).is_file()
            found = _mismatch(item, "missing", None, None, item.path) if gone else None
        else:
            found = _check_locked(item, path)
        if found is not None:
            mismatches.append(found)
    if not strict:
        for row in index.rows():
            relative = index.relative(row.path)
            if relative not in named:
                mismatches.append(
                    LockMismatch(
                        kind="missing",
                        variable=row.variable,
                        source=row.source,
                        station_id=row.station_id,
                        expected=None,
                        observed=relative,
                        path=relative,
                    )
                )
    return mismatches


__all__ = [
    "LOCKFILE_NAME",
    "LOCKFILE_REMEDY",
    "LOCKFILE_SCHEMA",
    "LOCKFILE_VERSIONS",
    "USER_FILE_SOURCE",
    "LockMismatch",
    "LockedInput",
    "LockedInputs",
    "cache_inputs",
    "project_lockfile_path",
    "read_lockfile_inputs",
    "read_lockfile_meta",
    "read_lockfile_schema_sha256",
    "read_locked_inputs",
    "reject_frozen_cache_miss",
    "reject_frozen_download",
    "reject_frozen_empty",
    "reject_frozen_record",
    "reject_frozen_row",
    "reject_frozen_user_file",
    "resolve_lockfile_root",
    "user_file_input",
    "verify_lockfile",
    "write_lockfile",
]
