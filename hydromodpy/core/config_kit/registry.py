"""Single source of truth for HydroModPy root TOML sections.

The registry is derived from ``root.model_fields`` so callers that need to
enumerate root sections (TOML scaffolding, JSON Schema export, interactive UI)
stay automatically in sync with the root model.
"""

from __future__ import annotations

from typing import get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from hydromodpy.core.config_kit.introspect import is_model, is_union_origin
from hydromodpy.core.config_kit.root import RootConfig, model_of


def _sequence_item_model(annotation: object) -> type[BaseModel] | None:
    """Return X behind ``list[X]`` or ``tuple[X, ...]`` when X is a model."""
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is list and len(args) == 1 and is_model(args[0]):
        return args[0]
    if origin is tuple and len(args) == 2 and args[1] is Ellipsis and is_model(args[0]):
        return args[0]
    return None


def _section_shape(annotation: object) -> tuple[type[BaseModel], bool] | None:
    """Return ``(model, repeated)`` for a root field that is a TOML section.

    ``X`` and ``Optional[X]`` are one ``[name]`` table. ``list[X]`` and
    ``tuple[X, ...]`` are an array of tables, one ``[[name]]`` block per
    entry. Anything else is a scalar and returns None.
    """
    candidates = get_args(annotation) if is_union_origin(get_origin(annotation)) else (annotation,)
    for arg in candidates:
        if is_model(arg):
            return arg, False
        item = _sequence_item_model(arg)
        if item is not None:
            return item, True
    return None


def _resolve_basemodel(annotation: object) -> type[BaseModel] | None:
    """Return the model class behind X, Optional[X], list[X] or tuple[X, ...]."""
    shape = _section_shape(annotation)
    return shape[0] if shape is not None else None


def root_sections(root: type[BaseModel] | RootConfig) -> dict[str, type[BaseModel]]:
    """Return the map of root TOML section names to Pydantic model classes.

    Iterates ``root.model_fields`` in declaration order and keeps only fields
    whose annotation resolves to a ``BaseModel`` subclass (scalars such as the
    ``workflow`` literal are skipped). A repeated section such as ``[[export]]``
    maps to the model of one entry; see :func:`repeated_root_sections`.
    Returns a fresh dict on each call so callers can safely mutate it.
    """
    root_cls = model_of(root)
    result: dict[str, type[BaseModel]] = {}
    for name, info in root_cls.model_fields.items():
        shape = _section_shape(info.annotation)
        if shape is None:
            continue
        result[name] = shape[0]
    return result


def repeated_root_sections(root: type[BaseModel] | RootConfig) -> frozenset[str]:
    """Return the root sections written as an array of tables (``[[name]]``)."""
    root_cls = model_of(root)
    repeated: set[str] = set()
    for name, info in root_cls.model_fields.items():
        shape = _section_shape(info.annotation)
        if shape is not None and shape[1]:
            repeated.add(name)
    return frozenset(repeated)


def root_scalar_fields(root: type[BaseModel] | RootConfig) -> dict[str, FieldInfo]:
    """Return root fields that are TOML scalars rather than sections."""
    root_cls = model_of(root)
    result: dict[str, FieldInfo] = {}
    for name, info in root_cls.model_fields.items():
        if _resolve_basemodel(info.annotation) is None:
            result[name] = info
    return result


__all__ = ["repeated_root_sections", "root_scalar_fields", "root_sections"]
