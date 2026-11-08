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
- :func:`run_identity_hash` and :func:`config_identity_hash` say when two runs
  compute the same thing.

Grammar
-------
A name is a directory name (:func:`run_dirname` keeps it as written). The
version suffix ``.v<N>`` is read by :func:`split_stem_version`; the bare name
is version 1 for good.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from hydromodpy.core.config_kit.written import written_as_a_file
from hydromodpy.core.exceptions import ImportConflictError, WriteConflictError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import internal_dir, runs_dir_for, sessions_dir_for
from hydromodpy.core.state.portable import to_workspace_relative
from hydromodpy.core.state.result_dirs import parse_rel_dir, run_dir_rel, session_dir_rel
from hydromodpy.core.workspace.resolve import locate_workspace_root
from hydromodpy.results.catalog.storage_paths import run_dirname
from hydromodpy.results.publication import publication_path, read_publication
from hydromodpy.results.storage.contract import ALLOWED_RUN_ENTRIES, RUN_MANIFEST_FILENAME
from hydromodpy.results.storage.digests import sha256_directory, sha256_streaming
from hydromodpy.results.trash import check_not_running, identity_of, list_trash, read_tombstones

logger = get_logger(__name__)

_RUN_INPUTS_KEY = "__run_inputs__"
_RUN_CODE_KEY = "__code__"
_RUN_MESH_ENGINE_KEY = "__mesh_engine__"
_WORKSPACE_SECTION = "workspace"
_WORKFLOW_SECTION = "workflow"
_SEARCH_SECTION = "calibration"


def run_identity_hash(config: dict | None, *, inputs: dict[str, str] | None = None) -> str | None:
    """Return the hash that says two runs compute the same thing.

    It is the ``config_hash`` of a run and of a planned case, and what
    ``hmp run`` and ``hmp.run`` compare to skip an identical completed run.
    It covers the configuration without its ``[workspace]`` section and without
    ``simulation.name``, the digests of the input files the configuration names
    (``inputs``, from :func:`input_file_digests`), the fingerprint of the code
    that computes (:func:`~hydromodpy.core.code_fingerprint.code_fingerprint`) and
    the mesh engine with its version (:func:`mesh_engine_identity`). A changed
    data file, an edit of a solver or another build of the mesh engine is another
    computation; another machine, workspace, project root or release that leaves
    the code alone is not. A path under the project root enters the hash relative
    to it, so two copies of one project hash alike.

    An override of a run is a change of its configuration, so it needs no entry of
    its own. :func:`config_identity_hash` gives what the configuration wrote: a
    default that moves is seen by the fingerprint, and a key written at its default
    value counts, because a validator can tell the two apart (``surface_offset`` of
    an ETP under a soil reservoir). ``[workflow]`` stays out: it says what ``hmp run``
    does with the file, and the sections hold what that computes.

    A run the configuration reads (``[flow] restart_from``, the ``run`` of a
    ``[[mesh.refinement_zone]]``) enters by its ``sim_id``
    (:func:`~hydromodpy.results.source_runs.resolve_source_runs`): the
    configuration of a run and the one it froze, which names the ``sim_id``,
    hash alike, and a later version of the source run is another computation.

    The run name is not part of the hash: it is the directory, which a rename
    moves.
    """
    if not config:
        return None
    from hydromodpy.core.code_fingerprint import RUN_LAYERS, code_fingerprint
    from hydromodpy.results.source_runs import resolve_source_runs

    payload = json.loads(json.dumps(config, default=str))
    payload.pop(_WORKFLOW_SECTION, None)
    workspace = payload.pop(_WORKSPACE_SECTION, None)
    project_root = workspace.get("project_root") if isinstance(workspace, dict) else None
    if project_root:
        resolve_source_runs(payload, Path(str(project_root)))
        payload = _relative_to_project(payload, Path(str(project_root)))
    simulation = payload.get("simulation")
    if isinstance(simulation, dict):
        simulation.pop("name", None)
        if not simulation:
            # A section left with nothing is a section left at its defaults.
            del payload["simulation"]
    payload[_RUN_INPUTS_KEY] = dict(sorted((inputs or {}).items()))
    payload[_RUN_CODE_KEY] = code_fingerprint(RUN_LAYERS)
    payload[_RUN_MESH_ENGINE_KEY] = mesh_engine_identity(payload)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def config_identity_hash(config: Any) -> str | None:
    """Return the identity hash of a validated configuration and of the files it names.

    The dump is what the configuration wrote, as the ``config.toml`` of its run reads
    back (:func:`~hydromodpy.core.config_kit.written.written_as_a_file`): a key written
    at its default value counts, and so does an override. The project root anchors the
    paths, so it stays even when ``[workspace]`` equals the default the current
    directory would give it. A ``[calibration]`` section enters: this is what a session
    and a planned case compare. What a run compares is :func:`solve_identity_hash`.
    """
    dump = written_as_a_file(config)
    root = getattr(getattr(config, "workspace", None), "project_root", None)
    if root is not None:
        dump[_WORKSPACE_SECTION] = {"project_root": str(root)}
    return run_identity_hash(dump, inputs=input_file_digests(config))


def solve_identity_hash(config: Any) -> str | None:
    """Return the identity hash of the solve *config* describes, without its search.

    It is the ``config_hash`` of a run, promoted by a calibration or not: a run seals
    its own solve and not the search that chose its parameters, so its ``config.toml``
    reads back to this hash.
    """
    if getattr(config, _SEARCH_SECTION, None) is not None:
        config = config.model_copy(update={_SEARCH_SECTION: None})
    return config_identity_hash(config)


def _relative_to_project(value: Any, project_root: Path) -> Any:
    """Return ``value`` with every absolute path of the workspace made relative to the project.

    A path under the project root becomes relative to it, a path elsewhere in
    the workspace of the project relative to the project root
    (``../../data/dem/dem.tif``), so the same configuration hashes alike in
    two workspaces. A path outside the workspace is left as it is: no copy of
    the workspace carries it.
    """
    return _relative_paths(value, project_root, locate_workspace_root(project_root))


def _relative_paths(value: Any, project_root: Path, workspace: Path | None) -> Any:
    if isinstance(value, dict):
        return {key: _relative_paths(item, project_root, workspace) for key, item in value.items()}
    if isinstance(value, list):
        return [_relative_paths(item, project_root, workspace) for item in value]
    if isinstance(value, str):
        return _portable_path_text(value, project_root, workspace)
    return value


def _portable_path_text(text: str, project_root: Path, workspace: Path | None) -> str:
    """Return ``text`` relative to ``project_root`` when it is an absolute path of the workspace."""
    if "://" in text or not Path(text).is_absolute():
        return text
    path = Path(text)
    if path.is_relative_to(project_root):
        return path.relative_to(project_root).as_posix()
    if workspace is not None and path.is_relative_to(workspace):
        return Path(os.path.relpath(path, project_root)).as_posix()
    return text


def mesh_engine_identity(config: dict) -> dict[str, str]:
    """Return ``{"engine": id, "version": engine_version}`` of the mesh engine ``config`` names.

    The engine is ``[mesh] engine``, or the registry default when the section
    or the key is absent. Its version bumps when its output changes, so a run
    meshed by another build is another computation. An id no engine answers
    to, or an engine that cannot be imported, gets a random salt: the run then
    matches no other run, which errs on the side of computing.
    """
    from hydromodpy.core.exceptions import MeshRequestError
    from hydromodpy.mesh import registry as mesh_registry

    section = config.get("mesh")
    engine_id = section.get("engine") if isinstance(section, dict) else None
    try:
        engine_cls = mesh_registry.mesh_engines.get(engine_id)
    except (MeshRequestError, ImportError) as exc:
        logger.warning("Mesh engine not hashed into the run identity: %s", exc)
        return {"engine": str(engine_id), "version": uuid.uuid4().hex}
    return {"engine": engine_cls.engine_id, "version": engine_cls.engine_version}


def input_file_digests(config: Any) -> dict[str, str]:
    """Return ``{"<role>:<path>": sha256}`` for the inputs ``config`` names.

    ``<path>`` is relative to the project root when the file lies under it,
    so two copies of a project name their inputs alike.

    The files are the ``InputFile`` fields of the configuration
    (:func:`hydromodpy.core.tracking.collect_input_files`), anchored on the
    project root, and hashed the way ``tracked_files`` hashes them. A path
    that does not exist hashes to ``"missing"``. A file that cannot be read,
    or a configuration that cannot be walked, gets a random salt: the run
    then matches no other run, which errs on the side of computing, and the
    error never stops it.
    """
    from hydromodpy.core.tracking import collect_input_files

    root = getattr(getattr(config, "workspace", None), "project_root", None)
    try:
        entries = collect_input_files(config, base=root)
    except Exception as exc:  # noqa: BLE001 - identity must never stop a run
        logger.warning("Input files not hashed into the run identity: %s", exc)
        return {"__unwalked__": uuid.uuid4().hex}
    digests: dict[str, str] = {}
    for entry in entries:
        path = Path(entry.canonical_path)
        try:
            if path.is_file():
                digest = sha256_streaming(path)
            elif path.is_dir():
                digest = sha256_directory(path)
            else:
                digest = "missing"
        except OSError as exc:
            logger.warning("Input file %s not hashed into the run identity: %s", path, exc)
            digest = f"unreadable:{uuid.uuid4().hex}"
        named = str(entry.original_path)
        if root is not None:
            named = _portable_path_text(named, Path(root), locate_workspace_root(root))
        digests[f"{entry.role}:{named}"] = digest
    return digests


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
    if run_dirname(name) != name:
        raise ValueError(f"{name!r} is not a directory name; use {run_dirname(name)!r}")
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


def check_name_free(project_root: Path, name: str) -> None:
    """Refuse ``name`` when any version of it is held; ``if_exists = "fail"`` calls it.

    A version is held by a live directory of ``runs/`` or ``sessions/``, a
    trashed one, or a tombstone. ``name`` is a bare name or a version; its
    stem is checked. Raises :class:`NameTakenError` listing the holders.
    """
    stem = split_stem_version(name)[0]
    holders = _holders(Path(project_root), stem)
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
    :class:`NameTakenError` for a taken name, ``ValueError`` for a name that
    is not a directory name or for a kept trial.
    """
    root = Path(project_root)
    parsed = parse_rel_dir(rel_dir)
    if parsed.kind == "trial":
        raise ValueError(
            f"{rel_dir} is a kept trial; rename its session {session_dir_rel(parsed.name)}"
        )
    if run_dirname(new_name) != new_name:
        raise ValueError(f"{new_name!r} is not a directory name; use {run_dirname(new_name)!r}")
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
