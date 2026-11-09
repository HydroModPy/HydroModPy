"""The one loader of a configuration, and the one reader of a TOML file.

:func:`read_document` reads a TOML file, the files of its ``base_config`` chain,
its overlays and dotted changes, each file once, and returns the merged
document. :func:`load` validates a configuration given as a TOML path, a
mapping, JSON text or a built :class:`HydroModPyConfig`, always through the
same validator, with the same migration and the same refusals.

Relative paths are read from one base. A file is its own anchor: the project
root above it, else the folder of the root file of its chain, unless the caller
names ``base``, which wins. A document in memory has no folder of its own, so
it needs ``base`` and is refused without one; the current folder is never used.
Neither a file nor a document in memory may write ``[workspace] project_root``:
the base is an argument.
"""

from __future__ import annotations

import copy
import json
import os
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hydromodpy.config.hydromodpy_config import (
    ROOT_CONFIG,
    HydroModPyConfig,
    run_name_of_file,
)
from hydromodpy.core.config_kit.root import RootConfig
from hydromodpy.core.exceptions import (
    ConfigError,
    ConfigValidationError,
    IncompatibleCapabilitiesError,
)
from hydromodpy.core.toml_io.loader import (
    BASE_CONFIG_KEY,
    ChainFile,
    config_base_dir,
    merge_toml_layers,
    read_toml,
    read_toml_chain,
)
from hydromodpy.core.toml_io.merge import merge_toml_payloads
from hydromodpy.core.toml_io.overrides import SET_SOURCE
from hydromodpy.core.toml_io.paths import assign, is_declared_absolute_path

MEMORY_NEEDS_BASE = (
    "A configuration read from memory needs base=, the folder its relative paths are read from."
)
"""The refusal of a mapping or of JSON text loaded without a base."""

TOML_SUFFIX = ".toml"
"""The suffix of a configuration file."""

REQUEST_SUFFIX = ".json"
"""The suffix of a run request file, which ``hmp run`` reads and :func:`load` does not."""


class ConfigFileError(ConfigError):
    """A configuration file, or a file of its ``base_config`` chain, cannot be read."""


def read_document(
    path: str | os.PathLike[str],
    *,
    overlays: Sequence[str | os.PathLike[str]] = (),
    changes: Mapping[str, Any] | None = None,
    root: RootConfig | None,
) -> dict[str, Any]:
    """Return the document of the TOML file *path*, its overlays and *changes* merged.

    Each file of the ``base_config`` chain is read once and migrated on its own,
    then each overlay and its own chain, then *changes*, a mapping of dotted paths
    to values (the grammar of ``--set``), in this order. ``root=None`` reads the
    files as they are written. Only a ``.toml`` file is read here: a run request
    in JSON carries its whole document already.
    """
    document, _ = _read_files(Path(path), overlays=overlays, changes=changes, root=root)
    return document


def load(
    source: str | os.PathLike[str] | Mapping[str, Any] | HydroModPyConfig,
    base: str | os.PathLike[str] | None = None,
    *,
    changes: Mapping[str, Any] | None = None,
    source_path: str | os.PathLike[str] | None = None,
) -> HydroModPyConfig:
    """Return the validated configuration of *source*.

    Parameters
    ----------
    source
        The path of a ``.toml`` file, a mapping of sections, JSON text that holds
        one, or a :class:`HydroModPyConfig`, which comes back as it is.
    base
        The folder relative paths are read from. A file reads them from its
        project root when *base* is not given. A mapping or JSON text is
        refused without it.
    changes
        Values set on top of the document, by dotted path, the grammar of
        ``--set``. They are migrated as a layer of their own, so an old key name
        is told under ``--set``.
    source_path
        The file a mapping was read from, when there is one: it names the run
        when the document writes no ``[simulation] name``, it tells a sealed run
        configuration, and it locates an error.

    Raises
    ------
    ConfigError
        On a document refused by the validator, on a mapping without *base*, on a
        ``base_config`` key in a mapping, and on a file that is not ``.toml``.
    """
    if isinstance(source, HydroModPyConfig):
        return source.with_changes(changes) if changes else source
    if isinstance(source, Mapping):
        return _load_document(dict(source), base, changes=changes, source_path=source_path)
    if isinstance(source, str) and is_json_text(source):
        document = json_object(source, where="A JSON configuration")
        return _load_document(document, base, changes=changes, source_path=source_path)
    if isinstance(source, (str, os.PathLike)):
        return _load_file(Path(source), base, changes=changes)
    raise TypeError(
        "load takes the path of a TOML file, a mapping, JSON text or a HydroModPyConfig, "
        f"not {type(source).__name__}."
    )


def is_json_text(text: str) -> bool:
    """Whether *text* is JSON text of an object rather than the path of a file."""
    return text.lstrip().startswith("{")


def json_object(text: str | bytes, *, where: str) -> dict[str, Any]:
    """Return the JSON object *text* holds, or refuse it, naming *where* it came from."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{where} is not valid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ConfigValidationError(
            f"{where} holds a {type(payload).__name__}, and a configuration is a table of sections.",
            details=(
                {
                    "pointer": "",
                    "loc": "<root>",
                    "msg": "Input should be a valid dictionary",
                    "type": "dict_type",
                },
            ),
        )
    return dict(payload)


def changes_payload(changes: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return *changes*, a mapping of dotted paths to values, as nested tables."""
    payload: dict[str, Any] = {}
    for dotted, value in (changes or {}).items():
        try:
            assign(payload, dotted, value)
        except ValueError as exc:
            raise ConfigError(f"--set {dotted}: {exc}") from exc
    return payload


def refuse_base_config(document: Mapping[str, Any]) -> None:
    """Refuse a document in memory that names a ``base_config`` file to inherit."""
    if BASE_CONFIG_KEY in document:
        raise ConfigError(
            "base_config is a key of a TOML file. A document in memory carries the whole "
            "configuration: merge the file it names into it, or load that file."
        )


def refuse_file_type(path: Path) -> None:
    """Refuse a configuration file *path* whose suffix this loader does not read."""
    if path.suffix == TOML_SUFFIX:
        return
    if path.suffix == REQUEST_SUFFIX:
        raise ConfigError(
            f"{path.name} is a run request, not a configuration file. hmp run reads it, and "
            "hydromodpy.project.request.request_of reads it in Python."
        )
    if path.suffix == ".py":
        raise ConfigError(
            "Python scripts are not supported by 'hmp run'. Run the script with python directly."
        )
    raise ConfigError(f"Unsupported file type: {path.suffix} (expected .toml or .json)")


def _load_file(
    path: Path, base: str | os.PathLike[str] | None, *, changes: Mapping[str, Any] | None
) -> HydroModPyConfig:
    """Read the TOML file *path* once and validate it."""
    target = Path(path).expanduser().resolve()
    refuse_file_type(target)
    document, chains = _read_files(target, overlays=(), changes=changes, root=ROOT_CONFIG)
    folder = (
        Path(base).expanduser().resolve()
        if base is not None
        else config_base_dir(target, chain=chains[0])
    )
    try:
        cfg = HydroModPyConfig._from_payload(
            document, base=folder, context="toml", source_path=target
        )
    except IncompatibleCapabilitiesError as exc:
        # A typed capability error of a rule does not carry the location of the file;
        # it is put in front, keeping the type, the error code and the diagnostics.
        raise type(exc)(f"{target}: {exc.message or exc}", diagnostics=exc.diagnostics) from exc
    return _named(cfg, target)


def _load_document(
    document: dict[str, Any],
    base: str | os.PathLike[str] | None,
    *,
    changes: Mapping[str, Any] | None,
    source_path: str | os.PathLike[str] | None,
) -> HydroModPyConfig:
    """Validate a document in memory against *base*, with its migration and its refusals."""
    if base is None:
        raise ConfigError(MEMORY_NEEDS_BASE)
    refuse_base_config(document)
    folder = Path(base).expanduser().resolve()
    named = None if source_path is None else Path(source_path).expanduser().resolve()
    merged = _migrated(copy.deepcopy(document), changes, root=ROOT_CONFIG)
    cfg = HydroModPyConfig._from_payload(merged, base=folder, context="request", source_path=named)
    return cfg if named is None else _named(cfg, named)


def _migrated(
    document: dict[str, Any], changes: Mapping[str, Any] | None, *, root: RootConfig
) -> dict[str, Any]:
    """Migrate *document* and *changes* as two layers, then merge them, as a file is."""
    payload = changes_payload(changes)
    layers: list[tuple[str | Path | None, dict[str, Any]]] = [(None, document)]
    if payload:
        layers.append((SET_SOURCE, payload))
    root.migrate_layers(layers)
    merged = merge_toml_payloads(document, cli_overrides=payload or None)
    root.migrate_merged(merged, layers)
    return merged


def _named(cfg: HydroModPyConfig, path: Path) -> HydroModPyConfig:
    """Name the run after the file *path* when the document writes no name."""
    if not cfg.simulation.name:
        cfg.simulation.name = run_name_of_file(path)
    return cfg


def _read_files(
    path: Path,
    *,
    overlays: Sequence[str | os.PathLike[str]],
    changes: Mapping[str, Any] | None,
    root: RootConfig | None,
) -> tuple[dict[str, Any], list[tuple[ChainFile, ...]]]:
    """Return the merged document and the chains read, each file read once."""
    files = [Path(item).expanduser().resolve() for item in (path, *overlays)]
    for item in files:
        if item.suffix != TOML_SUFFIX:
            raise ConfigError(
                f"{item.name} is not a TOML file. Only a .toml file and .toml overlays are "
                "read as layers; a run request in JSON carries its whole document under config."
            )
    chains = [_read_chain(item) for item in files]
    try:
        document = merge_toml_layers(
            chains, root=root, cli_overrides=changes_payload(changes) or None
        )
    except (TypeError, ValueError) as exc:
        raise ConfigFileError(f"Invalid configuration file {files[0]}: {exc}") from exc
    return document, chains


def _read_chain(path: Path) -> tuple[ChainFile, ...]:
    """Read the chain of *path* as written, naming the file at fault."""
    try:
        return read_toml_chain(path, root=None)
    except tomllib.TOMLDecodeError as exc:
        culprit = _first_unreadable_file(path) or path
        raise ConfigFileError(f"Invalid TOML in {culprit}: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise ConfigFileError(f"Invalid configuration file {path}: {exc}") from exc


def _first_unreadable_file(path: Path) -> Path | None:
    """Follow the chain from *path* and return the first file that does not parse.

    Called only once a parse failed, to name the file at fault.
    """
    seen: set[Path] = set()
    current: Path | None = path.resolve()
    while current is not None and current not in seen:
        seen.add(current)
        try:
            raw = read_toml(current)
        except tomllib.TOMLDecodeError:
            return current
        except OSError:
            return None
        named = raw.get(BASE_CONFIG_KEY)
        if not isinstance(named, str) or not named:
            return None
        parent = Path(named).expanduser()
        if not is_declared_absolute_path(parent):
            parent = current.parent / parent
        current = parent.resolve()
    return None


__all__ = [
    "MEMORY_NEEDS_BASE",
    "REQUEST_SUFFIX",
    "TOML_SUFFIX",
    "ConfigFileError",
    "changes_payload",
    "is_json_text",
    "json_object",
    "load",
    "read_document",
    "refuse_base_config",
    "refuse_file_type",
]
