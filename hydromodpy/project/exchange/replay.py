"""Replay a published run copy from its own bytes: ``hmp replay <copy>``.

Why
---
``hmp publish <run>`` copies a run with every file it read,
stored by content under ``inputs/``, and the install index ``INSTALL.toml``
that says where each file sits in a workspace (:mod:`hydromodpy.core.payload`).
A replay elsewhere, without that workspace and without its data cache, finds
each input of the seal by its role: every input the seal records
(``manifest.json``, ``inputs``) has a role and a path relative to the
workspace, and the field of the configuration marked with that role
(:class:`~hydromodpy.core.tracking.input_file.InputFile`) is pointed at the
bytes of the copy. A declared file is read in ``inputs/`` where it is. A
declared folder is rebuilt under a work directory from the files of the index
that sit in it, with the station rows its registries need: the copy never
carries a folder whole.

A replay of a copy means: every file of the index is in ``inputs/`` with its
digest, or it is refused before anything runs. A file a provider delivered
(Hub'Eau, SIM2, BD Topage) is installed by its digest in the workspace of the
project the replay writes into, with its sidecar and its data cache row, so the
run reads the cache and fetches nothing. A file already there with another
digest is refused by the install, and nothing is written.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.payload import (
    INSTALL_FILENAME,
    InstallIndex,
    PayloadFile,
    read_index,
    stored_name,
)
from hydromodpy.core.payload.install import plan_stations, sha256_of, write_stations
from hydromodpy.core.tracking import rewrite_input_paths
from hydromodpy.core.workspace.resolve import locate_workspace_root
from hydromodpy.results.export.publish import INPUTS_DIRNAME
from hydromodpy.results.storage.contract import PUBLICATION_FILENAME, RUN_MANIFEST_FILENAME
from hydromodpy.schema.sources import source_entry


def _provider_of(item: Any) -> str | None:
    """The provider an install index entry names, read under today's name.

    A copy sealed before 2.1.0 writes ``custom`` where the same file now seals
    ``file``; the sidecar migration reads the old name as the new one, so the
    replay installs the same files whatever sealed the copy.
    """
    if item.provider is None:
        return None
    return "file" if item.provider == "custom" else str(item.provider)


class ReplayInputError(ConfigError):
    """An input of a published copy is missing from ``inputs/`` or has another digest."""


def published_copy_of(config_path: Path) -> Path | None:
    """Return the published copy *config_path* is the frozen configuration of, or None."""
    folder = Path(config_path).resolve().parent
    if (folder / PUBLICATION_FILENAME).is_file() and (folder / RUN_MANIFEST_FILENAME).is_file():
        return folder
    return None


def checked_index(copy_dir: Path) -> InstallIndex:
    """Return the install index of a copy once every file it lists is in ``inputs/``.

    Raises :class:`ReplayInputError` for a copy without an index, a file
    missing from ``inputs/`` or bytes with another digest.
    """
    copy = Path(copy_dir)
    if not (copy / INSTALL_FILENAME).is_file():
        raise ReplayInputError(
            f"hmp replay: {copy.name} carries no {INSTALL_FILENAME}; the copy was "
            "published with --without inputs: publish the run again without that option to "
            "replay it alone."
        )
    index = read_index(copy)
    folder = copy / INPUTS_DIRNAME
    for item in index.files:
        stored = folder / stored_name(item.sha256, item.dest)
        if not stored.is_file():
            raise ReplayInputError(
                f"hmp replay: {item.dest} ({item.sha256[:12]}) is not in {folder}; the copy was "
                "published with --without inputs: publish the run again without that option "
                "to replay it alone."
            )
        if sha256_of(stored) != item.sha256:
            raise ReplayInputError(
                f"hmp replay: {stored.name} does not have the digest of {item.dest}."
            )
    return index


def input_files_by_role(copy_dir: Path, workdir: Path) -> dict[str, Path]:
    """Return the file or folder that holds each input the seal records.

    The key is the value the configuration declared for the input, which is
    unique to it. Two inputs of one role keep their own bytes. The role is a
    second key only when one input has it.

    A declared file is its stored bytes under ``inputs/``. A declared folder
    is rebuilt under *workdir*, at the path the seal records, from the files
    of the index that sit in it and the station rows of its registries.
    """
    from hydromodpy.results.publication import read_publication
    from hydromodpy.results.record.manifest import read_manifest

    copy = Path(copy_dir)
    index = checked_index(copy)
    project = read_publication(copy).source.project
    by_path = {_workspace_path(item, project): item for item in index.files}
    found: dict[str, Path] = {}
    roles: dict[str, int] = {}
    for entry in read_manifest(copy).get("inputs") or ():
        role, path = entry.get("role"), entry.get("path")
        if not role or not path:
            continue
        key = str(entry.get("declared_path") or role)
        roles[str(role)] = roles.get(str(role), 0) + 1
        item = by_path.get(str(path))
        if item is not None:
            found[key] = copy / INPUTS_DIRNAME / stored_name(item.sha256, item.dest)
            continue
        members = [(key, member) for key, member in by_path.items() if key.startswith(f"{path}/")]
        if not members:
            raise ReplayInputError(
                f"hmp replay: the input {role!r} ({path}) is not in {INSTALL_FILENAME}; the copy "
                "was published with --without inputs: publish the run again without that "
                "option to replay it alone."
            )
        found[key] = _rebuilt_folder(copy, index, workdir, str(path), members)
    for entry in read_manifest(copy).get("inputs") or ():
        role = str(entry.get("role") or "")
        key = str(entry.get("declared_path") or role)
        if role and roles.get(role) == 1 and key in found:
            found.setdefault(role, found[key])
    return found


def _workspace_path(item: PayloadFile, project: str) -> str:
    """Return the path of an index file relative to the workspace it was published from."""
    return item.dest if item.root == "workspace" else f"projects/{project}/{item.dest}"


def _rebuilt_folder(
    copy: Path,
    index: InstallIndex,
    workdir: Path,
    path: str,
    members: list[tuple[str, PayloadFile]],
) -> Path:
    """Rebuild one declared folder under *workdir* from the files of the index in it."""
    for key, item in members:
        target = workdir / key
        target.parent.mkdir(parents=True, exist_ok=True)
        stored = copy / INPUTS_DIRNAME / stored_name(item.sha256, item.dest)
        try:
            os.link(stored, target)
        except OSError:
            shutil.copyfile(stored, target)
    rows = [station for station in index.stations if station.dest.startswith(f"{path}/")]
    write_stations(plan_stations(workdir, rows))
    return workdir / path


def _delivered(item: PayloadFile) -> bool:
    """Whether a provider delivered the file: its provider is a source with a publisher."""
    provider = _provider_of(item)
    if provider is None:
        return False
    entry = source_entry(provider)
    return entry is None or entry.publisher is not None


def _install_delivered_inputs(copy: Path, index: InstallIndex, project_root: Path) -> None:
    """Install the files a provider delivered by their digest, in the workspace of the project.

    The data cache of the project then serves them, so the replay reads it and
    fetches nothing. A file of the same destination with another digest is
    refused by the install, which writes nothing in that case.
    """
    from hydromodpy.project.exchange.install import install_index

    delivered = [item for item in index.files if _delivered(item)]
    if not delivered:
        return
    install_index(
        index,
        blobs=copy / INPUTS_DIRNAME,
        workspace=locate_workspace_root(project_root) or project_root,
        project=project_root,
        files=delivered,
    )


def replay_payload(
    copy_dir: Path, payload: Mapping[str, Any], *, workdir: Path, project_root: Path
) -> dict[str, Any]:
    """Return *payload* with every recorded input pointed at the bytes of the copy.

    Declared folders are rebuilt under *workdir*, which the caller removes
    after the run. The files a provider delivered are installed in the workspace
    of *project_root*. Raises :class:`ReplayInputError` when an input of the seal
    is missing from the copy or has another digest, and the conflict error of the
    install when a delivered file meets other bytes at its destination.
    """
    import copy

    from hydromodpy.config.hydromodpy_config import HydroModPyConfig

    files = input_files_by_role(copy_dir, workdir)
    _install_delivered_inputs(Path(copy_dir), read_index(Path(copy_dir)), Path(project_root))
    document = copy.deepcopy(dict(payload))
    if files:
        rewrite_input_paths(
            document,
            HydroModPyConfig,
            lambda marker, value: str(files.get(value) or files.get(marker.role) or value),
        )
    return document


__all__ = [
    "ReplayInputError",
    "checked_index",
    "input_files_by_role",
    "published_copy_of",
    "replay_payload",
]
