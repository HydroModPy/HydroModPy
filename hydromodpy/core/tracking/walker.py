"""Walk a Pydantic config tree and collect ``InputFile``-annotated paths."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from types import UnionType
from typing import Annotated, Any, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from hydromodpy.core.tracking.input_file import InputFile, TrackedFileEntry


def collect_input_files(
    model: BaseModel,
    *,
    base: Path | str | None = None,
) -> list[TrackedFileEntry]:
    """Return every tracked file declared under ``model``.

    The walker descends into nested ``BaseModel`` instances and into lists
    of models. Fields annotated with ``InputFile`` are collected when they
    hold a non-empty path value. ``None`` and empty strings are skipped.
    Canonicalisation uses ``expanduser`` then ``resolve`` so equivalent
    paths deduplicate on the resolved form.

    ``base`` anchors a relative path. Without it a bare filename resolves
    against the shell's working directory, so the same configuration tracked
    its files or lost them depending on where it was launched from.
    """
    seen: set[tuple[str, str]] = set()
    entries: list[TrackedFileEntry] = []
    root = Path(base).expanduser().resolve() if base is not None else None
    _walk(model, seen, entries, root)
    return entries


def _walk(
    node: Any,
    seen: set[tuple[str, str]],
    entries: list[TrackedFileEntry],
    base: Path | None = None,
) -> None:
    if isinstance(node, BaseModel):
        for field_name, field_info in type(node).model_fields.items():
            value = getattr(node, field_name, None)
            marker = _input_file_marker(field_info)
            if marker is not None:
                _record_path_value(marker, value, seen, entries, base)
            _walk(value, seen, entries, base)
        return

    if isinstance(node, (list, tuple)):
        for item in node:
            _walk(item, seen, entries, base)
        return

    if isinstance(node, dict):
        for item in node.values():
            _walk(item, seen, entries, base)


def _input_file_marker(field_info: FieldInfo) -> InputFile | None:
    for meta in field_info.metadata:
        if isinstance(meta, InputFile):
            return meta
    return None


def _record_path_value(
    marker: InputFile,
    value: Any,
    seen: set[tuple[str, str]],
    entries: list[TrackedFileEntry],
    base: Path | None = None,
) -> None:
    raw = _extract_raw_path(value)
    if raw is None:
        return

    candidate = Path(raw).expanduser()
    if candidate.is_absolute() or base is None:
        canonical = candidate.resolve()
    else:
        anchored = (base / candidate).resolve()
        canonical = anchored if anchored.exists() else candidate.resolve()
    key = (marker.role, str(canonical))
    if key in seen:
        return
    seen.add(key)

    entries.append(
        TrackedFileEntry(
            role=marker.role,
            category=marker.category,
            original_path=str(raw),
            canonical_path=canonical,
            portable=bool(marker.portable),
        )
    )


def _extract_raw_path(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        token = value.strip()
        return token or None
    return None


def _contains_path_type(annotation: Any) -> bool:
    if annotation is Path:
        return True
    args = get_args(annotation)
    return any(_contains_path_type(arg) for arg in args)


def rewrite_input_paths(
    payload: dict[str, Any],
    model: type[BaseModel],
    rewrite: Callable[[InputFile, str], str],
) -> None:
    """Replace, in place, every ``InputFile`` path of a config document by ``rewrite(marker, value)``.

    The document is the plain mapping a TOML file or ``model_dump`` gives;
    *model* is the class it validates against. The walk follows the fields of
    the model into nested tables, lists of tables and tables of tables, and
    tries every member of a union.
    """
    _rewrite(payload, [model], rewrite)


def _rewrite(
    payload: dict[str, Any],
    models: list[type[BaseModel]],
    rewrite: Callable[[InputFile, str], str],
) -> None:
    for key, value in list(payload.items()):
        field_info = next(
            (model.model_fields[key] for model in models if key in model.model_fields), None
        )
        if field_info is None:
            continue
        marker = _input_file_marker(field_info)
        if marker is not None and isinstance(value, str) and value.strip():
            payload[key] = rewrite(marker, value)
            continue
        inner, keyed = _models_of(field_info.annotation)
        if not inner:
            continue
        if isinstance(value, dict) and keyed:
            for item in value.values():
                if isinstance(item, dict):
                    _rewrite(item, inner, rewrite)
        elif isinstance(value, dict):
            _rewrite(value, inner, rewrite)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _rewrite(item, inner, rewrite)


def _models_of(annotation: Any) -> tuple[list[type[BaseModel]], bool]:
    """Return the models an annotation may hold, and whether they are the values of a mapping."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation], False
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Annotated:
        return _models_of(args[0])
    if origin in (dict, Mapping) and len(args) == 2:
        return _models_of(args[1])[0], True
    models: list[type[BaseModel]] = []
    keyed = False
    if origin in (list, tuple, Union, UnionType):
        for arg in args:
            found, mapped = _models_of(arg)
            models.extend(found)
            keyed = keyed or mapped
    return models, keyed
