"""Walk a Pydantic config tree and collect ``InputFile``-annotated paths."""

from __future__ import annotations

from pathlib import Path
from typing import Any, get_args

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from hydromodpy.core.tracking.input_file import InputFile, TrackedFileEntry


def collect_input_files(model: BaseModel) -> list[TrackedFileEntry]:
    """Return every tracked file declared under ``model``.

    The walker descends into nested ``BaseModel`` instances and into lists
    of models. Fields annotated with ``InputFile`` are collected when they
    hold a non-empty path value. ``None`` and empty strings are skipped.
    Canonicalisation uses ``expanduser`` then ``resolve`` so equivalent
    paths deduplicate on the resolved form.
    """
    seen: set[tuple[str, str]] = set()
    entries: list[TrackedFileEntry] = []
    _walk(model, seen, entries)
    return entries


def _walk(
    node: Any,
    seen: set[tuple[str, str]],
    entries: list[TrackedFileEntry],
) -> None:
    if isinstance(node, BaseModel):
        for field_name, field_info in type(node).model_fields.items():
            value = getattr(node, field_name, None)
            marker = _input_file_marker(field_info)
            if marker is not None:
                _record_path_value(marker, value, seen, entries)
            _walk(value, seen, entries)
        return

    if isinstance(node, (list, tuple)):
        for item in node:
            _walk(item, seen, entries)
        return

    if isinstance(node, dict):
        for item in node.values():
            _walk(item, seen, entries)


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
) -> None:
    raw = _extract_raw_path(value)
    if raw is None:
        return

    canonical = Path(raw).expanduser().resolve()
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
