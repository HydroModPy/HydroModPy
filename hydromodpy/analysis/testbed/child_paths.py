"""Make the paths of a generated child config absolute, as its schema types them.

A testbed writes each child TOML in its own output folder, so a relative path
copied from the base config or from a case overlay would be read against the
wrong folder. Only the values the schema declares as paths are rewritten. The
schema says so in one of three ways:

- the field is typed ``Path`` (or a ``PurePath``), or carries ``InputFile``;
- the field is typed ``str`` and its name says it holds a path: ``path``,
  or a name ending in ``_path``, ``_file``, ``_dir``, ``_root`` or ``_folder``.
  These fields predate the ``Path`` typing and are read as paths by their
  loaders;
- the key is ``base_config``, the inheritance key of every TOML file, or one
  of the two comparison keys that name a simulation TOML.

Any other value is copied as written. The rule used before matched a key name
by substring anywhere in the tree, so ``track_dir = "forward"`` and
``profile = "x"`` came out as ``/base/forward`` and ``/base/x``.

A bare file name given to an ``InputFile`` field, and absent from the folder
of its source, is left bare: the child loader then looks it up in the data
folders of the workspace, as it would for a TOML written next to the file.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from pathlib import Path, PurePath
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from hydromodpy.core.config_kit.introspect import iter_basemodels
from hydromodpy.core.toml_io import is_declared_absolute_path
from hydromodpy.core.tracking.input_file import InputFile

PATH_NAME_SUFFIXES = ("_path", "_file", "_dir", "_root", "_folder")
"""Suffixes that mark a ``str`` field as a path."""

PATH_KEYS = frozenset({"base_config", "base_simulation_config", "simulation_config"})
"""Keys that name a TOML file, whatever their declared type."""

OVERLAY_KEYS = frozenset({"overlay", "base_simulation_overlay"})
"""Free mappings that hold a fragment of the root simulation config."""

_MERGE_SUFFIXES = ("__append", "__delete")


def root_simulation_model() -> type[BaseModel]:
    """The root config model, reached through the provider wired at bootstrap."""
    from hydromodpy.core.config_kit.root_config_protocol import get_root_config_provider

    return get_root_config_provider().root_model()


def comparison_model() -> type[BaseModel]:
    """The model of a comparison TOML file."""
    from hydromodpy.analysis.comparison.experiment_config import SimulationComparisonConfig

    return SimulationComparisonConfig


def absolutize_child_paths(
    payload: Mapping[str, Any],
    *,
    model: type[BaseModel],
    source_dir: Path,
) -> dict[str, Any]:
    """Return *payload* with each path the schema of *model* declares made absolute."""
    return _walk_mapping(payload, (model,), source_dir=Path(source_dir))


def _walk_mapping(
    mapping: Mapping[str, Any],
    models: tuple[type[BaseModel], ...],
    *,
    source_dir: Path,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw_key, value in mapping.items():
        key = str(raw_key)
        out[key] = _walk_value(key, value, models, source_dir=source_dir)
    return out


def _walk_value(
    key: str,
    value: Any,
    models: tuple[type[BaseModel], ...],
    *,
    source_dir: Path,
) -> Any:
    name = _field_key(key)
    if name in PATH_KEYS:
        return _absolutize(value, source_dir=source_dir, data_lookup=False)
    fields = [field for model in models if (field := _field_of(model, name)) is not None]
    if not fields:
        if name in OVERLAY_KEYS and isinstance(value, Mapping):
            return _walk_mapping(value, (root_simulation_model(),), source_dir=source_dir)
        return value
    if any(_is_path_field(name, field) for field in fields):
        return _absolutize(
            value,
            source_dir=source_dir,
            data_lookup=any(_is_input_file(field) for field in fields),
        )
    nested = tuple(
        dict.fromkeys(model for field in fields for model in iter_basemodels(field.annotation))
    )
    if nested:
        if any(_is_mapping_of_models(field.annotation) for field in fields) and isinstance(
            value, Mapping
        ):
            # The keys are names the user chose (a parameter, a boundary).
            return {
                str(entry): _walk_nested(item, nested, source_dir=source_dir)
                for entry, item in value.items()
            }
        return _walk_nested(value, nested, source_dir=source_dir)
    if name in OVERLAY_KEYS and isinstance(value, Mapping):
        return _walk_mapping(value, (root_simulation_model(),), source_dir=source_dir)
    return value


def _walk_nested(
    value: Any,
    models: tuple[type[BaseModel], ...],
    *,
    source_dir: Path,
) -> Any:
    if isinstance(value, Mapping):
        return _walk_mapping(value, models, source_dir=source_dir)
    if isinstance(value, list):
        return [_walk_nested(item, models, source_dir=source_dir) for item in value]
    return value


def _field_key(key: str) -> str:
    """The field a TOML key writes to, without its merge suffix."""
    for suffix in _MERGE_SUFFIXES:
        if key.endswith(suffix):
            return key[: -len(suffix)]
    return key


def _field_of(model: type[BaseModel], key: str) -> FieldInfo | None:
    field = model.model_fields.get(key)
    if field is not None:
        return field
    for candidate in model.model_fields.values():
        if candidate.alias == key:
            return candidate
    return None


def _is_input_file(field: FieldInfo) -> bool:
    return any(isinstance(meta, InputFile) for meta in field.metadata or ())


def _is_path_field(name: str, field: FieldInfo) -> bool:
    if _declares_path(field.annotation) or _is_input_file(field):
        return True
    if not _declares_plain_str(field.annotation):
        return False
    return name == "path" or name.endswith(PATH_NAME_SUFFIXES)


def _declares_path(annotation: Any) -> bool:
    if isinstance(annotation, type) and issubclass(annotation, PurePath):
        return True
    if get_origin(annotation) is Literal:
        return False
    return any(_declares_path(arg) for arg in get_args(annotation))


def _declares_plain_str(annotation: Any) -> bool:
    if annotation is str:
        return True
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return False
    if get_origin(annotation) is Literal:
        return False
    return any(_declares_plain_str(arg) for arg in get_args(annotation))


def _is_mapping_of_models(annotation: Any) -> bool:
    for node in (annotation, *get_args(annotation)):
        origin = get_origin(node)
        if not (isinstance(origin, type) and issubclass(origin, Mapping | dict)):
            continue
        args = get_args(node)
        if len(args) == 2 and iter_basemodels(args[1]):
            return True
    return False


def _absolutize(value: Any, *, source_dir: Path, data_lookup: bool) -> Any:
    if isinstance(value, list):
        return [_absolutize(item, source_dir=source_dir, data_lookup=data_lookup) for item in value]
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text in ("", "~") or "://" in text:
        return value
    declared = Path(text).expanduser()
    if is_declared_absolute_path(declared):
        return declared.as_posix()
    candidate = (source_dir / declared).resolve()
    if data_lookup and _is_bare_file_name(text) and not candidate.exists():
        return value
    return candidate.as_posix()


def _is_bare_file_name(text: str) -> bool:
    return "/" not in text and "\\" not in text and text not in (".", "..")


__all__ = [
    "OVERLAY_KEYS",
    "PATH_KEYS",
    "PATH_NAME_SUFFIXES",
    "absolutize_child_paths",
    "comparison_model",
    "root_simulation_model",
]
