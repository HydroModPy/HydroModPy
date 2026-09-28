"""Single source of truth for HydroModPy root TOML sections.

The registry is derived from ``HydroModPyConfig.model_fields`` so callers
that need to enumerate root sections (TOML scaffolding, JSON Schema export,
interactive UI) stay automatically in sync with the root model.
"""

from __future__ import annotations

import types as _stdlib_types
import typing
from typing import TypeGuard, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from hydromodpy.core.config_kit.root_config_protocol import get_root_config_provider

_CACHE: dict[str, type[BaseModel]] | None = None
_REPEATED_CACHE: frozenset[str] | None = None
_SCALAR_CACHE: dict[str, FieldInfo] | None = None


def _is_union_origin(origin: object) -> bool:
    if origin is typing.Union:
        return True
    if hasattr(_stdlib_types, "UnionType") and origin is _stdlib_types.UnionType:
        return True
    return False


def _is_model(annotation: object) -> TypeGuard[type[BaseModel]]:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _sequence_item_model(annotation: object) -> type[BaseModel] | None:
    """Return X behind ``list[X]`` or ``tuple[X, ...]`` when X is a model."""
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is list and len(args) == 1 and _is_model(args[0]):
        return args[0]
    if origin is tuple and len(args) == 2 and args[1] is Ellipsis and _is_model(args[0]):
        return args[0]
    return None


def _section_shape(annotation: object) -> tuple[type[BaseModel], bool] | None:
    """Return ``(model, repeated)`` for a root field that is a TOML section.

    ``X`` and ``Optional[X]`` are one ``[name]`` table. ``list[X]`` and
    ``tuple[X, ...]`` are an array of tables, one ``[[name]]`` block per
    entry. Anything else is a scalar and returns None.
    """
    candidates = get_args(annotation) if _is_union_origin(get_origin(annotation)) else (annotation,)
    for arg in candidates:
        if _is_model(arg):
            return arg, False
        item = _sequence_item_model(arg)
        if item is not None:
            return item, True
    return None


def _resolve_basemodel(annotation: object) -> type[BaseModel] | None:
    """Return the model class behind X, Optional[X], list[X] or tuple[X, ...]."""
    shape = _section_shape(annotation)
    return shape[0] if shape is not None else None


def _scan_sections() -> tuple[dict[str, type[BaseModel]], frozenset[str]]:
    global _CACHE, _REPEATED_CACHE
    if _CACHE is None or _REPEATED_CACHE is None:
        root_cls = get_root_config_provider().root_model()

        result: dict[str, type[BaseModel]] = {}
        repeated: set[str] = set()
        for name, info in root_cls.model_fields.items():
            shape = _section_shape(info.annotation)
            if shape is None:
                continue
            result[name] = shape[0]
            if shape[1]:
                repeated.add(name)
        _CACHE = result
        _REPEATED_CACHE = frozenset(repeated)
    return _CACHE, _REPEATED_CACHE


def root_sections() -> dict[str, type[BaseModel]]:
    """Return the map of root TOML section names to Pydantic model classes.

    Iterates ``HydroModPyConfig.model_fields`` in declaration order and
    keeps only fields whose annotation resolves to a ``BaseModel`` subclass
    (scalars such as the ``workflow`` literal are skipped). A repeated
    section such as ``[[export]]`` maps to the model of one entry; see
    :func:`repeated_root_sections`. Returns a fresh dict on each call so
    callers can safely mutate it.
    """
    return dict(_scan_sections()[0])


def repeated_root_sections() -> frozenset[str]:
    """Return the root sections written as an array of tables (``[[name]]``)."""
    return _scan_sections()[1]


def root_scalar_fields() -> dict[str, FieldInfo]:
    """Return root fields that are TOML scalars rather than sections."""
    global _SCALAR_CACHE
    if _SCALAR_CACHE is None:
        root_cls = get_root_config_provider().root_model()

        result: dict[str, FieldInfo] = {}
        for name, info in root_cls.model_fields.items():
            if _resolve_basemodel(info.annotation) is None:
                result[name] = info
        _SCALAR_CACHE = result
    return dict(_SCALAR_CACHE)


__all__ = ["repeated_root_sections", "root_scalar_fields", "root_sections"]
