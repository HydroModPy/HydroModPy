"""Replay a published run copy from its own bytes: ``hmp run <copy>/config.toml --frozen``.

Why
---
``hmp publish <run> --with inputs`` copies a run with the bytes of every
file it read under ``inputs/<sha256><suffix>``. The frozen ``config.toml``
of the copy names those files by paths of the machine that ran it, which the
publication redacts. A replay elsewhere, without that workspace and without
its data cache, finds each file by content instead: every input the seal
records (``manifest.json``, ``inputs``) has a role and a digest; the field of
the configuration marked with that role (:class:`~hydromodpy.core.tracking.
input_file.InputFile`) is pointed at ``inputs/<sha256><suffix>``, after the
digest of those bytes is checked. ``--frozen`` on a copy means exactly this
check: every input of the seal is in ``inputs/`` with the digest the run
sealed, or the replay is refused before anything runs.
"""

from __future__ import annotations

import hashlib
import types
import typing
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.results.export.publish import INPUTS_DIRNAME
from hydromodpy.results.storage.contract import PUBLICATION_FILENAME, RUN_MANIFEST_FILENAME


class ReplayInputError(ConfigError):
    """An input of a published copy is missing from ``inputs/`` or has another digest."""


def published_copy_of(config_path: Path) -> Path | None:
    """Return the published copy *config_path* is the frozen configuration of, or None."""
    folder = Path(config_path).resolve().parent
    if (folder / PUBLICATION_FILENAME).is_file() and (folder / RUN_MANIFEST_FILENAME).is_file():
        return folder
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def input_files_by_role(copy_dir: Path) -> dict[str, Path]:
    """Return the file of ``inputs/`` that holds each input the seal records, by role.

    Raises :class:`ReplayInputError` when an input is missing or its bytes
    do not have the digest the run sealed.
    """
    from hydromodpy.results.manifest import read_manifest

    manifest = read_manifest(copy_dir)
    folder = Path(copy_dir) / INPUTS_DIRNAME
    found: dict[str, Path] = {}
    for entry in manifest.get("inputs") or ():
        role, sha256 = entry.get("role"), entry.get("sha256")
        if not role or not sha256:
            continue
        matches = sorted(folder.glob(f"{sha256}*")) if folder.is_dir() else []
        if not matches:
            raise ReplayInputError(
                f"--frozen: the input {role!r} ({sha256[:12]}) is not in {folder}; publish the run "
                "with --with inputs to replay it alone."
            )
        if _sha256(matches[0]) != sha256:
            raise ReplayInputError(
                f"--frozen: {matches[0].name} does not have the digest the run sealed for {role!r}."
            )
        found[str(role)] = matches[0]
    return found


def _input_role(field: FieldInfo) -> str | None:
    for meta in field.metadata:
        if isinstance(meta, InputFile):
            return meta.role
    return None


def _models_of(annotation: Any) -> list[type[BaseModel]]:
    """Return the model classes an annotation may hold: unions and ``Annotated`` unwrapped."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        return _models_of(typing.get_args(annotation)[0])
    if origin in (typing.Union, types.UnionType):
        out: list[type[BaseModel]] = []
        for arg in typing.get_args(annotation):
            out.extend(_models_of(arg))
        return out
    return []


def _point_inputs(
    payload: dict[str, Any], models: list[type[BaseModel]], files: Mapping[str, Path]
) -> None:
    """Point every field of *payload* marked with a role of *files* at its file, in place."""
    for key, value in list(payload.items()):
        for model in models:
            field = model.model_fields.get(key)
            if field is None:
                continue
            role = _input_role(field)
            if role is not None and role in files and isinstance(value, str):
                payload[key] = str(files[role])
            elif isinstance(value, dict):
                _point_inputs(value, _models_of(field.annotation), files)


def replay_payload(copy_dir: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return *payload* with every recorded input pointed at the bytes of the copy.

    Raises :class:`ReplayInputError` when an input of the seal is missing
    from ``inputs/`` or has another digest.
    """
    import copy

    from hydromodpy.config.hydromodpy_config import HydroModPyConfig

    files = input_files_by_role(copy_dir)
    document = copy.deepcopy(dict(payload))
    if files:
        _point_inputs(document, [HydroModPyConfig], files)
    return document


__all__ = [
    "ReplayInputError",
    "input_files_by_role",
    "published_copy_of",
    "replay_payload",
]
