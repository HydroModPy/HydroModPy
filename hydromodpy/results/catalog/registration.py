"""Names of the result directories of a project.

A run or a session is a directory, and its name is its address:
``runs/<name>``, ``sessions/<name>``. This module gives names out and moves
directories between them; it never reads the index.

- :func:`reserve_version_dirname` creates the directory of the next version
  of a name. The version is computed on disk, over the live directories, the
  trash and the tombstones, so a deleted name is never given out again.
- :func:`rename_case` moves a run, and the session of the same name, to a new
  name that nothing holds or held.
- :func:`import_publication` brings a run published by ``hmp publish`` into
  the project under a reserved name, after checking every digest.

The identity of a run, the request id and the solution key, lives in
:mod:`hydromodpy.results.request_identity`.

Grammar
-------
A name follows the rule of :func:`~hydromodpy.core.state.names.check_name`: lower
case letters, digits, ``_`` and ``-``, forty characters at most. The version suffix ``.v<N>`` is read by :func:`split_stem_version`; the bare name
is version 1 for good.
"""

from __future__ import annotations

import os
import re
import shutil
import tarfile
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from hydromodpy.core.exceptions import ImportConflictError, WriteConflictError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import internal_dir, runs_dir_for, sessions_dir_for
from hydromodpy.core.state.names import check_name
from hydromodpy.core.state.portable import to_workspace_relative
from hydromodpy.core.state.result_dirs import parse_rel_dir, run_dir_rel, session_dir_rel
from hydromodpy.results.publication import publication_path, read_publication
from hydromodpy.results.storage.contract import ALLOWED_RUN_ENTRIES, RUN_MANIFEST_FILENAME
from hydromodpy.results.storage.digests import sha256_streaming
from hydromodpy.results.trash import check_not_running, identity_of, list_trash, read_tombstones

logger = get_logger(__name__)


def portable_config_source(project_root: Path, config_source: str | Path | None) -> str | None:
    """Return ``config_source`` as stored with a run: portable when it can be.

    A configuration that lives inside the project is recorded relative to the
    project root (``project.toml``, ``configs/winter.toml``), so a project that
    is copied or moved still recognizes its own runs. A configuration kept
    outside the project has no project-relative form and is recorded as the
    absolute path it is; the leading separator tells the two apart.
    """
    if config_source is None:
        return None
    try:
        return to_workspace_relative(project_root, config_source)
    except ValueError:
        return str(config_source)


_VERSION_SUFFIX_RE = re.compile(r"\.v(\d+)$")


def split_stem_version(name: str) -> tuple[str, int | None]:
    """Split ``baseline.v3`` into ``("baseline", 3)``.

    A bare name returns ``(name, None)``.
    """
    match = _VERSION_SUFFIX_RE.search(name)
    if match:
        return name[: match.start()], int(match.group(1))
    return name, None


_RESERVE_ATTEMPTS = 1000


class VersionPairingError(WriteConflictError, FileExistsError):
    """The run directory a session is paired with is already taken."""


class NameTakenError(WriteConflictError):
    """A name is held by a live directory, a trashed one or a tombstone."""


def reserve_version_dirname(
    project_root: Path,
    kind: Literal["run", "session"],
    name: str,
    *,
    pair_with: Path | None = None,
) -> Path:
    """Create and return the directory of the next version of ``name``.

    The version is computed on disk and ``os.mkdir`` only makes the claim
    atomic. ``N`` is one more than the highest version of ``name`` found
    among the live directories of ``runs/`` and ``sessions/``, the trashed
    directories (by the relative directory they came from) and the
    tombstones of ``trash/tombstones.txt``. A deleted name is therefore
    never given out again. The bare name is version 1. Runs and sessions
    draw on one version space, so a run and a session of one name never hold
    the same ``N`` by accident.

    When another process wins the ``mkdir``, the version is computed again,
    so a version is never given twice. ``kind`` picks the tree the claim is
    made in. ``name`` is a bare directory name: a name that already carries
    ``.vN`` is refused.

    A calibration session and its promoted run are paired: the session
    reserves ``N`` first, and the run is reserved with ``pair_with`` naming
    the session directory. The run then takes the very same directory name
    under ``runs/``, whatever the version space says, and the claim fails
    with :class:`VersionPairingError` when that directory already exists.
    """
    stem, version = split_stem_version(name)
    if version is not None:
        raise ValueError(f"reserve the bare name {stem!r}, not the version {name!r}")
    check_name(name, what="run")
    root = Path(project_root)
    parent = runs_dir_for(root) if kind == "run" else sessions_dir_for(root)
    parent.mkdir(parents=True, exist_ok=True)
    if pair_with is not None:
        paired_stem, _ = split_stem_version(pair_with.name)
        if paired_stem != name:
            raise ValueError(f"{pair_with.name!r} is not a version of {name!r}")
        target = parent / pair_with.name
        try:
            os.mkdir(target)
        except FileExistsError as exc:
            raise VersionPairingError(
                f"{target} already exists: the run paired with {pair_with} cannot take "
                f"its version. Trash or rename the existing directory first."
            ) from exc
        return target
    for _ in range(_RESERVE_ATTEMPTS):
        target = parent / next_version_dirname(root, name)
        try:
            os.mkdir(target)
        except FileExistsError:
            continue
        return target
    raise RuntimeError(f"no version of {name!r} could be reserved under {parent}")


def next_version_dirname(project_root: Path, name: str) -> str:
    """Return the directory name the next version of ``name`` would take.

    It is what :func:`reserve_version_dirname` would claim now, computed on
    disk without creating anything: ``name`` when no version of it is held,
    else ``<name>.v<N+1>`` over the live, trashed and tombstoned versions. A
    dry run quotes it; another process may claim it before a real run does.
    """
    highest = max(_taken_versions(Path(project_root), name), default=0)
    return name if highest == 0 else f"{name}.v{highest + 1}"


def _holders(project_root: Path, name: str) -> list[tuple[str, int]]:
    """``(holder, version)`` of each live, trashed or tombstoned directory of ``name``.

    ``holder`` says where the version is held: its ``rel_dir`` for a live
    directory, ``trash:<rel_dir>`` and ``tombstone:<rel_dir>`` otherwise.
    """
    held: list[tuple[str, str]] = []
    for tree, rel in (
        (runs_dir_for(project_root), run_dir_rel),
        (sessions_dir_for(project_root), session_dir_rel),
    ):
        if tree.is_dir():
            held.extend((rel(entry.name), entry.name) for entry in tree.iterdir() if entry.is_dir())
    for label, rel_dirs in (
        ("trash", [entry.rel_dir for entry in list_trash(project_root)]),
        ("tombstone", [tombstone.rel_dir for tombstone in read_tombstones(project_root)]),
    ):
        for rel_dir in rel_dirs:
            parsed = parse_rel_dir(rel_dir)
            if parsed.kind in ("run", "session"):
                held.append((f"{label}:{rel_dir}", parsed.name))
    holders: list[tuple[str, int]] = []
    for holder, candidate in sorted(held):
        stem, version = split_stem_version(candidate)
        if stem == name:
            holders.append((holder, 1 if version is None else version))
    return holders


def _taken_versions(project_root: Path, name: str) -> list[int]:
    """Versions of ``name`` held by a live, trashed or tombstoned directory."""
    return [version for _, version in _holders(project_root, name)]


def check_name_free(project_root: Path, name: str, *, excluding: str | None = None) -> None:
    """Refuse ``name`` when any version of it is held; ``if_exists = "fail"`` calls it.

    A version is held by a live directory of ``runs/`` or ``sessions/``, a
    trashed one, or a tombstone. ``name`` is a bare name or a version; its
    stem is checked. ``excluding`` names a run directory that does not count,
    the one an attempt has just claimed for this very name. Raises
    :class:`NameTakenError` listing the holders.
    """
    stem = split_stem_version(name)[0]
    ignored = None if excluding is None else run_dir_rel(excluding)
    holders = [
        held for held in _holders(Path(project_root), stem) if ignored is None or held[0] != ignored
    ]
    if holders:
        listed = ", ".join(holder for holder, _ in holders)
        raise NameTakenError(
            f"The name {stem!r} is taken ({listed}) and [simulation] if_exists = 'fail'. "
            "Pick another name, or set if_exists = 'version' to write the next version."
        )


def live_version_dir(project_root: Path, name: str) -> Path:
    """Return the live directory of ``runs/`` a versioned name names, or refuse it.

    A ``.vN`` is given by the disk when a version is reserved, never written
    by hand. A versioned name such as ``nancon.v2`` therefore reaches only a
    live run directory: a resume or a retry works in it. A version the trash
    or a tombstone holds, or one nobody holds, is refused with
    :class:`NameTakenError`, and the refusal names the bare name to use.
    """
    stem, version = split_stem_version(name)
    if version is None:
        raise ValueError(f"{name!r} carries no version")
    exact = runs_dir_for(Path(project_root)) / name
    if exact.is_dir():
        return exact
    held = [holder for holder, number in _holders(Path(project_root), stem) if number == version]
    where = f" ({', '.join(held)})" if held else ""
    raise NameTakenError(
        f"{name!r} names no live run directory{where}. A version is given by the disk, "
        f"never written by hand: name the case {stem!r} and the run takes the next "
        "free version."
    )


def rename_case(
    project_root: Path, rel_dir: str, new_name: str, *, dry_run: bool = False
) -> tuple[str, ...]:
    """Move a run, and the session of the same name, to ``new_name``.

    ``rel_dir`` is ``runs/<name>`` or ``sessions/<name>``; whichever of the
    two directories exists moves, so a calibration keeps its session and its
    promoted run side by side. Links between them are ids and stay valid;
    the ``rel_dir`` a manifest recorded at the seal becomes a hint the
    indexer reads past.

    ``new_name`` is a directory name, with or without ``.vN``. Its version
    must be free among the live directories, the trash and the tombstones:
    a deleted name is never given out again, not even by a rename. The name
    left behind is free again: a rename leaves no tombstone, so a later run
    or rename may take it. A copy published under the old name still names
    its run by ``sim_id``. A directory a live attempt writes into is never
    moved.

    With *dry_run* every check runs and the new directories are returned, nothing moves.

    Returns the new relative directories, run first. Raises
    :class:`NameTakenError` for a taken name,
    :class:`~hydromodpy.core.exceptions.ConfigError` for a name that breaks the rule of a
    run name, ``ValueError`` for a kept trial.
    """
    root = Path(project_root)
    parsed = parse_rel_dir(rel_dir)
    if parsed.kind == "trial":
        raise ValueError(
            f"{rel_dir} is a kept trial; rename its session {session_dir_rel(parsed.name)}"
        )
    check_name(new_name, what="run")
    if new_name == parsed.name:
        raise ValueError(f"{rel_dir} is already named {new_name!r}")
    sources = [
        rel
        for rel in (run_dir_rel(parsed.name), session_dir_rel(parsed.name))
        if (root / rel).is_dir()
    ]
    if not sources:
        raise FileNotFoundError(f"{rel_dir} is not a directory of the project {root}")
    for rel in sources:
        check_not_running(root / rel, rel)
    stem, version = split_stem_version(new_name)
    if (version or 1) in _taken_versions(root, stem):
        raise NameTakenError(
            f"{new_name!r} is taken: a directory of runs/, sessions/ or the trash holds it, "
            "or a tombstone remembers it. A deleted name is never given out again."
        )
    if dry_run:
        return tuple(
            (run_dir_rel if rel == run_dir_rel(parsed.name) else session_dir_rel)(new_name)
            for rel in sources
        )
    moved: list[tuple[Path, Path]] = []
    try:
        for rel in sources:
            source = root / rel
            target = source.parent / new_name
            if target.exists():
                raise NameTakenError(f"{target} appeared while renaming {rel_dir}")
            os.rename(source, target)
            moved.append((source, target))
    except BaseException:
        for source, target in reversed(moved):
            os.rename(target, source)
        raise
    renamed = [run_dir_rel(new_name), session_dir_rel(new_name)]
    return tuple(rel for rel in renamed if (root / rel).is_dir())


_IMPORT_STAGING_PREFIX = "import-"


def import_publication(
    project_root: Path,
    source: Path,
    *,
    name: str | None = None,
    admit: Callable[[Path], None] | None = None,
    dry_run: bool = False,
) -> str:
    """Bring a run published by ``hmp publish`` into the project; return its ``rel_dir``.

    ``source`` is the published directory or its tar. Every file of the copy
    must be listed in its ``PUBLICATION.json`` and match its digest before
    anything enters ``runs/``. The run takes the next free version of
    ``name``, which defaults to the name of the published run without its
    ``.vN``: a published ``x.v2`` lands as ``x`` in a project without ``x``.
    Entries a run directory does not carry (``PUBLICATION.json``, the crate)
    stay out of it. The checked copy enters ``runs/`` by one rename, so a
    reader never sees part of it.

    *admit* is called with the checked copy before anything enters
    ``runs/``: the catalog layer installs the inputs of the copy there, and a
    refusal it raises leaves the project as it was.

    With *dry_run* the copy is staged outside the project, every check and *admit* run,
    and the ``rel_dir`` the run would take is returned. Nothing enters the project.

    Raises :class:`~hydromodpy.core.exceptions.ImportConflictError` when a
    run of the project already carries the published ``sim_id``, and
    ``ValueError`` when the copy is not a sealed run or a digest differs.
    """
    root = Path(project_root)
    origin = Path(source).expanduser()
    if not origin.exists():
        raise FileNotFoundError(f"No published run at {origin}")
    if dry_run:
        staging = Path(tempfile.mkdtemp(prefix=_IMPORT_STAGING_PREFIX))
    else:
        staging = internal_dir(root) / f"{_IMPORT_STAGING_PREFIX}{uuid.uuid4().hex}"
        staging.mkdir(parents=True)
    try:
        copy = _stage_copy(origin, staging)
        publication = read_publication(copy)
        if publication.kind == "project" and not publication.members:
            raise ValueError(
                f"{origin} is a project package written by hmp publish --package; install it "
                "with hmp project import."
            )
        if publication.kind != "run":
            raise ValueError(
                f"{origin} is a {publication.kind} copy; only a run is imported. "
                "Import one of its members."
            )
        source_rel = parse_rel_dir(publication.source.rel_dir)
        if source_rel.kind != "run":
            raise ValueError(
                f"{origin} publishes {publication.source.rel_dir}; only a run is imported"
            )
        _check_digests(copy, publication.files, origin)
        if not (copy / RUN_MANIFEST_FILENAME).is_file():
            raise ValueError(f"{origin} carries no {RUN_MANIFEST_FILENAME}: not a sealed run")
        sim_id = publication.source.sim_id or identity_of(copy)
        holder = run_dir_holding(root, sim_id)
        if holder is not None:
            raise ImportConflictError(
                f"Run {sim_id} is already in this project, as {holder}. "
                "Trash it first to import the copy again."
            )
        if admit is not None:
            admit(copy)
        if dry_run:
            bare = name if name is not None else split_stem_version(source_rel.name)[0]
            return run_dir_rel(next_version_dirname(root, bare))
        for entry in sorted(copy.iterdir()):
            if entry.name not in ALLOWED_RUN_ENTRIES:
                logger.info("%s is not a run entry; left out of the import", entry.name)
                _remove(entry)
        bare = name if name is not None else split_stem_version(source_rel.name)[0]
        target = reserve_version_dirname(root, "run", bare)
        try:
            # One rename onto the empty reserved directory: the run appears whole or not at all.
            os.rename(copy, target)
        except BaseException:
            target.rmdir()
            raise
        return run_dir_rel(target.name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _remove(entry: Path) -> None:
    if entry.is_dir() and not entry.is_symlink():
        shutil.rmtree(entry)
    else:
        entry.unlink()


def _stage_copy(origin: Path, staging: Path) -> Path:
    """Copy or extract ``origin`` under ``staging``; return the directory holding the publication."""
    landing = staging / "copy"
    if origin.is_dir():
        shutil.copytree(origin, landing, symlinks=True)
    else:
        landing.mkdir()
        with tarfile.open(origin) as archive:
            archive.extractall(landing, filter="data")
    if publication_path(landing).is_file():
        return landing
    children = [entry for entry in landing.iterdir() if entry.is_dir()]
    if len(children) == 1 and publication_path(children[0]).is_file():
        return children[0]
    raise ValueError(f"{origin} holds no PUBLICATION.json: it was not written by hmp publish")


def _check_digests(copy: Path, files: dict[str, str], origin: Path) -> None:
    """Every file of the copy is listed in PUBLICATION.json and matches its digest."""
    publication = publication_path(copy)
    unlisted = sorted(
        path.relative_to(copy).as_posix()
        for path in copy.rglob("*")
        if (path.is_file() or path.is_symlink())
        and path != publication
        and path.relative_to(copy).as_posix() not in files
    )
    if unlisted:
        raise ValueError(
            f"{origin}: {', '.join(unlisted[:5])} not listed in PUBLICATION.json; "
            "a published copy carries nothing its digests do not cover"
        )
    for rel, digest in sorted(files.items()):
        path = copy / rel
        if not path.is_file():
            raise ValueError(f"{origin}: {rel} is listed in PUBLICATION.json and missing")
        if sha256_streaming(path) != digest:
            raise ValueError(f"{origin}: {rel} does not match its digest in PUBLICATION.json")


def run_dir_holding(project_root: Path, sim_id: str | None) -> str | None:
    """Return the ``rel_dir`` of the run under ``runs/`` that carries ``sim_id``, if one does.

    Read from each run's ``outcome.json`` or ``manifest.json``, without the index.
    """
    if not sim_id:
        return None
    runs = runs_dir_for(project_root)
    if not runs.is_dir():
        return None
    for entry in sorted(runs.iterdir()):
        if entry.is_dir() and identity_of(entry) == sim_id:
            return run_dir_rel(entry.name)
    return None
