"""The request id and the solution key of a case, told before or during its run.

A run is identical to a completed one when their solution keys agree
(:func:`~hydromodpy.results.record.request_identity.solution_key`): the request id,
which reads the written document, the edition and the digest and state of every
input, then the code, the solver binaries and the numeric packages. The request
id reads the inputs the data layer resolves, which ``results`` never reads, so
it is told here. :func:`input_digests` turns resolved inputs into the digests
:func:`~hydromodpy.results.record.request_identity.request_id` reads. A run tells its
key once its inputs are resolved (:func:`request_id_of`); a plan, a dry run and
a calibration tell it offline (:func:`planned_solution_key`), and a case that
needs the network then reads as not done.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config_kit.written import written_as_a_file
from hydromodpy.core.exceptions import HydroModPyError
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.workspace.resolve import locate_workspace_root
from hydromodpy.results.record.request_identity import (
    input_role,
    mesh_engine_identity,
    portable_path,
    request_id,
    solution_key,
)
from hydromodpy.results.storage.digests import sha256_directory

logger = get_logger(__name__)

SEARCH_SECTION: Final[str] = "calibration"
"""The section a run leaves out of its request id and a calibration session keeps."""


def request_document(cfg: HydroModPyConfig, *, search: bool) -> dict[str, Any]:
    """Return the document whose request id says what *cfg* asks for.

    It is what a file of *cfg* writes, with its project root to anchor its
    paths. A run leaves ``[calibration]`` out (``search=False``): it computes the
    same whatever search chose its parameters. A calibration session keeps it.
    """
    document = written_as_a_file(cfg)
    document.setdefault("workspace", {})["project_root"] = str(cfg.workspace.project_root)
    if not search:
        document.pop(SEARCH_SECTION, None)
    return document


def input_digests(cfg: HydroModPyConfig, resolved: Any) -> dict[str, list[str | None]]:
    """Return ``{role: [digest, state]}`` of the inputs of *cfg*.

    *resolved* is what :func:`~hydromodpy.data.loading.inputs.resolve_inputs`
    returned: each file it resolved enters by its role (the section of
    ``[data]`` and its index) with the sha256 of its bytes and its state. Every
    other file the configuration names enters by its role and its path, relative
    to the project, with the digest of its bytes and no state; a missing file is
    ``missing`` and an unreadable one gets a random salt, so the run matches no
    other run.
    """
    from hydromodpy.core.tracking.walker import collect_input_files

    found: dict[str, list[str | None]] = {}
    if resolved.dem is not None:
        found[input_role("dem", 0)] = [resolved.dem.sha256, resolved.dem.state]
    for section, records in sorted(resolved.records.items()):
        for index, record in enumerate(records):
            found[input_role(section, index)] = [record.sha256, record.state]
    covered = [Path(record.path).resolve() for record in resolved.all_records]
    root = Path(cfg.workspace.project_root)
    workspace = locate_workspace_root(root)
    for entry in collect_input_files(cfg, base=root):
        path = Path(entry.canonical_path)
        if any(item == path or item.is_relative_to(path) for item in covered):
            continue
        named = portable_path(str(entry.original_path), root, workspace)
        found[f"{entry.role}:{named}"] = [_file_digest(path), None]
    return found


def request_id_of(
    cfg: HydroModPyConfig,
    resolved: Any,
    *,
    search: bool,
    window_state: str | None = None,
    source_states: Mapping[str, str] | None = None,
) -> str:
    """Return the request id of *cfg* with the inputs *resolved* gave."""
    return request_id(
        request_document(cfg, search=search),
        input_digests(cfg, resolved),
        edition=cfg.edition,
        window_state=window_state,
        source_states=source_states,
    )


def planned_request_id(
    cfg: HydroModPyConfig, *, search: bool | None = None, data_dir: Path | None = None
) -> str | None:
    """Return the request id of *cfg* computed offline, or ``None`` when it needs the network.

    The inputs are resolved with no host allowed: an input already in the cache
    resolves, and one that would be fetched gives ``None``. A plan then reads the
    case as not done and launches it, and the worker skips it when a completed run
    answers. An earlier run the configuration reads enters by its name here, so a
    case that restarts from one also reads as not done. *search* defaults to
    whether *cfg* has a ``[calibration]``. A plan compares a solution key built on
    this id (:func:`planned_solution_key`), never the id itself.
    """
    from hydromodpy.data.loading.inputs import resolve_inputs

    keeps_search = getattr(cfg, SEARCH_SECTION, None) is not None if search is None else search
    try:
        resolved = resolve_inputs(
            cfg,
            bounds=Bounds(allowed_hosts=frozenset()),
            data_dir=data_dir if data_dir is not None else cfg.workspace.data_path,
        )
    except (HydroModPyError, OSError) as exc:
        logger.debug("The request id of %s is not known offline: %s", cfg.simulation.name, exc)
        return None
    return request_id_of(cfg, resolved, search=keeps_search)


def solution_key_of(
    cfg: HydroModPyConfig,
    request: str,
    *,
    binaries: Mapping[str, str | os.PathLike[str] | None],
) -> str:
    """Return the solution key of the request id *request* of *cfg*, with its solver *binaries*."""
    return solution_key(
        request, mesh_engine=mesh_engine_identity(written_as_a_file(cfg)), binaries=binaries
    )


def _file_digest(path: Path) -> str:
    try:
        if path.is_file():
            return sha256_of(path)
        if path.is_dir():
            return sha256_directory(path)
    except OSError as exc:
        logger.warning("Input file %s not hashed into the request id: %s", path, exc)
        return f"unreadable:{uuid.uuid4().hex}"
    return "missing"


def planned_solution_key(cfg: HydroModPyConfig, *, search: bool = False) -> str | None:
    """Return the solution key of the case *cfg* describes, told offline, or None.

    This is the key a run of *cfg* would seal, built on :func:`planned_request_id`.
    A plan, a dry run and a calibration compare it to the key of a sealed run or
    session, never the request id itself. ``None`` when an input needs the
    network: the case then reads as not done, and the worker answers when it runs.
    """
    from hydromodpy.workflow.steps.prepare_solver.dispatch import solver_binaries

    found = planned_request_id(cfg, search=search)
    if found is None:
        return None
    return solution_key_of(cfg, found, binaries=solver_binaries(cfg, fetch=False))


def session_solution_key(cfg: HydroModPyConfig) -> str:
    """Return the solution key a calibration session of *cfg* seals, its search kept.

    It equals :func:`planned_solution_key` whenever the inputs resolve offline. A
    case that needs the network is told from the files it names alone, which no plan
    compares.
    """
    from hydromodpy.data.loading.inputs import ResolvedInputs
    from hydromodpy.workflow.steps.prepare_solver.dispatch import solver_binaries

    key = planned_solution_key(cfg, search=True)
    if key is not None:
        return key
    found = request_id_of(cfg, ResolvedInputs(), search=True)
    return solution_key_of(cfg, found, binaries=solver_binaries(cfg))


__all__ = [
    "SEARCH_SECTION",
    "input_digests",
    "planned_request_id",
    "planned_solution_key",
    "request_document",
    "request_id_of",
    "session_solution_key",
    "solution_key_of",
]
