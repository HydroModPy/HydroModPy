"""The two fingerprints of a run: what it asks, and what computes it.

The request id says what a run asks for. It is the sha256 of the document the
run was given, as a file writes it, without what does not change the answer:
``[workspace]``, ``[workflow]``, ``simulation.name`` (:data:`REQUEST_EXCLUDED`)
and every ``deliver_to`` key (:func:`~hydromodpy.results.exporters.destination.without_delivery`).
Each input resolved before the run enters by the
digest of its bytes and its state, and its path or its URL leaves the document,
so two addresses that give the same bytes ask the same thing. An earlier run the
configuration reads (``[flow] restart_from``, the ``run`` of a refinement zone)
enters by the digest of the arrays the run reads from it, never by its name or
its ``sim_id``. The edition of the defaults and the state a window starts from
enter too.

The solution key says what computes the answer: the request id, the code that
computes, the mesh engine and its version, the bytes of each solver binary and
the versions of the numeric packages. Two runs with the same key give the same
numbers, and a completed run is reused only on an equal key.

A source of an API whose extent comes from the delineated catchment is fetched
after the identity is known, so it enters by its declaration in the document,
and its digest is sealed in ``inputs.json``.

This module reads ``core`` and ``results`` only. The caller resolves the inputs
and passes their digests as a mapping.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Mapping, Sequence
from functools import cache, lru_cache
from importlib import metadata
from pathlib import Path
from typing import Any, Final

import numpy as np

from hydromodpy.core.io.canonical_json import dumps
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.core.logging import get_logger
from hydromodpy.core.workspace.resolve import locate_workspace_root
from hydromodpy.model.initial.state import PriorState
from hydromodpy.results.exporters.destination import without_delivery
from hydromodpy.results.record.manifest import KEY_PACKAGES

logger = get_logger(__name__)

REQUEST_ID_COMPOSITION: Final[str] = "hydromodpy.request_id.v1"
"""The name of what a request id covers. Another composition gives other ids."""

SOLUTION_KEY_COMPOSITION: Final[str] = "hydromodpy.solution_key.v1"
"""The name of what a solution key covers."""

REQUEST_EXCLUDED: Final[tuple[str, ...]] = (
    "workspace",
    "workflow",
    "simulation.name",
)
"""The keys of a document that never enter a request id.

A dotted key is left out where it is. ``[workspace]`` says where the project
lives, ``[workflow]`` what ``hmp run`` does with the file, and
``simulation.name`` the folder of the run: none of them changes a number.
``deliver_to`` leaves by :func:`without_delivery`, which reads the blocks of
``[[export]]`` rather than a name at any depth.
"""

INPUT_ADDRESS_KEYS: Final[Mapping[str, tuple[str, ...]]] = {
    "file": ("path",),
    "url": ("url", "sha256"),
}
"""The keys of a ``[[data.<section>.sources]]`` entry that only say where its bytes are.

They leave the document when the section has a resolved input, whose digest
stands for them.
"""

INPUT_ROLE_SEPARATOR: Final[str] = "."
"""What joins a section of ``[data]`` and the index of a resolved file in its role."""

RESTART_KEY: Final[str] = "flow.restart_from"
"""The key of the run a simulation starts from."""

ZONE_RUN_KEY: Final[str] = "mesh.refinement_zone.{index}.run"
"""The key of the run a refinement zone reads, by the index of the zone."""

InputDigests = Mapping[str, Sequence[str | None]]
"""``{role: (digest, state)}`` of the inputs resolved before the run."""


def input_role(section: str, index: int) -> str:
    """Return the role of the *index*-th file resolved for the ``[data]`` *section*."""
    return f"{section}{INPUT_ROLE_SEPARATOR}{index}"


def section_of_role(role: str) -> str | None:
    """Return the ``[data]`` section of a role :func:`input_role` made, else ``None``."""
    section, separator, index = role.rpartition(INPUT_ROLE_SEPARATOR)
    if not separator or not index.isdigit() or ":" in section:
        return None
    return section


def request_id(
    document: Mapping[str, Any],
    inputs: InputDigests,
    *,
    edition: str,
    window_state: str | None = None,
    source_states: Mapping[str, str] | None = None,
) -> str:
    """Return the sha256 that says what a run asks for.

    Parameters
    ----------
    document
        The configuration as a file writes it. A ``[workspace] project_root`` it
        carries anchors its paths: a path under the project, or elsewhere in the
        workspace of the project, enters relative to the project, so two copies of
        a project ask alike. A run leaves ``[calibration]`` out of the document; a
        calibration session keeps it.
    inputs
        ``{role: (digest, state)}`` of each input resolved before the run. A role
        made by :func:`input_role` takes the address of the files of its section
        out of the document.
    edition
        The edition of the defaults the document is read with.
    window_state
        The digest of the state the previous window of the run ended in, or
        ``None`` for a run that starts on its own.
    source_states
        ``{key: digest}`` of each earlier run the configuration reads, by the key
        that names it (:data:`RESTART_KEY`, :data:`ZONE_RUN_KEY`). The digest takes
        the place of the name in the document.
    """
    body = {
        "composition": REQUEST_ID_COMPOSITION,
        "document": _requested(document, inputs, source_states or {}),
        "inputs": {role: [*map(_text, value)] for role, value in sorted(inputs.items())},
        "edition": str(edition),
        "window_state": window_state,
    }
    return hashlib.sha256(dumps(body).encode("utf-8")).hexdigest()


def solution_key(
    request: str,
    *,
    mesh_engine: Mapping[str, str],
    binaries: Mapping[str, str | os.PathLike[str] | None],
    code: Mapping[str, str] | None = None,
    packages: Mapping[str, str | None] | None = None,
) -> str:
    """Return the sha256 that says what computes the answer to the request *request*.

    *mesh_engine* is :func:`mesh_engine_identity` of the document, *binaries*
    names each solver binary the run calls by its path, hashed by
    :func:`binary_digest`. *code* is the fingerprint of the code that computes
    and *packages* the versions of :data:`~hydromodpy.results.record.manifest.KEY_PACKAGES`;
    both are read from this process when not given. The run name never enters.
    """
    from hydromodpy.core.code_fingerprint import RUN_LAYERS, code_fingerprint

    body = {
        "composition": SOLUTION_KEY_COMPOSITION,
        "request_id": request,
        "code": dict(code if code is not None else code_fingerprint(RUN_LAYERS)),
        "mesh_engine": dict(mesh_engine),
        "binaries": {
            name: binary_digest(path) for name, path in sorted(binaries.items(), key=_first)
        },
        "packages": dict(packages if packages is not None else package_versions()),
    }
    return hashlib.sha256(dumps(body).encode("utf-8")).hexdigest()


def mesh_engine_identity(document: Mapping[str, Any]) -> dict[str, str]:
    """Return ``{"engine": id, "version": engine_version}`` of the mesh engine *document* names.

    The engine is ``[mesh] engine``, or the registry default when the section
    or the key is absent. Its version bumps when its output changes, so a run
    meshed by another build is another computation. An id no engine answers
    to, or an engine that cannot be imported, gets a random salt: the run then
    matches no other run, which errs on the side of computing.
    """
    from hydromodpy.core.exceptions import MeshRequestError
    from hydromodpy.mesh import registry as mesh_registry

    section = document.get("mesh")
    engine_id = section.get("engine") if isinstance(section, Mapping) else None
    try:
        engine_cls = mesh_registry.mesh_engines.get(engine_id)
    except (MeshRequestError, ImportError) as exc:
        logger.warning("Mesh engine not hashed into the run identity: %s", exc)
        return {"engine": str(engine_id), "version": uuid.uuid4().hex}
    return {"engine": engine_cls.engine_id, "version": engine_cls.engine_version}


def binary_digest(path: str | os.PathLike[str] | None) -> str | None:
    """Return the sha256 of the binary at *path*, or ``None`` when there is none.

    The digest is kept in the memory of the process by resolved path, size and
    modification time, so a plan of many cases reads each binary once. A binary
    rewritten in place changes its size or its time, and is read again.
    """
    if path is None:
        return None
    target = Path(path).expanduser().resolve()
    try:
        stat = target.stat()
    except OSError:
        return None
    if not target.is_file():
        return None
    return _sha256_of(str(target), stat.st_size, stat.st_mtime_ns)


def package_versions() -> dict[str, str | None]:
    """Return the version of each package of ``KEY_PACKAGES``, ``None`` when it is absent."""
    return dict(_package_versions())


def array_digest(arrays: Mapping[str, Any]) -> str:
    """Return the sha256 of named arrays, read as float64 values.

    Each array is read in C order as float64, every NaN as the one quiet NaN and
    ``-0.0`` as ``0.0``, with its shape. The names enter sorted, so the order of
    the mapping does not count.
    """
    digest = hashlib.sha256()
    for name in sorted(arrays):
        values = np.ascontiguousarray(np.asarray(arrays[name], dtype=np.float64))
        values = np.where(np.isnan(values), np.nan, values) + 0.0
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(json.dumps(list(values.shape)).encode("ascii"))
        digest.update(b"\0")
        digest.update(values.tobytes(order="C"))
    return digest.hexdigest()


def prior_state_digest(state: PriorState) -> str:
    """Return the sha256 of what a run reads from the run it starts from.

    The head of each cell and the stage of each lake, with the shape of the head
    and the lake ids. The stage of each SFR reach and the reach numbers count
    too, when the state carries them; a state without reach stages keeps the
    digest it had before reach stages existed, so a restart of an earlier run is
    still the same request. The store path and the ``sim_id`` of the earlier run
    stay out: two runs that leave the same state give the same digest.
    """
    lakes = sorted(state.lake_stages)
    reaches = sorted(state.sfr_stages)
    digest = hashlib.sha256()
    digest.update(json.dumps(lakes).encode("utf-8"))
    digest.update(b"\0")
    if reaches:
        digest.update(json.dumps(reaches).encode("utf-8"))
        digest.update(b"\0")
    arrays = {
        "head": state.head,
        "lake_stages": np.array([state.lake_stages[lake] for lake in lakes], dtype=float),
    }
    if reaches:
        arrays["sfr_stages"] = np.array([state.sfr_stages[reach] for reach in reaches], dtype=float)
    digest.update(array_digest(arrays).encode("ascii"))
    return digest.hexdigest()


@lru_cache(maxsize=256)
def _sha256_of(path: str, size: int, mtime_ns: int) -> str | None:
    """Hash one binary; the size and the time are part of the key of the memory."""
    try:
        return sha256_of(path)
    except OSError:
        return None


@cache
def _package_versions() -> tuple[tuple[str, str | None], ...]:
    found: list[tuple[str, str | None]] = []
    for name in KEY_PACKAGES:
        try:
            found.append((name, metadata.version(name)))
        except metadata.PackageNotFoundError:
            found.append((name, None))
    return tuple(found)


def _requested(
    document: Mapping[str, Any], inputs: InputDigests, source_states: Mapping[str, str]
) -> dict[str, Any]:
    """Return *document* as the request id reads it."""
    payload = without_delivery(json.loads(json.dumps(dict(document), default=str)))
    workspace = payload.get("workspace")
    root = workspace.get("project_root") if isinstance(workspace, dict) else None
    if root:
        payload = _relative_paths(payload, Path(str(root)), locate_workspace_root(Path(str(root))))
    _drop_excluded(payload)
    _drop_input_addresses(payload, {section_of_role(role) for role in inputs} - {None})
    _put_source_states(payload, source_states)
    return payload


def _drop_excluded(payload: dict[str, Any]) -> None:
    for key in REQUEST_EXCLUDED:
        if key.startswith("*."):
            _drop_everywhere(payload, key[2:])
            continue
        *parents, leaf = key.split(".")
        holder: Any = payload
        for part in parents:
            holder = holder.get(part) if isinstance(holder, dict) else None
        if isinstance(holder, dict):
            holder.pop(leaf, None)
            if parents and not holder:
                # A section left with nothing is a section left at its defaults.
                payload.pop(parents[0], None)


def _drop_everywhere(value: Any, key: str) -> None:
    if isinstance(value, dict):
        value.pop(key, None)
        for item in value.values():
            _drop_everywhere(item, key)
    elif isinstance(value, list):
        for item in value:
            _drop_everywhere(item, key)


def _drop_input_addresses(payload: dict[str, Any], sections: set[str | None]) -> None:
    data = payload.get("data")
    if not isinstance(data, dict):
        return
    for section in sections:
        table = data.get(section) if section else None
        sources = table.get("sources") if isinstance(table, dict) else None
        for source in sources if isinstance(sources, list) else ():
            if isinstance(source, dict):
                for key in INPUT_ADDRESS_KEYS.get(str(source.get("source")), ()):
                    source.pop(key, None)


def _put_source_states(payload: dict[str, Any], source_states: Mapping[str, str]) -> None:
    for key, digest in source_states.items():
        holder: Any = payload
        *parents, leaf = key.split(".")
        for part in parents:
            if isinstance(holder, list) and part.isdigit() and int(part) < len(holder):
                holder = holder[int(part)]
            elif isinstance(holder, dict) and isinstance(holder.get(part), (dict, list)):
                holder = holder[part]
            else:
                raise KeyError(f"{key}: the document names no earlier run there.")
        if not isinstance(holder, dict) or leaf not in holder:
            raise KeyError(f"{key}: the document names no earlier run there.")
        holder[leaf] = {"state": digest}


def _relative_paths(value: Any, project_root: Path, workspace: Path | None) -> Any:
    """Return *value* with each absolute path of the workspace made relative to the project.

    A path outside the workspace stays as it is: no copy of the workspace carries it.
    """
    if isinstance(value, dict):
        return {key: _relative_paths(item, project_root, workspace) for key, item in value.items()}
    if isinstance(value, list):
        return [_relative_paths(item, project_root, workspace) for item in value]
    if isinstance(value, str):
        return portable_path(value, project_root, workspace)
    return value


def portable_path(text: str, project_root: Path, workspace: Path | None) -> str:
    """Return the absolute path *text* relative to *project_root* when the workspace holds it.

    A path under the project, or elsewhere in the *workspace* of the project, is
    written relative to the project, so two copies of a project name it alike. A
    URL, a relative path and a path outside the workspace stay as they are.
    """
    if "://" in text or not Path(text).is_absolute():
        return text
    path = Path(text)
    if path.is_relative_to(project_root):
        return path.relative_to(project_root).as_posix()
    if workspace is not None and path.is_relative_to(workspace):
        return Path(os.path.relpath(path, project_root)).as_posix()
    return text


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _first(item: tuple[str, Any]) -> str:
    return item[0]


__all__ = [
    "INPUT_ADDRESS_KEYS",
    "REQUEST_EXCLUDED",
    "REQUEST_ID_COMPOSITION",
    "RESTART_KEY",
    "SOLUTION_KEY_COMPOSITION",
    "ZONE_RUN_KEY",
    "InputDigests",
    "array_digest",
    "binary_digest",
    "input_role",
    "mesh_engine_identity",
    "package_versions",
    "portable_path",
    "prior_state_digest",
    "request_id",
    "section_of_role",
    "solution_key",
]
